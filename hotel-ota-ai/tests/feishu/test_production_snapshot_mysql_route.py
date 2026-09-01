from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


class TestProductionSnapshotMysqlRoute(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "auth.sqlite")
        self.auth_config = root / "role-map.json"
        self.auth_config.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": ["owner-1"],
                    "users": [{"principal_id": "owner-1", "open_id": "ou_owner"}],
                    "hotel_memberships": [{"principal_id": "owner-1", "hotel_id": "xingfeng", "role": "owner"}],
                    "group_chat_bindings": [{"chat_id": "oc_xingfeng", "hotel_id": "xingfeng"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_production_snapshot_uses_mysql_when_db_source_enabled(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operating_snapshot":
                return {
            "status": "ok",
            "data_source_type": "mysql_db",
            "source_mode": "mysql_runtime",
            "payload": {
                "source_status": "ok",
                "data_business_date": "2026-06-26",
                "data_snapshot_time": "2026-06-26 23:00:00",
                "freshness_status": "stale",
                "s2_contract": "pms_room_type_forecast_v1",
                "total_rooms": 31,
                "sold_rooms": 23,
                "committed_sold_rooms": 23,
                "physical_occupied_rooms": 18,
                "physical_occupancy_rate": 0.5806,
                "sold_room_nights_today": 23,
                "sold_orders_today": 18,
                "occupancy_rate": 0.7419,
                "adr": 188,
                "revpar": 139.6,
            },
        }
            if template == "reservation_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "new_arrival_rooms": 2,
                        "jd01_checked_in_departure_after_as_of": 0,
                        "jd01_reserved_arrival_today": 2,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-06-26",
                        "data_snapshot_time": "2026-06-26 18:00:00",
                    },
                }
            if template == "stayover_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "stayover_rooms": 21,
                        "jd04_checkout_after_as_of": 21,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-06-26",
                        "data_snapshot_time": "2026-06-26 18:00:00",
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_unexpected"}

        with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=fake_template
        ) as db_query:
            result = safe_route_feishu_command(
                "1",
                db_path=self.db_path,
                chat_id="oc_xingfeng",
                chat_type="group",
                open_id="ou_owner",
                auth_config=str(self.auth_config),
                production_feishu=True,
                render=True,
                as_of_time="2026-06-26 18:00:00",
            )

        self.assertEqual(
            db_query.call_args_list[0],
            mock.call("operating_snapshot", "xingfeng", date="2026-06-26", as_of_time="2026-06-26 18:00:00"),
        )
        self.assertEqual(result["intent"], "run_s02")
        self.assertEqual(result["hotel_id"], "xingfeng")
        self.assertEqual(result["data_source_type"], "mysql_db")
        self.assertEqual(result["core_metrics"]["sold_room_nights_today"], 23)
        self.assertEqual(result["formula_version"], "pms_room_type_forecast_committed_sales_v1")
        self.assertIsNone(result["actual_numerator_rooms"])
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertEqual(result["occupancy_rate"], 0.7419)
        self.assertIsNone(result["actual_occupancy_rate"])
        self.assertEqual(result["physical_occupied_rooms"], 18)
        self.assertEqual(db_query.call_count, 8)
        self.assertIn("一、经营总览", result["send_payload"]["text"])
        self.assertIn("六、推广活动状态", result["send_payload"]["text"])
        self.assertNotIn(result.get("data_source_type"), {"demo_data", "sample_data", "synthetic_today_demo"})

    def test_production_snapshot_uses_formula_rate_not_kf11_occupied_rate(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "data_source_type": "mysql_db",
                    "source_mode": "mysql_runtime",
                    "payload": {
                        "source_status": "ok",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 16:25:00",
                        "freshness_status": "fresh",
                        "total_rooms": 31,
                        "sold_rooms": 16,
                        "occupancy_rate": 0.5161,
                        "adr": 188,
                        "revpar": 97.03,
                    },
                }
            if template == "room_status_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "row_count": 31,
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 16:25:00",
                        "freshness_status": "fresh",
                        "rows": [
                            *[{"room_no": f"2{i:02d}", "room_status": "住脏"} for i in range(1, 17)],
                            *[{"room_no": f"3{i:02d}", "room_status": "空净"} for i in range(1, 12)],
                            *[{"room_no": f"4{i:02d}", "room_status": "空脏"} for i in range(1, 5)],
                        ],
                    },
                }
            if template == "reservation_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 16:25:00",
                        "realtime_rows": [
                            {"room_no": "501", "booking_status": "预订", "arrival_time": "2026-07-03 20:00:00"},
                            {"room_no": "502", "booking_status": "预订", "arrival_time": "2026-07-03 21:00:00"},
                        ],
                    },
                }
            if template == "stayover_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 16:25:00",
                        "realtime_rows": [{"room_no": "503", "checkout_time": "2026-07-03 19:00:00"}],
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_unexpected"}

        with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=fake_template
        ):
            result = safe_route_feishu_command(
                "实时出租率",
                db_path=self.db_path,
                chat_id="oc_xingfeng",
                chat_type="group",
                open_id="ou_owner",
                auth_config=str(self.auth_config),
                production_feishu=True,
                render=True,
                as_of_time="2026-07-03 16:25:00",
            )

        self.assertEqual(result["intent"], "run_s02")
        self.assertEqual(result["occupancy_rate"], 0.0968)
        self.assertEqual(result["actual_occupancy_rate"], 0.0968)
        self.assertEqual(result["actual_numerator_rooms"], 3)
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertEqual(result["kf11_occupied_rooms"], 16)
        self.assertEqual(result["kf11_formula_gap_rooms"], 13)
        rendered_text = result["send_payload"]["text"]
        self.assertIn("0.0968", rendered_text)
        self.assertNotIn("0.5161", rendered_text)
        self.assertIn("是否真实经营数据：是", rendered_text)
        self.assertNotIn("演示结果", rendered_text)
        self.assertIn("read_only_runtime_formal_live_blocked", rendered_text)
        self.assertNotIn("demo_preview_allowed_formal_live_blocked", rendered_text)

    def test_production_snapshot_blocks_when_formula_components_are_missing(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "data_source_type": "mysql_db",
                    "source_mode": "mysql_runtime",
                    "payload": {
                        "source_status": "ok",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 16:25:00",
                        "freshness_status": "fresh",
                        "total_rooms": 31,
                        "sold_rooms": 17,
                        "occupancy_rate": 0.5484,
                        "adr": 188,
                        "revpar": 103.1,
                    },
                }
            if template == "room_status_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "row_count": 31,
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 16:25:00",
                        "freshness_status": "fresh",
                        "rows": [
                            *[{"room_no": f"2{i:02d}", "room_status": "住净"} for i in range(1, 9)],
                            *[{"room_no": f"3{i:02d}", "room_status": "住脏"} for i in range(1, 10)],
                            *[{"room_no": f"4{i:02d}", "room_status": "空净"} for i in range(1, 15)],
                        ],
                    },
                }
            if template == "reservation_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "new_arrival_rooms": 0,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 16:25:00",
                    },
                }
            if template == "stayover_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "stayover_rooms": 1,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 16:25:00",
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_unexpected"}

        with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=fake_template
        ):
            result = safe_route_feishu_command(
                "实时出租率",
                db_path=self.db_path,
                chat_id="oc_xingfeng",
                chat_type="group",
                open_id="ou_owner",
                auth_config=str(self.auth_config),
                production_feishu=True,
                render=True,
                as_of_time="2026-07-04 16:25:00",
            )

        self.assertEqual(result["intent"], "run_s02")
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "realtime_occupancy_formula_evidence_missing")
        self.assertIsNone(result.get("occupancy_rate"))
        self.assertIsNone(result.get("actual_occupancy_rate"))
        rendered_text = result["send_payload"]["text"]
        self.assertNotIn("0.5484", rendered_text)
        self.assertNotIn("54.84%", rendered_text)
        self.assertIn("realtime_occupancy_formula_evidence_missing", rendered_text)

    def test_realtime_occupancy_never_renders_stale_jy01_rate_when_formula_is_available(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "data_source_type": "mysql_db",
                    "source_mode": "mysql_runtime",
                    "payload": {
                        "source_status": "ok",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 20:14:44",
                        "freshness_status": "stale",
                        "total_rooms": 31,
                        "sold_rooms": 17,
                        "occupancy_rate": 0.5484,
                        "adr": 160.86,
                        "revpar": 155.67,
                    },
                }
            if template == "room_status_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "row_count": 31,
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 20:14:44",
                        "freshness_status": "stale",
                        "rows": [
                            *[{"room_no": f"2{i:02d}", "room_status": "住脏"} for i in range(1, 22)],
                            *[{"room_no": f"3{i:02d}", "room_status": "空脏"} for i in range(1, 10)],
                            {"room_no": "401", "room_status": "空净"},
                        ],
                    },
                }
            if template == "reservation_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "jd01_checked_in_departure_after_as_of": 12,
                        "jd01_reserved_raw_arrival_today": 11,
                        "jd01_reserved_arrival_today": 4,
                        "jd01_cancelled_arrival_today": 12,
                        "freshness_status": "stale",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 16:26:24",
                    },
                }
            if template == "stayover_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "jd04_checkout_after_as_of": 6,
                        "freshness_status": "stale",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 11:36:09",
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_unexpected"}

        with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=fake_template
        ):
            result = safe_route_feishu_command(
                "实时出租率",
                db_path=self.db_path,
                chat_id="oc_xingfeng",
                chat_type="group",
                open_id="ou_owner",
                auth_config=str(self.auth_config),
                production_feishu=True,
                render=True,
                as_of_time="2026-07-04 20:14:44",
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["actual_numerator_rooms"], 22)
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertEqual(result["actual_occupancy_rate"], 0.7097)
        self.assertEqual(result["occupancy_rate"], 0.7097)
        self.assertEqual(
            result["occupancy_reservation_adjustment_components"],
            {"jd01_reserved_raw_arrival_today": 11, "jd01_cancelled_arrival_today": 12},
        )
        rendered_text = result["send_payload"]["text"]
        self.assertIn("0.7097", rendered_text)
        self.assertNotIn("0.5484", rendered_text)
        self.assertNotIn("54.84%", rendered_text)

    def test_realtime_occupancy_today_data_gap_does_not_fallback_to_yesterday_snapshot(self) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            calls.append((template, dict(kwargs)))
            query_date = kwargs.get("date")
            if template == "operating_snapshot" and query_date is None:
                return {
                    "status": "ok",
                    "data_source_type": "mysql_db",
                    "source_mode": "mysql_runtime",
                    "payload": {
                        "source_status": "ok",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 23:59:00",
                        "freshness_status": "stale",
                        "total_rooms": 31,
                        "sold_rooms": 17,
                        "occupancy_rate": 0.5484,
                    },
                }
            if query_date == "2026-07-05":
                return {"status": "data_gap", "reason": f"{template}_missing_for_target_date", "payload": {}}
            return {"status": "data_gap", "reason": f"{template}_unexpected_date_{query_date}", "payload": {}}

        with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=fake_template
        ):
            result = safe_route_feishu_command(
                "实时出租率",
                db_path=self.db_path,
                chat_id="oc_xingfeng",
                chat_type="group",
                open_id="ou_owner",
                auth_config=str(self.auth_config),
                production_feishu=True,
                render=True,
                as_of_time="2026-07-05 15:25:00",
            )

        self.assertEqual(result["intent"], "run_s02")
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["data_business_date"], "2026-07-05")
        self.assertIsNone(result.get("actual_occupancy_rate"))
        self.assertNotEqual(result.get("occupancy_rate"), 0.5484)
        self.assertNotIn(("operating_snapshot", {}), calls)
        self.assertIn(("operating_snapshot", {"date": "2026-07-05", "as_of_time": "2026-07-05 15:25:00"}), calls)
        rendered_text = result["send_payload"]["text"]
        self.assertNotIn("0.5484", rendered_text)
        self.assertNotIn("54.84%", rendered_text)


if __name__ == "__main__":
    unittest.main()
