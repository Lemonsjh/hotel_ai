from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from runtime.cli import main as cli_main
from runtime.control_plane import (
    approve_configuration_request,
    build_tenant_management_read_model,
    create_configuration_request,
    resolve_price_guard_policy,
)
from runtime.storage import connect, init_schema


def _run_cli(arguments: list[str]) -> dict:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli_main(arguments)
    if exit_code not in (None, 0):
        raise AssertionError(f"cli exited {exit_code}: {output.getvalue()}")
    import json

    return json.loads(output.getvalue())


class TestPriceGuardResolverConsumers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "controls.sqlite")
        self.owner = {"principal_id": "owner-1", "role": "owner", "hotel_ids": ["hotel-a"], "global_admin": False}
        self.second_owner = {"principal_id": "owner-2", "role": "owner", "hotel_ids": ["hotel-a"], "global_admin": False}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _activate_policy(self) -> None:
        request = create_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            payload={
                "room_type_id": "KING",
                "floor_price": 150,
                "ceiling_price": 250,
                "max_increase_pct": 0.12,
                "max_decrease_pct": 0.15,
                "min_increase_pct": 0.05,
                "min_decrease_pct": 0.05,
            },
            nonce="guard-nonce",
            expires_at="2099-01-01T00:00:00",
            now="2026-06-24T10:00:00",
        )
        approved = approve_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            nonce="guard-nonce",
            approver=self.second_owner,
            now="2026-06-24T10:01:00",
        )
        self.assertEqual(approved["status"], "approved")

    def test_management_guard_summary_comes_from_resolver_with_directional_limits(self) -> None:
        self._activate_policy()

        result = build_tenant_management_read_model(
            self.db_path,
            hotel_id="hotel-a",
            role_map={"hotel_memberships": []},
            at_time="2026-06-24T10:02:00",
        )

        guard = result["price_guard_statuses"][0]
        self.assertEqual(guard["source"], "active_price_guard_policy")
        self.assertEqual(guard["room_type_id"], "KING")
        self.assertEqual(guard["version"], 1)
        self.assertEqual(guard["floor_price"], 150.0)
        self.assertEqual(guard["ceiling_price"], 250.0)
        self.assertEqual(guard["max_increase_pct"], 0.12)
        self.assertEqual(guard["max_decrease_pct"], 0.15)
        self.assertEqual(guard["min_increase_pct"], 0.05)
        self.assertEqual(guard["min_decrease_pct"], 0.05)

    def test_s6_default_policy_uses_directional_limits_without_room_price_bounds(self) -> None:
        _run_cli(["--db", self.db_path, "init-db"])

        result = _run_cli(
            [
                "--db",
                self.db_path,
                "execute-price",
                "--hotel-id",
                "hotel-a",
                "--room-type-id",
                "UNKNOWN",
                "--channel",
                "Mtop",
                "--normal-price",
                "159",
                "--begin-date",
                "2026-06-24",
                "--end-date",
                "2026-06-24",
                "--user-role",
                "operator",
                "--dry-run",
                "--no-log",
            ]
        )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["price_guard_policy"]["source"], "default_policy")
        self.assertFalse(result["price_guard_policy"]["execution_allowed"])
        self.assertEqual(result["blocked_reason"], "dry_run_preview_only")
        self.assertIsNone(result["guard"]["floor_price"])
        self.assertIsNone(result["guard"]["ceiling_price"])

    def test_management_read_model_exposes_default_policy_as_preview_only(self) -> None:
        result = build_tenant_management_read_model(
            self.db_path,
            hotel_id="hotel-a",
            role_map={"hotel_memberships": []},
            at_time="2026-06-24T10:02:00",
        )

        guard = result["price_guard_statuses"][0]
        self.assertEqual(result["active_price_guard_count"], 0)
        self.assertEqual(guard["source"], "default_policy")
        self.assertFalse(guard["execution_allowed"])
        self.assertIsNone(guard["floor_price"])
        self.assertIsNone(guard["ceiling_price"])

    def test_price_guard_resolver_prefers_product_then_channel_then_room_policy(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            init_schema(conn)
            rows = [
                ("generic", None, None, 150, 1),
                ("meituan", "meituan", None, 160, 2),
                ("product", "meituan", "mt-prod-1", 170, 3),
            ]
            for label, channel, product_id, floor, version in rows:
                conn.execute(
                    """
                    INSERT INTO price_guard_policies (
                      policy_id, hotel_id, room_type_id, channel_source, ota_product_id,
                      floor_price, ceiling_price, max_single_change_pct, max_increase_pct,
                      max_decrease_pct, min_increase_pct, min_decrease_pct, effective_from,
                      effective_to, version, status, source_request_id, created_at
                    )
                    VALUES (?, 'hotel-a', 'KING', ?, ?, ?, 260, 0.2, 0.2, 0.2, 0.05, 0.05,
                            '2026-06-24T00:00:00', NULL, ?, 'active', ?, '2026-06-24T00:00:00')
                    """,
                    (f"pgp-{label}", channel, product_id, floor, version, f"req-{label}"),
                )
            conn.commit()

        generic = resolve_price_guard_policy(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            at_time="2026-06-24T10:00:00",
        )
        channel = resolve_price_guard_policy(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            at_time="2026-06-24T10:00:00",
            channel_source="meituan",
        )
        product = resolve_price_guard_policy(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            at_time="2026-06-24T10:00:00",
            channel_source="meituan",
            ota_product_id="mt-prod-1",
        )

        self.assertEqual(generic["policy_id"], "pgp-generic")
        self.assertEqual(channel["policy_id"], "pgp-meituan")
        self.assertEqual(product["policy_id"], "pgp-product")


if __name__ == "__main__":
    unittest.main()
