from __future__ import annotations

import sqlite3
import unittest

from runtime.adapters import database
from runtime.s2_business_metric_snapshot_patch import (
    _per_metric_snapshot_clause,
    s2_business_metric_snapshot_scope,
)


class TestS2BusinessMetricSnapshotScope(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE meituan_ota_business_metrics (
                hotel_id TEXT NOT NULL,
                business_date TEXT NOT NULL,
                metric_code TEXT NOT NULL,
                metric_value REAL,
                snapshot_time TEXT NOT NULL
            )
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    def _insert(
        self,
        metric_code: str,
        metric_value: float,
        snapshot_time: str,
        *,
        business_date: str = "2026-08-07",
        hotel_id: str = "H001",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO meituan_ota_business_metrics
                (hotel_id, business_date, metric_code, metric_value, snapshot_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (hotel_id, business_date, metric_code, metric_value, snapshot_time),
        )
        self.conn.commit()

    def _query(self, business_date: str, *, as_of_time: str | None = None) -> list[tuple[str, float, str]]:
        columns = {
            "metric_code": "metric_code",
            "snapshot_time": "snapshot_time",
        }
        scope_parts = ["`hotel_id` = %s", "DATE(`business_date`) = %s"]
        scope_params: list[object] = ["H001", business_date]
        if as_of_time is not None:
            scope_parts.append("`snapshot_time` <= %s")
            scope_params.append(as_of_time)
        clause, clause_params = _per_metric_snapshot_clause(
            "meituan_ota_business_metrics",
            columns,
            scope_parts,
            scope_params,
        )
        sql = (
            "SELECT metric_code, metric_value, snapshot_time "
            "FROM meituan_ota_business_metrics "
            f"WHERE {' AND '.join(scope_parts)} AND {clause} "
            "ORDER BY metric_code"
        ).replace("%s", "?")
        rows = self.conn.execute(sql, tuple(scope_params + clause_params)).fetchall()
        return [
            (str(row["metric_code"]), float(row["metric_value"]), str(row["snapshot_time"]))
            for row in rows
        ]

    def test_different_metric_snapshot_times_keep_each_metric_latest_row(self) -> None:
        self._insert("EXPOSE_PV_CNT", 100, "2026-08-07 15:30:00")
        self._insert("PAY_ORDER_CNT", 8, "2026-08-07 15:28:00")
        self._insert("PAY_ADR", 260, "2026-08-07 15:25:00")

        self.assertEqual(
            self._query("2026-08-07"),
            [
                ("EXPOSE_PV_CNT", 100.0, "2026-08-07 15:30:00"),
                ("PAY_ADR", 260.0, "2026-08-07 15:25:00"),
                ("PAY_ORDER_CNT", 8.0, "2026-08-07 15:28:00"),
            ],
        )

    def test_duplicate_metric_code_keeps_only_newest_snapshot(self) -> None:
        self._insert("INTENTION_UV", 40, "2026-08-07 14:00:00")
        self._insert("INTENTION_UV", 56, "2026-08-07 15:00:00")

        self.assertEqual(
            self._query("2026-08-07"),
            [("INTENTION_UV", 56.0, "2026-08-07 15:00:00")],
        )

    def test_exact_business_date_does_not_fallback(self) -> None:
        self._insert(
            "PAY_AMT",
            1200,
            "2026-08-06 23:00:00",
            business_date="2026-08-06",
        )

        self.assertEqual(self._query("2026-08-07"), [])

    def test_explicit_as_of_time_selects_each_metric_latest_before_cutoff(self) -> None:
        self._insert("EXPOSE_PV_CNT", 80, "2026-08-07 10:00:00")
        self._insert("EXPOSE_PV_CNT", 100, "2026-08-07 12:00:00")
        self._insert("PAY_ORDER_CNT", 5, "2026-08-07 09:30:00")
        self._insert("PAY_ORDER_CNT", 9, "2026-08-07 13:00:00")

        self.assertEqual(
            self._query("2026-08-07", as_of_time="2026-08-07 11:00:00"),
            [
                ("EXPOSE_PV_CNT", 80.0, "2026-08-07 10:00:00"),
                ("PAY_ORDER_CNT", 5.0, "2026-08-07 09:30:00"),
            ],
        )

    def test_identical_snapshot_batch_is_unchanged(self) -> None:
        self._insert("EXPOSE_PV_CNT", 100, "2026-08-07 15:30:00")
        self._insert("INTENTION_UV", 50, "2026-08-07 15:30:00")

        self.assertEqual(
            self._query("2026-08-07"),
            [
                ("EXPOSE_PV_CNT", 100.0, "2026-08-07 15:30:00"),
                ("INTENTION_UV", 50.0, "2026-08-07 15:30:00"),
            ],
        )

    def test_scope_changes_snapshot_clause_only_inside_s2_context(self) -> None:
        columns = {
            "metric_code": "metric_code",
            "snapshot_time": "snapshot_time",
        }
        scope_parts = ["`hotel_id` = %s", "DATE(`business_date`) = %s"]
        scope_params = ["H001", "2026-08-07"]

        outside_clause, _ = database._latest_snapshot_clause(
            "meituan_ota_business_metrics",
            columns,
            scope_parts,
            scope_params,
        )
        with s2_business_metric_snapshot_scope():
            inside_clause, _ = database._latest_snapshot_clause(
                "meituan_ota_business_metrics",
                columns,
                scope_parts,
                scope_params,
            )
        restored_clause, _ = database._latest_snapshot_clause(
            "meituan_ota_business_metrics",
            columns,
            scope_parts,
            scope_params,
        )

        self.assertNotIn("GROUP BY", outside_clause)
        self.assertIn("GROUP BY `metric_code`", inside_clause)
        self.assertNotIn("GROUP BY", restored_clause)


if __name__ == "__main__":
    unittest.main()
