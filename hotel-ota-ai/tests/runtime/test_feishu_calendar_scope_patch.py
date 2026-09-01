from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_calendar_scope_patch import (
    install,
    parse_calendar_season_tag_command,
    parse_calendar_season_tag_query,
)

install()

from runtime.decisions import calendar as calendar_module
from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth
from runtime.storage import connect, init_schema


class TestFeishuCalendarScopePatch(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "control.sqlite")
        self.auth_config = root / "role-map.json"
        self.auth_config.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": [],
                    "users": [
                        {
                            "principal_id": "owner-1",
                            "open_id": "ou_owner",
                            "display_name": "Owner",
                        },
                        {
                            "principal_id": "target-b",
                            "open_id": "ou_target_b",
                            "display_name": "李四",
                        },
                    ],
                    "hotel_memberships": [
                        {
                            "principal_id": "owner-1",
                            "hotel_id": "hotel-a",
                            "role": "owner",
                        },
                        {
                            "principal_id": "target-b",
                            "hotel_id": "hotel-a",
                            "role": "operator",
                        },
                    ],
                    "group_chat_bindings": [
                        {"chat_id": "oc_group_a", "hotel_id": "hotel-a"},
                        {"chat_id": "oc_group_b", "hotel_id": "hotel-a"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))
        with connect(self.db_path) as conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO chat_role_memberships (
                  chat_id_hash, hotel_id, principal_id, role, status, created_at, updated_at
                ) VALUES (?, 'hotel-a', 'target-b', 'operator', 'active', ?, ?)
                """,
                (
                    hashlib.sha256(b"feishu-chat:oc_group_b").hexdigest(),
                    "2026-08-06T00:00:00",
                    "2026-08-06T00:00:00",
                ),
            )
            conn.commit()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _route(self, message: str, *, render: bool = False) -> dict:
        return safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id="oc_group_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.auth_config),
            production_feishu=True,
            render=render,
        )

    def test_parser_accepts_exact_range_and_whole_month(self) -> None:
        range_payload = parse_calendar_season_tag_command(
            "将2026-08-01至2026-08-31设为旺季"
        )
        self.assertEqual(range_payload["status"], "ok")
        self.assertEqual(range_payload["season_tag"], "旺季")
        self.assertEqual(range_payload["operation"], "set")
        self.assertEqual(range_payload["day_count"], 31)

        month_payload = parse_calendar_season_tag_command("将2026年9月设置为平季")
        self.assertEqual(month_payload["start_date"], "2026-09-01")
        self.assertEqual(month_payload["end_date"], "2026-09-30")
        self.assertEqual(month_payload["season_tag"], "平季")
        self.assertEqual(month_payload["day_count"], 30)

    def test_parser_distinguishes_discrete_dates_from_range(self) -> None:
        payload = parse_calendar_season_tag_command(
            "将2026-08-07和2026-08-09设为旺季"
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["scope_kind"], "date_list")
        self.assertEqual(payload["target_dates"], ["2026-08-07", "2026-08-09"])
        self.assertEqual(payload["day_count"], 2)

    def test_reset_phrase_without_resolved_dates_is_not_routed_to_menu(self) -> None:
        result = self._route("将这俩天改回原来的标签吧", render=True)

        self.assertEqual(result["intent"], "calendar_season_tag_write")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "calendar_season_exact_date_required")
        self.assertEqual(result["runtime_command"], "calendar-season-tag-reset")
        self.assertIn("明确日期", result["send_payload"]["text"])

    def test_owner_can_write_calendar_days_season_tag_from_bound_group(self) -> None:
        result = self._route("将2026-08-01至2026-08-03设为旺季", render=True)
        self.assertEqual(result["intent"], "calendar_season_tag_write")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["sqlite_written"])
        self.assertTrue(result["readback_verified"])
        self.assertEqual(result["updated_rows"], 3)

        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date, season_tag FROM calendar_days WHERE date BETWEEN '2026-08-01' AND '2026-08-03' ORDER BY date"
            ).fetchall()
        self.assertEqual([row["season_tag"] for row in rows], ["旺季", "旺季", "旺季"])

    def test_discrete_write_does_not_touch_date_between_targets(self) -> None:
        result = self._route("将2026-08-07和2026-08-09设为旺季")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["updated_rows"], 2)

        defaults = {
            str(row["date"]): str(row["season_tag"])
            for row in calendar_module.build_calendar_days(2026)
        }
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date, season_tag FROM calendar_days WHERE date BETWEEN '2026-08-07' AND '2026-08-09' ORDER BY date"
            ).fetchall()
        actual = {str(row["date"]): str(row["season_tag"]) for row in rows}
        self.assertEqual(actual["2026-08-07"], "旺季")
        self.assertEqual(actual["2026-08-08"], defaults["2026-08-08"])
        self.assertEqual(actual["2026-08-09"], "旺季")

    def test_reset_restores_authoritative_default_without_touching_other_manual_date(self) -> None:
        self.assertEqual(self._route("将2026-08-07和2026-08-09设为旺季")["status"], "ok")
        self.assertEqual(self._route("将2026-08-08设为平季")["status"], "ok")

        result = self._route(
            "将2026-08-07和2026-08-09恢复为系统默认",
            render=True,
        )
        self.assertEqual(result["intent"], "calendar_season_tag_write")
        self.assertEqual(result["runtime_command"], "calendar-season-tag-reset")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["updated_rows"], 2)
        self.assertTrue(result["readback_verified"])
        self.assertEqual(
            [item["date"] for item in result["restored_tags"]],
            ["2026-08-07", "2026-08-09"],
        )

        defaults = {
            str(row["date"]): str(row["season_tag"])
            for row in calendar_module.build_calendar_days(2026)
        }
        with connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT date, season_tag FROM calendar_days WHERE date BETWEEN '2026-08-07' AND '2026-08-09' ORDER BY date"
            ).fetchall()
        actual = {str(row["date"]): str(row["season_tag"]) for row in rows}
        self.assertEqual(actual["2026-08-07"], defaults["2026-08-07"])
        self.assertEqual(actual["2026-08-08"], "平季")
        self.assertEqual(actual["2026-08-09"], defaults["2026-08-09"])

        sync_result = calendar_module.sync_calendar_year(self.db_path, 2026)
        self.assertEqual(sync_result["manual_season_tags_preserved"], 1)
        with connect(self.db_path) as conn:
            after_sync = {
                str(row["date"]): str(row["season_tag"])
                for row in conn.execute(
                    "SELECT date, season_tag FROM calendar_days WHERE date BETWEEN '2026-08-07' AND '2026-08-09' ORDER BY date"
                ).fetchall()
            }
        self.assertEqual(after_sync["2026-08-07"], defaults["2026-08-07"])
        self.assertEqual(after_sync["2026-08-08"], "平季")
        self.assertEqual(after_sync["2026-08-09"], defaults["2026-08-09"])

    def test_season_query_routes_to_runtime_and_returns_exact_manual_dates(self) -> None:
        self.assertEqual(self._route("将2026-08-07和2026-08-09设为旺季")["status"], "ok")
        query = parse_calendar_season_tag_query("2026年哪些天是旺季")
        self.assertEqual(query["season_tag"], "旺季")

        result = self._route("2026年哪些天是旺季", render=True)
        self.assertEqual(result["intent"], "business_calendar")
        self.assertEqual(result["runtime_command"], "calendar-season-tag-query")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["match_count"], 2)
        self.assertEqual(
            [item["date"] for item in result["season_tag_matches"]],
            ["2026-08-07", "2026-08-09"],
        )
        self.assertIn("2026-08-07", result["send_payload"]["text"])
        self.assertIn("2026-08-09", result["send_payload"]["text"])

    def test_calendar_sync_preserves_manual_chinese_season_tags(self) -> None:
        first = self._route("将2026-08-01至2026-08-03设为淡季")
        self.assertEqual(first["status"], "ok")

        sync_result = calendar_module.sync_calendar_year(self.db_path, 2026)
        self.assertEqual(sync_result["manual_season_tags_preserved"], 3)
        with connect(self.db_path) as conn:
            tags = conn.execute(
                "SELECT DISTINCT season_tag FROM calendar_days WHERE date BETWEEN '2026-08-01' AND '2026-08-03'"
            ).fetchall()
        self.assertEqual([row["season_tag"] for row in tags], ["淡季"])

    def test_named_role_target_does_not_cross_current_chat(self) -> None:
        group_a = safe_route_feishu_command(
            "将李四分配角色前台",
            db_path=self.db_path,
            chat_id="oc_group_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.auth_config),
            production_feishu=True,
        )
        self.assertEqual(group_a["status"], "blocked")
        self.assertEqual(group_a["reason"], "role_membership_target_not_found")

        group_b = safe_route_feishu_command(
            "将李四分配角色前台",
            db_path=self.db_path,
            chat_id="oc_group_b",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.auth_config),
            production_feishu=True,
        )
        self.assertEqual(group_b["status"], "pending_confirmation")
        self.assertEqual(group_b["intent"], "chat_role_named_request")

    def test_current_group_member_info_can_create_candidate_without_bot_scope(self) -> None:
        result = safe_route_feishu_command(
            "将王五分配角色前台",
            db_path=self.db_path,
            chat_id="oc_group_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.auth_config),
            production_feishu=True,
            member_info=[
                {"name": "王五", "display_name": "王五", "open_id": "ou_wangwu"}
            ],
        )
        self.assertEqual(result["status"], "pending_confirmation")
        self.assertEqual(result["intent"], "chat_role_named_request")


if __name__ == "__main__":
    unittest.main()
