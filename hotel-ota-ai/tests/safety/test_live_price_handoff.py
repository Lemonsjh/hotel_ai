from __future__ import annotations

import unittest

from runtime.safety.approvals import approval_gate
from runtime.safety.guards import price_guard
from runtime.safety.payload_hash import price_execution_payload, price_execution_payload_hash


class TestLivePriceHandoff(unittest.TestCase):
    def test_live_guard_rejects_missing_old_price(self) -> None:
        result = price_guard(
            old_price=None,
            new_price=200,
            floor_price=150,
            ceiling_price=240,
            require_old_price=True,
        )

        self.assertFalse(result["passed"])
        self.assertIn("old_price_required_for_live", result["violations"])

    def test_price_payload_hash_is_bound_to_hotel_and_guard_version(self) -> None:
        first = price_execution_payload(
            hotel_id="hotel-a",
            room_type_id="KING",
            channel="Mtop",
            normal_price=200,
            begin_date="2026-06-23",
            end_date="2026-06-23",
            guard_version="room-price-guard-v1",
        )
        second = {**first, "hotel_id": "hotel-b"}

        self.assertNotEqual(price_execution_payload_hash(first), price_execution_payload_hash(second))

    def test_price_payload_hash_is_bound_to_old_price_and_policy_identity(self) -> None:
        first = price_execution_payload(
            hotel_id="hotel-a",
            room_type_id="KING",
            channel="Mtop",
            normal_price=200,
            old_price=190,
            price_guard_policy_id="policy-v1",
            guard_version=1,
            begin_date="2026-06-23",
            end_date="2026-06-23",
        )
        changed_old_price = {**first, "old_price": 189}
        changed_policy = {**first, "price_guard_policy_id": "policy-v2"}

        self.assertNotEqual(price_execution_payload_hash(first), price_execution_payload_hash(changed_old_price))
        self.assertNotEqual(price_execution_payload_hash(first), price_execution_payload_hash(changed_policy))

    def test_price_payload_hash_is_bound_to_ota_product(self) -> None:
        first = price_execution_payload(
            hotel_id="hotel-a",
            room_type_id="KING",
            channel="meituan",
            ota_product_id="mt-product-1",
            normal_price=200,
            old_price=190,
            price_guard_policy_id="policy-v1",
            guard_version=1,
            begin_date="2026-06-23",
            end_date="2026-06-23",
        )

        self.assertNotEqual(price_execution_payload_hash(first), price_execution_payload_hash({**first, "ota_product_id": "mt-product-2"}))

    def test_directional_price_guard_rejects_small_or_excessive_directional_change(self) -> None:
        too_small = price_guard(
            old_price=200,
            new_price=202,
            floor_price=150,
            ceiling_price=240,
            max_increase_pct=0.1,
            max_decrease_pct=0.12,
            min_increase_pct=0.02,
            min_decrease_pct=0.03,
        )
        too_large_decrease = price_guard(
            old_price=200,
            new_price=170,
            floor_price=150,
            ceiling_price=240,
            max_increase_pct=0.1,
            max_decrease_pct=0.12,
            min_increase_pct=0.02,
            min_decrease_pct=0.03,
        )
        no_change = price_guard(
            old_price=200,
            new_price=200,
            floor_price=150,
            ceiling_price=240,
            max_increase_pct=0.1,
            max_decrease_pct=0.12,
            min_increase_pct=0.02,
            min_decrease_pct=0.03,
        )
        self.assertIn("increase_below_minimum", too_small["violations"])
        self.assertIn("decrease_max_exceeded", too_large_decrease["violations"])
        self.assertEqual(no_change["violations"], ["no_effective_change"])

    def test_price_payload_hash_is_bound_to_directional_limits(self) -> None:
        first = price_execution_payload(
            hotel_id="hotel-a",
            room_type_id="KING",
            channel="Mtop",
            normal_price=200,
            old_price=190,
            price_guard_policy_id="policy-v1",
            guard_version=1,
            max_increase_pct=0.1,
            max_decrease_pct=0.12,
            min_increase_pct=0.01,
            min_decrease_pct=0.01,
            begin_date="2026-06-23",
            end_date="2026-06-23",
        )
        self.assertNotEqual(price_execution_payload_hash(first), price_execution_payload_hash({**first, "max_decrease_pct": 0.11}))

    def test_approval_gate_allows_owner_self_approval(self) -> None:
        # 用户设计:admin/owner 可自审批(operator 才必须别人批)。
        result = approval_gate(
            approved_by="ou_requester",
            requester_id="ou_requester",
            dry_run=False,
            action_type="price_update",
            approval_id="approval-1",
            approver_role="owner",
        )

        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "approved")

    def test_approval_gate_allows_admin_self_execution(self) -> None:
        # admin/owner 可自审批自执行。
        result = approval_gate(
            approved_by="ou_admin",
            requester_id="ou_admin",
            executor_id="ou_admin",
            dry_run=False,
            action_type="price_update",
            approval_id="approval-1",
            approver_role="admin",
        )

        self.assertTrue(result["allowed"])

    def test_approval_gate_still_requires_admin_or_owner(self) -> None:
        # operator 无论是否自审批,一律不能审批。
        result = approval_gate(
            approved_by="ou_op",
            requester_id="ou_op",
            dry_run=False,
            action_type="price_update",
            approval_id="approval-1",
            approver_role="operator",
        )

        self.assertFalse(result["allowed"])
        self.assertIn("admin_or_owner", result["reason"])


if __name__ == "__main__":
    unittest.main()
