from __future__ import annotations

import unittest

from runtime.feishu_output_renderer import render_feishu_output


class TestBusinessSnapshotSalesMetrics(unittest.TestCase):
    def test_business_snapshot_prefers_room_nights_and_order_count_for_today_sales(self) -> None:
        rendered = render_feishu_output(
            {
                "intent": "run_s02",
                "auth_role": "owner",
                "data_source_type": "mysql_db",
                "business_date": "2026-06-26",
                "approval_data_allowed": False,
                "live_allowed": False,
                "core_metrics": {
                    "total_rooms": 31,
                    "sold_rooms": 20,
                    "sold_room_nights_today": 23,
                    "sold_orders_today": 18,
                    "occupancy_rate": 0.7419,
                    "adr": 188,
                    "revpar": 139.6,
                },
                "summary": "数据库经营快照已生成。",
            },
            "owner_business",
        )

        text = rendered["text"]
        self.assertIn("今日已售间夜：23", text)
        self.assertIn("今日订单数：18", text)
        self.assertIn("当前占用房：20", text)
        self.assertNotIn("sold_room_nights_today", text)
        self.assertNotIn("sold_orders_today", text)


if __name__ == "__main__":
    unittest.main()
