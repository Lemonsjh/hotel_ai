from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.control_plane import (
    approve_configuration_request,
    approve_formal_price_approval,
    create_configuration_request,
    create_formal_price_approval,
)


class TestTenantPriceApproval(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "price-approval.sqlite")
        self.owner = {"principal_id": "owner-1", "role": "owner", "hotel_ids": ["hotel-a"], "global_admin": False}
        self.second_owner = {"principal_id": "owner-2", "role": "owner", "hotel_ids": ["hotel-a"], "global_admin": False}
        guard = create_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            payload={
                "room_type_id": "KING",
                "floor_price": 150,
                "ceiling_price": 250,
                "max_increase_pct": 0.1,
                "max_decrease_pct": 0.12,
                "min_increase_pct": 0.01,
                "min_decrease_pct": 0.01,
            },
            nonce="guard-nonce",
            expires_at="2026-06-23T12:00:00",
            now="2026-06-23T10:00:00",
        )
        approve_configuration_request(
            self.db_path,
            request_id=guard["request_id"],
            nonce="guard-nonce",
            approver=self.second_owner,
            now="2026-06-23T10:01:00",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_formal_price_approval_binds_current_policy_and_never_executes_live(self) -> None:
        request = create_formal_price_approval(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            old_price=200,
            proposed_price=210,
            business_payload={
                "freshness_status": "fresh",
                "business_status": "current",
                "data_source_type": "real_data",
                "data_business_date": "2026-06-23",
                "data_snapshot_time": "2026-06-23T10:02:00",
                "dry_run_summary": "price candidate",
                "channel_source": "meituan",
                "ota_product_id": "mt-product-1",
                "begin_date": "2026-06-23",
                "end_date": "2026-06-23",
            },
            requester=self.owner,
            now="2026-06-23T10:03:00",
        )

        self.assertEqual(request["status"], "pending")
        self.assertEqual(request["price_guard_policy_version"], 1)
        self.assertTrue(request["execution_payload_hash"])
        self.assertIn("price_guard_policy_id", request["execution_payload"])
        self.assertEqual(request["execution_payload"]["old_price"], 200.0)
        self.assertEqual(request["execution_payload"]["ota_product_id"], "mt-product-1")
        self.assertEqual(request["execution_payload"]["max_increase_pct"], 0.1)
        self.assertEqual(request["live_execution_count"], 0)

        approved = approve_formal_price_approval(
            self.db_path,
            approval_id=request["approval_id"],
            approver=self.second_owner,
            now="2026-06-23T10:04:00",
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["live_execution_count"], 0)

    def test_formal_price_approval_rejects_stale_data_but_uses_default_directional_limits(self) -> None:
        stale = create_formal_price_approval(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            old_price=200,
            proposed_price=210,
            business_payload={"freshness_status": "demo_data", "business_status": "demo_or_historical"},
            requester=self.owner,
            now="2026-06-23T10:03:00",
        )
        missing = create_formal_price_approval(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="TWIN",
            old_price=200,
            proposed_price=210,
            business_payload={
                "freshness_status": "fresh",
                "business_status": "current",
                "data_source_type": "real_data",
                "begin_date": "2026-06-23",
                "end_date": "2026-06-23",
            },
            requester=self.owner,
            now="2026-06-23T10:03:00",
        )

        self.assertEqual(stale["status"], "blocked")
        self.assertEqual(stale["reason"], "formal_price_approval_requires_fresh_current_data")
        self.assertEqual(missing["status"], "pending")
        self.assertIsNone(missing["execution_payload"]["floor_price"])
        self.assertIsNone(missing["execution_payload"]["ceiling_price"])

    def test_formal_price_approval_requires_explicit_effective_date_range(self) -> None:
        result = create_formal_price_approval(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            old_price=200,
            proposed_price=210,
            business_payload={"freshness_status": "fresh", "business_status": "current", "data_source_type": "real_data"},
            requester=self.owner,
            now="2026-06-23T10:03:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "formal_price_approval_effective_date_required")

    def test_formal_price_approval_rejects_no_effective_change(self) -> None:
        result = create_formal_price_approval(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            old_price=200,
            proposed_price=200,
            business_payload={
                "freshness_status": "fresh",
                "business_status": "current",
                "data_source_type": "real_data",
                "begin_date": "2026-06-23",
                "end_date": "2026-06-23",
            },
            requester=self.owner,
            now="2026-06-23T10:03:00",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["guard"]["violations"], ["no_effective_change"])


if __name__ == "__main__":
    unittest.main()
