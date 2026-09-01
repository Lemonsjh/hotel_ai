from __future__ import annotations

import argparse
import unittest
from unittest import mock

from runtime.adapters import database


class OperationDiagnosisMetricMappingTests(unittest.TestCase):
    def test_meituan_hos_and_info_scores_map_to_distinct_fields(self) -> None:
        def fake_rows(conn, args, profile, *, template, table_keys):
            if template == "ota_business_metrics":
                return {
                    "payload": {
                        "rows": [
                            {"metric_name": "HOS分", "metric_value": "5.6", "business_date": "2026-07-02"},
                            {"metric_name": "信息分", "metric_value": "107", "business_date": "2026-07-02"},
                            {"metric_name": "浏览人数", "metric_value": "104", "business_date": "2026-07-03"},
                        ]
                    },
                    "data_business_date": "2026-07-03",
                    "data_snapshot_time": "2026-07-03 11:14:39",
                }
            return {"payload": {"rows": []}}

        latest_score_rows = [
            {"metric_name": "HOS分", "metric_value": "5.6", "business_date": "2026-07-02"},
            {"metric_name": "信息分", "metric_value": "107", "business_date": "2026-07-02"},
        ]
        with mock.patch("runtime.adapters.database._mysql_latest_metrics", return_value={"normalized_metrics": {}}), mock.patch(
            "runtime.adapters.database._query_mysql_v4_rows", side_effect=fake_rows
        ), mock.patch("runtime.adapters.database._query_mysql_latest_score_metric_rows", return_value=latest_score_rows):
            result = database._query_mysql_operation_diagnosis_from_v4(
                object(),
                argparse.Namespace(hotel_id="puyue", date="2026-07-03"),
                {"hotel_ids": {"puyue": {"hotel_name": "puyue"}}},
            )

        self.assertEqual(result["hos_score"], 5.6)
        self.assertEqual(result["ota_health_score"], 107.0)
        self.assertEqual(result["views"], 104.0)


if __name__ == "__main__":
    unittest.main()
