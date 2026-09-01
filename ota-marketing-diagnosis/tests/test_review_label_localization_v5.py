import unittest

from marketing_diagnosis.reporting_v9 import _localize_result


class ReviewLabelLocalizationTests(unittest.TestCase):
    def test_legacy_review_labels_are_translated_to_chinese(self):
        result = {
            "visual_diagnosis": {
                "items": [
                    {
                        "standard_item_id": 13,
                        "fields": [
                            {"label": "meituan评分", "value": 4.8},
                            {"label": "meituan点评条数", "value": 2327},
                            {"label": "meituan未回复点评数", "value": 0},
                            {"label": "dianping评分", "value": 4.3},
                            {"label": "dianping点评条数", "value": 100},
                        ],
                    }
                ]
            }
        }

        localized = _localize_result(result)
        labels = [
            field["label"]
            for field in localized["visual_diagnosis"]["items"][0]["fields"]
        ]

        self.assertEqual(
            labels,
            [
                "美团评分",
                "美团点评条数",
                "美团未回复点评数",
                "大众点评评分",
                "大众点评点评条数",
            ],
        )
        self.assertEqual(
            result["visual_diagnosis"]["items"][0]["fields"][0]["label"],
            "meituan评分",
        )


if __name__ == "__main__":
    unittest.main()
