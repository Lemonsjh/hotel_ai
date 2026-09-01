from __future__ import annotations

import unittest

import runtime  # noqa: F401 - installs runtime patches
from runtime.decisions.customer import render_s17_summary


class TestS17PublicText(unittest.TestCase):
    def test_user_visible_summary_hides_internal_field_names_and_optional_gaps(self) -> None:
        summary = render_s17_summary(
            {
                "window_start": "2026-07-04",
                "window_end": "2026-08-03",
                "as_of_datetime": "2026-08-03 20:59:00",
                "populations": {
                    "pms_booking_created": {
                        "created_order_count": 10,
                        "booked_rooms": 11,
                        "current_cancelled_orders": 2,
                        "current_cancelled_share": 0.2,
                        "current_non_cancelled_orders": 8,
                        "guest_source_order_distribution": [
                            {"name": "中介", "value": 9, "share": 0.9},
                            {"name": "非会员", "value": 1, "share": 0.1},
                        ],
                        "booking_channel_status": "unavailable",
                        "unmapped_count": 2,
                        "contact_proxy": {
                            "status": "unavailable",
                            "reason": "contact_semantic_unavailable_or_masked",
                        },
                    },
                    "pms_arrival_cohort": {
                        "arrival_order_count": 7,
                        "planned_arrival_order_count": 7,
                        "booked_rooms": 8,
                        "planned_room_nights": 8,
                        "current_cancelled_orders": 2,
                        "current_cancelled_share": 2 / 9,
                        "current_non_cancelled_orders": 7,
                        "stay_duration_buckets": [
                            {"name": "1_night", "value": 7, "share": 1.0},
                        ],
                        "long_stay_share": 0.1,
                    },
                    "realized_stay": {
                        "realized_room_nights": 12,
                        "realized_room_fee": 1800,
                        "realized_adr": 150,
                        "source_distribution": [
                            {"customer_source": "中介", "realized_room_nights": 12, "share": 1.0},
                        ],
                    },
                },
                "data_gaps": [
                    "meituan_scan_order",
                    "meituan_monthly_background",
                    "provider_order_detail",
                    "provider_profile_background",
                    "room_mix_background",
                    "contact_semantic_unavailable_or_masked",
                ],
            }
        )

        forbidden = (
            "guest_source",
            "customer_source",
            "arrival_time",
            "member_level",
            "booking_product_tag",
            "room_type_id",
            " contact ",
            "population",
            "meituan_scan_order",
            "meituan_monthly_background",
            "provider_order_detail",
            "provider_profile_background",
            "room_mix_background",
            "当前物理在住",
            "KF11",
        )
        for field_name in forbidden:
            self.assertNotIn(field_name, summary)

        self.assertIn("预订客源分类（仅表示客源类别，不代表预订渠道）", summary)
        self.assertIn("渠道识别所需的数据映射尚未完成", summary)
        self.assertIn("计划到店订单：7 单，8 间预订房，计划入住 8 间夜", summary)
        self.assertIn("计划到店订单入住时长结构", summary)
        self.assertIn("统一房型编码缺失", summary)
        self.assertIn("实际入住客源结构（RS01）", summary)
        self.assertIn("当前联系人来源值为脱敏值", summary)
        self.assertIn("不同统计口径", summary)
        self.assertNotIn("数据缺口：", summary)


if __name__ == "__main__":
    unittest.main()
