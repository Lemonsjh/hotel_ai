from __future__ import annotations

import unittest

from marketing_diagnosis.visual_diagnosis_v14 import _patch_authoritative_flow


class AuthoritativeFlowCsvValuesTest(unittest.TestCase):
    def _result(self) -> dict:
        return {
            "items": [
                {
                    "standard_item_id": 4,
                    "item_name": "流量数据分析",
                    "base_score": 15,
                    "participates_in_score": True,
                    "data_status": "pending_rule",
                    "score_ratio": None,
                    "item_score": None,
                    "fields": [
                        {"label": "曝光人数", "value": 999999},
                        {"label": "曝光人数同行排名", "value": None},
                    ],
                }
            ]
        }

    @staticmethod
    def _row(day: str, exposure: float, peer: float | None, rank: str | None, stamp: str) -> dict:
        row = {
            "platform": "meituan",
            "period_type": "日",
            "business_date": day,
            "snapshot_time": stamp,
            "source_table": "hotel_puyue.meituan_ota_business_metrics",
            "exposure": exposure,
            "peer_exposure": peer,
            "exposure_metric_code": "FLOW_EXPOSURE_UV",
            "exposure_metric_name": "曝光人数",
        }
        if rank is not None:
            row["exposure_rank_raw"] = rank
            row["exposure_rank"] = int(rank.split("/", 1)[0])
        return row

    def test_exact_csv_totals_and_latest_nonempty_rank(self) -> None:
        rows = [
            self._row("2026-07-11", 4033, 1544, None, "2026-07-11 16:00:00"),
            self._row("2026-07-12", 3190, 1467, "4/20", "2026-07-12 16:00:00"),
            self._row("2026-07-13", 2711, 1639, "6/20", "2026-07-13 16:00:00"),
            self._row("2026-07-14", 2611, 1377, "5/20", "2026-07-14 16:00:00"),
            self._row("2026-07-15", 999, None, None, "2026-07-15 08:00:00"),
            self._row("2026-07-15", 332, None, None, "2026-07-15 16:00:00"),
        ]
        result = self._result()
        _patch_authoritative_flow(result, {"ota_funnel": rows})

        item = result["items"][0]
        fields = {field["label"]: field for field in item["fields"]}

        self.assertEqual(fields["曝光人数"]["value"], 12877)
        self.assertEqual(fields["曝光人数同行均值"]["value"], 6027)

        rank_label = "曝光人数同行排名（取值日：2026-07-14）"
        self.assertIn(rank_label, fields)
        self.assertEqual(fields[rank_label]["value"], "5/20")
        self.assertIsNotNone(item["item_score"])
        self.assertNotEqual(item["data_status"], "missing")

    def test_ordinary_same_name_metric_is_not_mixed_into_db_total(self) -> None:
        rows = [
            self._row("2026-07-14", 2611, 1377, "5/20", "2026-07-14 16:00:00"),
            {
                "platform": "meituan",
                "period_type": "日",
                "business_date": "2026-07-14",
                "snapshot_time": "2026-07-14 18:00:00",
                "source_table": "hotel_puyue.meituan_ota_business_metrics",
                "exposure": 999999,
                "peer_exposure": 999999,
                "exposure_metric_code": "OTHER_EXPOSURE_METRIC",
            },
        ]
        result = self._result()
        _patch_authoritative_flow(result, {"ota_funnel": rows})
        fields = {field["label"]: field for field in result["items"][0]["fields"]}
        self.assertEqual(fields["曝光人数"]["value"], 2611)
        self.assertEqual(fields["曝光人数同行均值"]["value"], 1377)


if __name__ == "__main__":
    unittest.main()
