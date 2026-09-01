import unittest

from marketing_diagnosis.reporting_v3 import build_html
from marketing_diagnosis.visual_diagnosis import build_visual_diagnosis


class VisualDiagnosisTests(unittest.TestCase):
    def test_exposure_uses_real_zero_and_daily_ratio(self):
        result = build_visual_diagnosis({"exposure_daily": [{
            "business_date": "2026-07-13", "total_exposure": 100,
            "non_ad_exposure": 70, "ad_exposure": 30,
            "ad_exposure_ratio_pct": 30,
        }]})
        item = result["items"][2]
        self.assertEqual(item["data_status"], "success")
        self.assertEqual(item["item_score"], 4)
        self.assertEqual(item["fields"][-1]["value"], .3)
        self.assertEqual(item["fields"][0]["origin"], "区间汇总")
        self.assertEqual(item["fields"][3]["origin"], "公式计算")

    def test_exposure_deduplicates_days_before_30_day_sum(self):
        rows = []
        for day in range(1, 32):
            date = f"2026-06-{day:02d}" if day <= 30 else "2026-07-01"
            rows.append({"business_date": date, "snapshot_time": f"{date} 10:00:00",
                         "total_exposure": 10, "non_ad_exposure": 8, "ad_exposure": 2})
        rows.append({"business_date": "2026-07-01", "snapshot_time": "2026-07-01 09:00:00",
                     "total_exposure": 999, "non_ad_exposure": 999, "ad_exposure": 0})
        item = build_visual_diagnosis({"exposure_daily": rows})["items"][2]
        self.assertEqual(item["fields"][0]["value"], 300)
        self.assertEqual(item["fields"][2]["value"], 60)

    def test_jl02_and_jl01_are_rendered_with_requested_grains(self):
        visual = build_visual_diagnosis({
            "hotel_performance_daily": [
                {"metric_name": "房费", "value_day": 100, "value_month": 3000, "value_year": 20000, "snapshot_time": "2026-07-14 10:00:00"},
                {"metric_name": "房费", "value_day": 90, "value_month": 2000, "value_year": 18000, "snapshot_time": "2025-07-14 10:00:00"},
            ],
            "room_type_performance_daily": [
                {"room_type_id": "r1", "room_type_name": "云栖大床房", "metric_name": "出租率", "value_day": 80, "value_month": 55, "value_year": 70},
                {"room_type_id": "r1", "room_type_name": "云栖大床房", "metric_name": "RevPar", "value_day": 120, "value_month": 100, "value_year": 110},
            ],
        })
        yoy, rooms = visual["items"][0], visual["items"][1]
        self.assertEqual(yoy["fields"][0]["value"], 3000)
        self.assertEqual(yoy["fields"][1]["value"], 2000)
        self.assertEqual(yoy["fields"][2]["value"], .5)
        self.assertEqual(rooms["fields"][0]["value"], 1)
        self.assertEqual(rooms["records"][0]["revpar_month"], 100)

    def test_flow_sums_available_daily_values_and_peer_averages(self):
        rows = [
            {"platform": "meituan", "period_type": "日", "business_date": "2026-07-13",
             "exposure": 100, "peer_exposure": 80, "views": 20, "peer_views": 15, "paid_orders": 2},
            {"platform": "meituan", "period_type": "日", "business_date": "2026-07-14",
             "exposure": 120, "peer_exposure": 90, "views": 30, "peer_views": 25, "paid_orders": 3},
        ]
        item = build_visual_diagnosis({"ota_funnel": rows})["items"][3]
        values = {field["label"]: field["value"] for field in item["fields"]}
        self.assertEqual(values["曝光人数"], 220)
        self.assertEqual(values["曝光人数同行均值"], 170)
        self.assertEqual(values["浏览人数"], 50)
        self.assertEqual(values["浏览人数同行均值"], 40)

    def test_missing_is_not_scored_as_zero(self):
        result = build_visual_diagnosis({})
        self.assertEqual(result["items"][2]["data_status"], "missing")
        self.assertIsNone(result["items"][2]["item_score"])
        self.assertEqual(result["items"][7]["data_status"], "zero")
        self.assertEqual(result["items"][7]["item_score"], 0)
        self.assertEqual(result["connected_base_score"], 5)

    def test_report_renders_23_item_database_section(self):
        visual = build_visual_diagnosis({})
        html = build_html({
            "hotel_name": "测试酒店", "platform": "meituan",
            "period_start": "2026-06-14", "period_end": "2026-07-13",
            "visual_diagnosis": visual, "metrics": {}, "data_quality": {},
            "module_scores": [], "rule_hits": [],
        })
        self.assertIn("23项诊断结果总览", html)
        self.assertIn("id='rule-21'", html)
        self.assertIn("首页视频", html)
        self.assertIn("规则待确认", html)
        # 客户页面只展示业务结果，不强制展示数据库表名和技术字段。
        self.assertIn("当前得分", html)
        self.assertIn("class='diagnosis-card config-status-group'", html)


if __name__ == "__main__":
    unittest.main()
