from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.control_plane import (
    active_price_guard_policy,
    approve_configuration_request,
    approve_configuration_card_callback,
    create_configuration_card,
    create_configuration_request,
    create_role_membership_request_from_role_map,
    list_role_map_apply_queue,
    resolve_price_guard_policy,
    verify_audit_chain,
)
from runtime.storage import connect, init_schema


class TestConfigurationCardAudit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "control-plane.sqlite")
        self.owner = {"principal_id": "owner-1", "role": "owner", "hotel_ids": ["hotel-a"], "global_admin": False}
        self.second_owner = {"principal_id": "owner-2", "role": "owner", "hotel_ids": ["hotel-a"], "global_admin": False}
        self.admin = {"principal_id": "admin-1", "role": "admin", "hotel_ids": [], "global_admin": True}
        self.second_admin = {"principal_id": "admin-2", "role": "admin", "hotel_ids": [], "global_admin": True}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _directional_guard_payload() -> dict[str, object]:
        return {
            "room_type_id": "KING",
            "floor_price": 150,
            "ceiling_price": 250,
            "max_increase_pct": 0.1,
            "max_decrease_pct": 0.12,
            "min_increase_pct": 0.01,
            "min_decrease_pct": 0.01,
        }

    def test_price_guard_requires_distinct_in_scope_approver_and_creates_policy(self) -> None:
        request = create_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            payload={
                **self._directional_guard_payload(),
                "effective_from": "2026-06-23T00:00:00",
                "effective_to": "2026-06-24T00:00:00",
            },
            nonce="nonce-price-1",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:00:00",
        )
        self.assertEqual(request["status"], "pending")
        self.assertIsNone(active_price_guard_policy(self.db_path, "hotel-a", "KING", "2026-06-23T10:00:00"))

        self_approval = approve_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            nonce="nonce-price-1",
            approver=self.owner,
            now="2026-06-23T10:01:00",
        )
        self.assertEqual(self_approval["status"], "blocked")
        self.assertEqual(self_approval["reason"], "self_approval_not_allowed")

        approved = approve_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            nonce="nonce-price-1",
            approver=self.second_owner,
            now="2026-06-23T10:02:00",
        )
        self.assertEqual(approved["status"], "approved")
        policy = active_price_guard_policy(self.db_path, "hotel-a", "KING", "2026-06-23T10:03:00")
        self.assertEqual(policy["version"], 1)
        self.assertEqual(policy["floor_price"], 150.0)
        self.assertTrue(verify_audit_chain(self.db_path, "hotel-a")["valid"])

    def test_expired_or_replayed_nonce_never_changes_request_state(self) -> None:
        request = create_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            payload=self._directional_guard_payload(),
            nonce="nonce-expired",
            expires_at="2026-06-23T10:01:00",
            now="2026-06-23T10:00:00",
        )

        expired = approve_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            nonce="nonce-expired",
            approver=self.second_owner,
            now="2026-06-23T10:02:00",
        )
        self.assertEqual(expired["status"], "blocked")
        self.assertEqual(expired["reason"], "card_nonce_expired")
        replay = approve_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            nonce="nonce-expired",
            approver=self.second_owner,
            now="2026-06-23T10:02:30",
        )
        self.assertEqual(replay["status"], "blocked")
        self.assertEqual(replay["reason"], "card_nonce_expired")
        self.assertIsNone(active_price_guard_policy(self.db_path, "hotel-a", "KING", "2026-06-23T10:03:00"))

    def test_new_guard_requires_all_directional_limits_and_legacy_policy_reads(self) -> None:
        with self.assertRaisesRegex(ValueError, "price_guard_payload_missing_required_fields"):
            create_configuration_request(
                self.db_path,
                request_kind="price_guard_policy",
                hotel_id="hotel-a",
                requester=self.owner,
                payload={"room_type_id": "KING", "floor_price": 150, "ceiling_price": 250, "max_single_change_pct": 0.1},
                nonce="legacy-write",
                expires_at="2026-06-23T10:10:00",
                now="2026-06-23T10:00:00",
            )

        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                    """
                    INSERT INTO price_guard_policies
                      (policy_id, hotel_id, room_type_id, floor_price, ceiling_price, max_single_change_pct, effective_from, effective_to, version, status, source_request_id, created_at)
                    VALUES ('legacy-guard', 'hotel-a', 'LEGACY', 150, 250, 0.12, '2026-06-23T00:00:00', NULL, 1, 'active', 'legacy-source', '2026-06-23T00:00:00')
                    """
                )
        legacy = active_price_guard_policy(self.db_path, "hotel-a", "LEGACY", "2026-06-23T10:00:00")
        self.assertEqual(legacy["policy_schema"], "legacy_single_cap")
        self.assertEqual(legacy["max_increase_pct"], 0.12)
        self.assertEqual(legacy["max_decrease_pct"], 0.12)
        self.assertEqual(legacy["min_increase_pct"], 0.0)
        self.assertEqual(legacy["min_decrease_pct"], 0.0)

    def test_missing_active_policy_resolves_a_labeled_controlled_default(self) -> None:
        resolved = resolve_price_guard_policy(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            at_time="2026-06-23T10:00:00",
        )

        self.assertEqual(resolved["source"], "default_policy")
        self.assertEqual(resolved["policy_state"], "default_policy")
        self.assertIsNone(resolved["policy_id"])
        self.assertGreater(resolved["max_increase_pct"], 0)

    def test_role_membership_approval_only_queues_private_apply(self) -> None:
        request = create_configuration_request(
            self.db_path,
            request_kind="role_membership_change",
            hotel_id="hotel-a",
            requester=self.admin,
            payload={"principal_id": "operator-1", "role": "operator", "operation": "grant"},
            nonce="nonce-role-1",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:00:00",
        )

        approved = approve_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            nonce="nonce-role-1",
            approver=self.second_admin,
            now="2026-06-23T10:01:00",
        )
        self.assertEqual(approved["status"], "approved")
        queue = list_role_map_apply_queue(self.db_path)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["status"], "pending")
        self.assertNotIn("open_id", str(queue[0]))
        self.assertTrue(verify_audit_chain(self.db_path, "hotel-a")["valid"])

    def test_owner_can_self_confirm_other_operator_in_own_hotel_only(self) -> None:
        role_map = {
            "version": 3,
            "direct_message_policy": "role_mapped_users_only",
            "global_admin_principal_ids": ["admin-1"],
            "users": [
                {"principal_id": "admin-1", "open_id": "ou_admin"},
                {"principal_id": "owner-1", "open_id": "ou_owner"},
                {"principal_id": "operator-1", "open_id": "ou_operator"},
            ],
            "hotel_memberships": [
                {"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"},
            ],
            "group_chat_bindings": [],
        }
        request = create_role_membership_request_from_role_map(
            self.db_path,
            hotel_id="hotel-a",
            requester=self.owner,
            role_map=role_map,
            payload={"principal_id": "operator-1", "role": "operator", "operation": "grant"},
            nonce="nonce-owner-role-1",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:00:00",
        )
        self.assertEqual(request["status"], "pending")

        approved = approve_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            nonce="nonce-owner-role-1",
            approver=self.owner,
            now="2026-06-23T10:01:00",
        )
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(len(list_role_map_apply_queue(self.db_path)), 1)

        self_target = create_role_membership_request_from_role_map(
            self.db_path,
            hotel_id="hotel-a",
            requester=self.owner,
            role_map=role_map,
            payload={"principal_id": "owner-1", "role": "frontdesk", "operation": "grant"},
            nonce="nonce-owner-self",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:02:00",
        )
        self.assertEqual(self_target["status"], "blocked")
        self.assertEqual(self_target["reason"], "owner_cannot_modify_self_membership")

        cross_hotel = create_role_membership_request_from_role_map(
            self.db_path,
            hotel_id="hotel-b",
            requester=self.owner,
            role_map=role_map,
            payload={"principal_id": "operator-1", "role": "operator", "operation": "grant"},
            nonce="nonce-owner-cross",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:02:00",
        )
        self.assertEqual(cross_hotel["status"], "blocked")

        unknown_target = create_role_membership_request_from_role_map(
            self.db_path,
            hotel_id="hotel-a",
            requester=self.owner,
            role_map=role_map,
            payload={"principal_id": "unknown", "role": "operator", "operation": "grant"},
            nonce="nonce-owner-unknown",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:02:00",
        )
        self.assertEqual(unknown_target["status"], "blocked")
        self.assertEqual(unknown_target["reason"], "role_membership_target_not_found")

    def test_owner_role_request_requires_private_role_map_validation(self) -> None:
        result = create_configuration_request(
            self.db_path,
            request_kind="role_membership_change",
            hotel_id="hotel-a",
            requester=self.owner,
            payload={"principal_id": "operator-1", "role": "operator", "operation": "grant"},
            nonce="nonce-owner-no-map",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:00:00",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "role_membership_role_map_required")

    def test_card_callback_requires_matching_payload_hash_and_distinct_approver(self) -> None:
        card = create_configuration_card(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            payload=self._directional_guard_payload(),
            nonce="card-nonce",
            expires_at="2026-06-23T10:10:00",
            now="2026-06-23T10:00:00",
        )

        self.assertEqual(card["status"], "pending")
        self.assertEqual(set(card["card"].keys()), {"schema_version", "action", "request_id", "nonce", "payload_hash", "expires_at", "summary"})
        self.assertNotIn("floor_price", str(card["card"]))

        tampered = approve_configuration_card_callback(
            self.db_path,
            callback={**card["card"], "payload_hash": "tampered"},
            approver=self.second_owner,
            now="2026-06-23T10:01:00",
        )
        self.assertEqual(tampered["status"], "blocked")
        self.assertEqual(tampered["reason"], "card_payload_hash_mismatch")

        approved = approve_configuration_card_callback(
            self.db_path,
            callback=card["card"],
            approver=self.second_owner,
            now="2026-06-23T10:02:00",
        )
        self.assertEqual(approved["status"], "approved")


if __name__ == "__main__":
    unittest.main()
