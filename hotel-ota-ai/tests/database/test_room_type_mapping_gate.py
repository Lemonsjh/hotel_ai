from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path

from runtime.adapters.normalized_query import is_price_task_mapping_ready
from runtime.adapters.zhiting_price_task_outbox import _product_skip_reason, write_zhiting_price_tasks
from runtime.storage import connect, init_schema


class TestRoomTypeMappingGate(unittest.TestCase):
    def test_mapping_statuses_other_than_auto_are_blocked_for_s6(self) -> None:
        for status in ("CONFIRMED", "PENDING", "CONFLICT", "REJECTED", None):
            with self.subTest(status=status):
                ready = is_price_task_mapping_ready(
                    {
                        "mapping_status": status,
                        "mapping_active": True,
                        "room_type_id": "KING",
                        "source_product_id": "mt-prod-1",
                        "price_editable_flag": 1,
                        "is_hour_room": 0,
                        "source_platform": "meituan",
                    }
                )
                self.assertFalse(ready["ready_for_price_task"])
                self.assertEqual(ready["blocked_reason"], "mapping_status_not_auto")
                self.assertEqual(ready["mapping_resolution_status"], "mapping_pending")
                self.assertIn("price_task_blocked", ready["risk_flags"])

    def test_active_auto_mapping_is_ready_regardless_of_match_rule(self) -> None:
        for rule in ("MANUAL", "ROOM_ID", "PRODUCT_ID", "GOODS_ID", "ROOM_NAME", None, ""):
            with self.subTest(rule=rule):
                ready = is_price_task_mapping_ready(
                    {
                        "mapping_status": "AUTO",
                        "match_rule": rule,
                        "mapping_active": True,
                        "room_type_id": "py03",
                        "source_product_id": "2304257179",
                        "price_editable_flag": 1,
                        "is_hour_room": 0,
                        "source_platform": "meituan",
                    }
                )
                self.assertTrue(ready["ready_for_price_task"])
                self.assertEqual(ready["mapping_resolution_status"], "mapped")

    def test_auto_exact_match_does_not_block_on_price_editable_flag_null(self) -> None:
        ready = is_price_task_mapping_ready(
            {
                "mapping_status": "AUTO",
                "match_rule": "",
                "mapping_active": True,
                "room_type_id": "py03",
                "source_product_id": "2304257179",
                "price_editable_flag": None,
                "is_hour_room": 0,
                "source_platform": "meituan",
            }
        )
        self.assertTrue(ready["ready_for_price_task"])
        self.assertIsNone(ready["blocked_reason"])

    def test_hour_room_does_not_block_price_task_readiness(self) -> None:
        ready = is_price_task_mapping_ready(
            {
                "mapping_status": "AUTO",
                "mapping_active": True,
                "room_type_id": "HOUR",
                "source_product_id": "mt-hour-1",
                "price_editable_flag": None,
                "is_hour_room": 1,
                "source_platform": "meituan",
            }
        )
        self.assertTrue(ready["ready_for_price_task"])
        self.assertIsNone(ready["blocked_reason"])

    def test_name_inferred_auto_mapping_is_still_blocked(self) -> None:
        ready = is_price_task_mapping_ready(
            {
                "mapping_status": "AUTO",
                "mapping_resolution_status": "mapping_pending",
                "mapping_active": True,
                "room_type_id": "py03",
                "source_product_id": "2304257179",
                "source_platform": "meituan",
                "risk_flags": ["mapping_candidate_name_match", "inferred_by_name"],
            }
        )
        self.assertFalse(ready["ready_for_price_task"])
        self.assertEqual(ready["blocked_reason"], "mapping_not_exact")

    def test_confirmed_active_mapping_is_not_ready_for_price_task(self) -> None:
        ready = is_price_task_mapping_ready(
            {
                "mapping_status": "CONFIRMED",
                "mapping_active": True,
                "room_type_id": "KING",
                "source_product_id": "mt-prod-1",
                "price_editable_flag": 1,
                "is_hour_room": 0,
                "source_platform": "meituan",
            }
        )

        self.assertFalse(ready["ready_for_price_task"])
        self.assertEqual(ready["blocked_reason"], "mapping_status_not_auto")

    def test_ctrip_requires_product_cipher_for_price_task(self) -> None:
        ready = is_price_task_mapping_ready(
            {
                "mapping_status": "AUTO",
                "mapping_active": True,
                "room_type_id": "KING",
                "source_product_id": "ct-prod-1",
                "price_editable_flag": 1,
                "is_hour_room": 0,
                "source_platform": "ctrip",
                "product_cipher": "",
            }
        )

        self.assertFalse(ready["ready_for_price_task"])
        self.assertEqual(ready["blocked_reason"], "ctrip_product_cipher_missing")

    def test_outbox_blocks_non_auto_mapping_before_inserting_tasks(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        db_path = str(Path(tmp.name) / "outbox.sqlite")
        with contextlib.closing(connect(db_path)) as conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO meituan_ota_goods_price_mapping
                  (hotel_name, channel_source, room_type_name, business_date, ota_product_id, ota_product_name,
                   mapping_status, is_active, price_editable_flag, is_hour_room)
                VALUES
                  ('测试酒店', 'meituan', 'KING', '2026-06-30', 'mt-prod-1', 'KING-无早',
                   'PENDING', 1, 1, 0)
                """
            )
            conn.commit()

        result = write_zhiting_price_tasks(
            db_path,
            channel_source="meituan",
            hotel_name="测试酒店",
            room_type_name="KING",
            business_date="2026-06-30",
            target_sale_price=199,
            source_decision_id="DEC-MAP",
            created_by="owner-1",
            write_enabled=True,
            confirmed=True,
            allowed_channels=["meituan"],
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "price_task_mapping_not_ready")
        self.assertEqual(result["inserted_task_count"], 0)
        self.assertIn("mapping_status_not_auto", {item["reason"] for item in result["skipped_products"]})

    def test_product_skip_reason_uses_active_auto_mapping(self) -> None:
        reason = _product_skip_reason(
            "meituan",
            {
                "mapping_status": "AUTO",
                "mapping_active": True,
                "room_type_id": "KING",
                "source_product_id": "mt-prod-1",
                "price_editable_flag": 1,
                "is_hour_room": 0,
                "source_platform": "meituan",
            },
        )
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
