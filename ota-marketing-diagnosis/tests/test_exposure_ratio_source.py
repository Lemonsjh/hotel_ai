import unittest

from marketing_diagnosis.visual_diagnosis_v2 import build_visual_diagnosis


class ExposureRatioSourceTests(unittest.TestCase):
    def test_daily_exposure_ratio_prefers_database_percentage(self):
        item = build_visual_diagnosis({
            "exposure_daily": [{
                "business_date": "2026-06-15",
                "total_exposure": 100,
                "non_ad_exposure": 100,
                "ad_exposure": 0,
                "ad_exposure_ratio_pct": 8.95,
            }],
        })["items"][2]

        daily = item["fields"][-1]
        self.assertAlmostEqual(daily["value"], 0.0895)
        self.assertEqual(daily["origin"], "数据库原值")
        self.assertIn("ad_exposure_ratio_pct", daily["note"])

    def test_daily_exposure_ratio_falls_back_to_formula(self):
        item = build_visual_diagnosis({
            "exposure_daily": [{
                "business_date": "2026-06-16",
                "total_exposure": 100,
                "non_ad_exposure": 70,
                "ad_exposure": 30,
            }],
        })["items"][2]

        daily = item["fields"][-1]
        self.assertAlmostEqual(daily["value"], 0.3)
        self.assertEqual(daily["origin"], "公式计算")
        self.assertIn("回退", daily["note"])

    def test_30_day_total_ratio_still_uses_summed_exposure(self):
        item = build_visual_diagnosis({
            "exposure_daily": [{
                "business_date": "2026-06-15",
                "total_exposure": 62019,
                "non_ad_exposure": 56469,
                "ad_exposure": 5550,
                "ad_exposure_ratio_pct": 8.95,
            }],
        })["items"][2]

        self.assertAlmostEqual(item["fields"][3]["value"], 5550 / 62019)
        self.assertEqual(item["fields"][3]["origin"], "公式计算")
        self.assertAlmostEqual(item["fields"][-1]["value"], 0.0895)


if __name__ == "__main__":
    unittest.main()
