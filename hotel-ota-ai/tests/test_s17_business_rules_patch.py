from __future__ import annotations

import datetime as dt
import unittest

import runtime  # noqa: F401 - installs S17 convergence patch
from runtime.adapters import s17_repository
from runtime.algorithms.guest_frequency import aggregate_real_guest_frequency
from runtime.s17_feishu_route_patch import _is_s17_message


class TestS17BusinessRulesPatch(unittest.TestCase):
    def test_valid_name_total_is_separate_from_realized_frequency_without_charge_subject_gate(self) -> None:
        rows = [
            {
                "hotel_id": "puyue", "source_platform": "pms", "order_id": "o1", "room_no": "101",
                "guest_name": " 张 三 ", "charge_subject": "房费", "business_date": "2026-07-10",
                "checkin_time": "2026-07-10", "room_nights": 1, "snapshot_time": "2026-08-01",
            },
            {
                "hotel_id": "puyue", "source_platform": "pms", "order_id": "o1", "room_no": "102",
                "guest_name": "张   三", "charge_subject": "房费", "business_date": "2026-07-10",
                "checkin_time": "2026-07-10", "room_nights": 1, "snapshot_time": "2026-08-01",
            },
            {
                "hotel_id": "puyue", "source_platform": "pms", "order_id": "o2", "room_no": "103",
                "guest_name": "李四", "charge_subject": "加收全天", "business_date": "2026-07-11",
                "checkin_time": "2026-07-11", "room_nights": 1, "snapshot_time": "2026-08-01",
            },
            {
                "hotel_id": "puyue", "source_platform": "pms", "order_id": "o3", "room_no": "104",
                "guest_name": "王五", "charge_subject": "早餐", "business_date": "2026-07-12",
                "checkin_time": "2026-07-12", "room_nights": 0, "snapshot_time": "2026-08-01",
            },
        ]
        result = aggregate_real_guest_frequency(
            rows, [], hotel_id="puyue",
            window_start=dt.datetime(2026, 7, 1), window_end=dt.datetime(2026, 8, 1),
            as_of=dt.datetime(2026, 8, 2), contact_hmac_secret=None,
        )
        self.assertEqual(result["valid_guest_name_count"], 3)
        self.assertEqual(result["realized_frequency_guest_name_count"], 2)
        self.assertFalse(result["charge_subject_filter_for_frequency"])
        self.assertEqual(result["frequency_distribution"][0]["name"], "窗口内1次")
        self.assertEqual(result["frequency_distribution"][0]["value"], 2)
        self.assertEqual(result["frequency_level_rule"]["5+"], "窗口内5次及以上")

    def test_add_full_day_is_lodging_revenue_without_duplicate_room_nights(self) -> None:
        rows = [
            {
                "hotel_id": "puyue", "source_platform": "pms", "order_id": "o1", "room_no": "101",
                "charge_subject": "房费", "business_date": "2026-07-10", "customer_source": "中介",
                "room_type_id": "rt1", "room_nights": 1, "room_fee": 100, "snapshot_time": "2026-08-01",
            },
            {
                "hotel_id": "puyue", "source_platform": "pms", "order_id": "o1", "room_no": "101",
                "charge_subject": "加收全天", "business_date": "2026-07-10", "customer_source": "中介",
                "room_type_id": "rt1", "room_nights": 1, "room_fee": 20, "snapshot_time": "2026-08-01",
            },
            {
                "hotel_id": "puyue", "source_platform": "pms", "order_id": "o2", "room_no": "102",
                "charge_subject": "加收全天", "business_date": "2026-07-11", "customer_source": "中介",
                "room_type_id": "rt1", "room_nights": 1, "room_fee": 80, "snapshot_time": "2026-08-01",
            },
        ]
        result = s17_repository.aggregate_realized(
            rows,
            hotel_id="puyue",
            window_start=dt.datetime(2026, 7, 1),
            window_end=dt.datetime(2026, 8, 1),
            as_of=dt.datetime(2026, 8, 2),
        )
        self.assertIn("加收全天", result["approved_charge_subjects"])
        self.assertEqual(result["realized_room_nights"], 2.0)
        self.assertEqual(result["realized_room_fee"], 200.0)
        self.assertEqual(result["realized_adr"], 100.0)
        self.assertEqual(result["excluded_unapproved_charge_record_count"], 0)

    def test_operational_distributions_are_not_small_cell_suppressed(self) -> None:
        cells = [
            {"name": "3_4_nights", "value": 2, "share": 0.01, "unit": "orders"},
            {"name": "5_7_nights", "value": 1, "share": 0.005, "unit": "orders"},
        ]
        visible, suppressed = s17_repository.suppress_cells(
            cells, count_field="value", minimum_cohort_size=5, max_output_cells=100
        )
        self.assertEqual(len(visible), 2)
        self.assertEqual(suppressed, 0)

        contact_cells = [
            {"name": "5_plus_orders", "value": 2, "share": 1.0, "unit": "contact_proxy_keys"}
        ]
        contact_visible, contact_suppressed = s17_repository.suppress_cells(
            contact_cells, count_field="value", minimum_cohort_size=5, max_output_cells=100
        )
        self.assertEqual(contact_visible, [])
        self.assertEqual(contact_suppressed, 1)

    def test_complete_s17_alias_uses_formal_route(self) -> None:
        self.assertTrue(_is_s17_message("完整s17"))
        self.assertTrue(_is_s17_message("完整 S17"))
        self.assertTrue(_is_s17_message("详细版s17"))

    def test_kf11_is_short_circuited_before_database_query(self) -> None:
        rows, meta = s17_repository._mapped_rows(
            None, {}, s17_repository.CORE_TABLES["physical"], "puyue",
            as_of=dt.datetime(2026, 8, 1), fields=("hotel_id",),
        )
        self.assertEqual(rows, [])
        self.assertEqual(meta["status"], "retired")
        self.assertEqual(meta["reason"], "s17_physical_occupancy_retired")


if __name__ == "__main__":
    unittest.main()
