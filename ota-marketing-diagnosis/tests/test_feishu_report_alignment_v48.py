from __future__ import annotations

import unittest

from importlib import import_module


adapter = import_module("skills.s14-operation-diagnosis.runtime.feishu_adapter")


class FeishuReportAlignmentTests(unittest.TestCase):
    def _result(self):
        return {
            "hotel_id": "puyue",
            "hotel_name": "璞悦",
            "platform": "multi",
            "data_source": "hotel_puyue_mysql",
            "period_start": "2026-06-17",
            "period_end": "2026-07-16",
            "report_url": "http://example.test/report.html",
            # Deliberately wrong legacy values: the reply must ignore these.
            "final_score": 78,
            "metrics": {
                "ota_funnel": {
                    "exposure": 79072,
                    "views": 9550,
                    "paid_orders": 847,
                    "payment_conversion_rate": 0.089,
                }
            },
            "module_scores": [
                {
                    "module_id": "M03",
                    "module_name": "旧模块",
                    "score": 9.8,
                    "weight": 15,
                    "rate": 0.6,
                }
            ],
            "visual_diagnosis": {
                # Stale pre-patch aggregate: Feishu must use the final item
                # scores and bases rendered by the report instead.
                "normalized_score": 86.4,
                "raw_score": 76.0,
                "connected_base_score": 88.0,
                "items": [
                    {
                        "standard_item_id": 2,
                        "item_name": "房型 RevPAR 与低效房型",
                        "base_score": 8,
                        "item_score": 4.8,
                        "score_ratio": 0.6,
                        "participates_in_score": True,
                        "data_status": "success",
                        "fields": [
                            {"label": "全部在售房型数", "value": 10},
                            {"label": "低效房型数", "value": 2},
                            {"label": "低效房型占比", "value": 0.2},
                        ],
                    },
                    {
                        "standard_item_id": 4,
                        "item_name": "流量数据分析",
                        "base_score": 15,
                        "item_score": 9,
                        "score_ratio": 0.6,
                        "participates_in_score": True,
                        "data_status": "success",
                        "fields": [
                            {"label": "曝光人数", "value": 17187},
                            {"label": "浏览人数", "value": 1619},
                            {"label": "支付订单数", "value": 147},
                            {"label": "浏览-支付转化率", "value": 0.0908},
                        ],
                    },
                    {
                        "standard_item_id": 9,
                        "item_name": "推广数据",
                        "base_score": 8,
                        "item_score": 4.8,
                        "score_ratio": 0.6,
                        "participates_in_score": True,
                        "data_status": "success",
                        "fields": [
                            {"label": "推广状态", "value": "RUNNING"},
                            {"label": "近30天推广投入", "value": 2000},
                            {"label": "预订订单金额（元）", "value": 12000},
                            {"label": "ROI", "value": 6},
                        ],
                    },
                    {
                        "standard_item_id": 13,
                        "item_name": "口碑分析",
                        "base_score": 10,
                        "item_score": 8,
                        "score_ratio": 0.8,
                        "participates_in_score": True,
                        "data_status": "success",
                        "fields": [
                            {"label": "美团评分", "value": 4.8},
                            {"label": "美团点评条数", "value": 2337},
                            {"label": "昨日新增点评数", "value": 7},
                            {"label": "美团未回复点评数", "value": 9},
                        ],
                    },
                    {
                        "standard_item_id": 11,
                        "item_name": "房型名称卖点优化",
                        "base_score": 4,
                        "item_score": 0,
                        "score_ratio": 0,
                        "participates_in_score": True,
                        "data_status": "zero",
                        "fields": [],
                    },
                    {
                        "standard_item_id": 5,
                        "item_name": "用户来源数据",
                        "base_score": 0,
                        "item_score": None,
                        "score_ratio": None,
                        "participates_in_score": False,
                        "data_status": "missing",
                        "fields": [],
                    },
                ],
            },
        }

    def test_text_reply_uses_same_visual_score_and_fields_as_report(self):
        reply = adapter.build_feishu_reply(self._result())
        self.assertIn("总得分：26.6/100", reply)
        self.assertNotIn("折算得分", reply)
        self.assertNotIn("原始得分", reply)
        self.assertNotIn("已接入基础分", reply)
        self.assertNotIn("未取到数据", reply)
        self.assertIn("曝光 17,187", reply)
        self.assertIn("支付订单 147", reply)
        self.assertIn("二转 9.08%", reply)
        self.assertIn("预订订单金额 ¥12,000.00", reply)
        self.assertIn("昨日新增 7", reply)
        self.assertIn("11 房型名称卖点优化：0/4｜真实为0", reply)
        self.assertNotIn("78.0/100", reply)
        self.assertNotIn("79,072", reply)
        self.assertNotIn("M03", reply)

    def test_card_reply_uses_the_same_report_summary(self):
        card = adapter.build_feishu_card_reply(self._result())
        content = "\n".join(
            element.get("text", {}).get("content", "")
            for element in card["card"]["elements"]
            if element.get("tag") == "div"
        )
        self.assertIn("总得分：26.6/100", content)
        self.assertIn("04 流量", content)
        self.assertIn("09 推广", content)
        self.assertIn("13 口碑", content)
        self.assertNotIn("79,072", content)

    def test_ctrip_summary_is_included_when_ctrip_data_is_connected(self):
        result = self._result()
        result["ctrip_summary"] = {
            "total_score": 18.2,
            "full_score": 27.0,
            "connected_items": 16,
            "scored_items": 15,
        }

        reply = adapter.build_feishu_reply(result)
        card = adapter.build_feishu_card_reply(result)
        content = "\n".join(
            element.get("text", {}).get("content", "")
            for element in card["card"]["elements"]
            if element.get("tag") == "div"
        )

        expected = "携程得分：23/100｜已接入 16 项｜已计分 15 项"
        self.assertIn(expected, reply)
        self.assertIn(expected, content)


if __name__ == "__main__":
    unittest.main()
