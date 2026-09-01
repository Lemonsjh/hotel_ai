from __future__ import annotations

import math
import unittest

from runtime.meituan_activity_net_price_patch import (
    activity_factor,
    enrich_product_prices,
    extract_discount_factors,
    normalize_commission_rate,
)


class MeituanActivityNetPricePatchTests(unittest.TestCase):
    def test_commission_rate_normalization(self) -> None:
        self.assertEqual(normalize_commission_rate("12.00%"), 0.12)
        self.assertEqual(normalize_commission_rate(12), 0.12)
        self.assertEqual(normalize_commission_rate(0.12), 0.12)
        self.assertIsNone(normalize_commission_rate("bad"))
        self.assertIsNone(normalize_commission_rate(100))

    def test_tiered_activity_uses_one_lowest_factor(self) -> None:
        self.assertEqual(
            extract_discount_factors("整周，连住2天9.5折、连住3天9.3折"),
            [0.95, 0.93],
        )
        self.assertEqual(
            activity_factor("整周，连住2天9.5折、连住3天9.3折"),
            0.93,
        )

    def test_commission_is_deducted_before_all_activity_factors_compound(self) -> None:
        price_rows = [
            {
                "hotel_id": "puyue",
                "room_type_id": "py08",
                "ota_product_id": "1599630802",
                "ota_sale_price": 358,
                "commission_rate": "12.00%",
            }
        ]
        activities = [
            {
                "hotel_id": "puyue",
                "room_type_id": "py08",
                "ota_product_id": "1599630802",
                "activity_id": activity_id,
                "activity_name": name,
                "activity_status": "进行中",
                "activity_time_range": "全年",
                "activity_rule_labels": label,
            }
            for activity_id, name, label in (
                (1, "首住折扣", "整周，9.4折"),
                (2, "今夜特价", "整周，18:00-次日06:00，9.3折"),
                (3, "天天特价", "整周，8折"),
                (4, "连住优惠", "整周，连住2天9.5折、连住3天9.3折"),
                (5, "早订多减", "整周，提前1天9.5折"),
                (6, "人群特惠1", "每间夜9折"),
                (7, "人群特惠2", "每间夜9.5折"),
                (8, "人群特惠3", "每间夜9折"),
                (9, "人群特惠4", "每间夜9折"),
                (10, "人群特惠5", "每间夜9折"),
            )
        ]
        result = enrich_product_prices(
            price_rows,
            activities,
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 21:28:00",
        )[0]
        factors = [0.94, 0.93, 0.80, 0.93, 0.95, 0.90, 0.95, 0.90, 0.90, 0.90]
        expected_combined = math.prod(factors)
        expected_commission_net = 358 * 0.88
        expected_activity_net = expected_commission_net * expected_combined
        self.assertAlmostEqual(result["commission_net_base_price"], expected_commission_net)
        self.assertAlmostEqual(result["combined_activity_factor"], expected_combined)
        self.assertAlmostEqual(result["estimated_activity_net_price"], expected_activity_net)
        self.assertEqual(result["matched_activity_count"], 10)
        self.assertTrue(result["activity_factors_compounded"])
        self.assertFalse(result["user_coupon_included"])
        self.assertEqual(
            result["activity_calculation_order"],
            "raw_price_then_commission_then_compound_all_matched_activities",
        )

    def test_tonight_activity_is_excluded_before_its_time_window(self) -> None:
        result = enrich_product_prices(
            [
                {
                    "room_type_id": "py08",
                    "ota_product_id": "P1",
                    "ota_sale_price": 100,
                    "commission_rate": "10%",
                }
            ],
            [
                {
                    "room_type_id": "py08",
                    "ota_product_id": "P1",
                    "activity_id": 1,
                    "activity_name": "今夜特价",
                    "activity_status": "进行中",
                    "activity_time_range": "全年",
                    "activity_rule_labels": "18:00-次日06:00，8折",
                },
                {
                    "room_type_id": "py08",
                    "ota_product_id": "P1",
                    "activity_id": 2,
                    "activity_name": "天天特价",
                    "activity_status": "进行中",
                    "activity_time_range": "全年",
                    "activity_rule_labels": "整周，9折",
                },
            ],
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 10:00:00",
        )[0]
        self.assertEqual(result["matched_activity_count"], 1)
        self.assertAlmostEqual(result["combined_activity_factor"], 0.9)
        self.assertAlmostEqual(result["estimated_activity_net_price"], 81.0)


if __name__ == "__main__":
    unittest.main()
