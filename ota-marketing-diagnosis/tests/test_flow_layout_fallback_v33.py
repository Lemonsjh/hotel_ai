from __future__ import annotations

import unittest

from marketing_diagnosis.visual_diagnosis_v15 import build_visual_diagnosis


class FlowLayoutFallbackTest(unittest.TestCase):
    def test_missing_canonical_flow_keeps_complete_layout(self):
        sections = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "daily",
                    "business_date": "2026-07-15",
                    "snapshot_time": "2026-07-15 12:00:00",
                    "exposure": 1000,
                    "peer_exposure": 900,
                    "views": 200,
                    "peer_views": 180,
                    "paid_orders": 20,
                    "peer_paid_orders": 18,
                }
            ]
        }

        result = build_visual_diagnosis(sections)
        item = next(
            item
            for item in result["items"]
            if int(item.get("standard_item_id") or 0) == 4
        )

        labels = [str(field.get("label") or "") for field in item.get("fields") or []]
        self.assertEqual(item["data_status"], "missing")
        self.assertIsNone(item["item_score"])
        self.assertGreaterEqual(len(labels), 5)
        self.assertIn("曝光人数", labels)
        self.assertIn("浏览人数", labels)
        self.assertIn("支付订单数", labels)
        self.assertIn("曝光-浏览转化率", labels)
        self.assertIn("浏览-支付转化率", labels)


if __name__ == "__main__":
    unittest.main()
