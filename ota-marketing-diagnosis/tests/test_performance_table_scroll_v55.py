from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v38 import enable_performance_table_scroll


class PerformanceTableScrollV55Tests(unittest.TestCase):
    def test_wraps_full_table_in_horizontal_scroll_container(self):
        html = (
            "<html><head></head><body>"
            "<div class='performance-trend-layout-v54'>"
            "<section class='performance-chart-v54'></section>"
            "<section class='performance-detail-v54'>"
            "<table class='performance-detail-table-v54'>"
            "<thead><tr><th>日期范围</th><th>ADR</th><th>出租率</th><th>RevPAR</th><th>房费（元）</th></tr></thead>"
            "<tbody><tr><td>2026/07/01—2026/07/16</td><td>148.23 / 156.25</td><td>93.95% / 86.09%</td><td>139.27 / 134.52</td><td>69,076.50 / 66,719.96</td></tr></tbody>"
            "</table></section></div></body></html>"
        )

        rendered = enable_performance_table_scroll(html)

        self.assertIn("<div class='performance-detail-scroll-v55'>", rendered)
        self.assertIn("overflow-x:auto", rendered)
        self.assertIn("min-width:940px!important", rendered)
        self.assertIn("position:sticky", rendered)
        self.assertIn("房费（元）", rendered)
        self.assertIn("69,076.50 / 66,719.96", rendered)

    def test_chart_is_stacked_above_full_width_detail_table(self):
        rendered = enable_performance_table_scroll(
            "<html><head></head><body>"
            "<div class='performance-trend-layout-v54'>"
            "<section class='performance-chart-v54'></section>"
            "<section class='performance-detail-v54'>"
            "<table class='performance-detail-table-v54'></table>"
            "</section></div></body></html>"
        )

        self.assertIn("grid-template-columns:minmax(0,1fr)!important", rendered)
        self.assertIn("grid-auto-rows:auto!important", rendered)
        self.assertIn("gap:16px!important", rendered)
        self.assertIn("align-items:start!important", rendered)
        self.assertIn("width:100%", rendered)
        self.assertIn("height:auto!important", rendered)
        self.assertNotIn("height:600px!important", rendered)
        self.assertNotIn("grid-template-columns:minmax(520px", rendered)

    def test_chart_keeps_compact_height_and_table_rows_stay_compact(self):
        rendered = enable_performance_table_scroll(
            "<html><head></head><body>"
            "<div class='performance-trend-layout-v54'>"
            "<section class='performance-chart-v54'></section>"
            "<section class='performance-detail-v54'>"
            "<table class='performance-detail-table-v54'></table>"
            "</section></div></body></html>"
        )

        self.assertIn("height:360px!important", rendered)
        self.assertIn("min-height:360px!important", rendered)
        self.assertIn("height:82px!important", rendered)
        self.assertIn("height:92px!important", rendered)
        self.assertIn("padding:12px 9px!important", rendered)
        self.assertIn("width:100%!important", rendered)

    def test_rewrite_is_idempotent(self):
        html = (
            "<html><head></head><body>"
            "<table class='performance-detail-table-v54'><tbody><tr><td>日期</td></tr></tbody></table>"
            "</body></html>"
        )
        once = enable_performance_table_scroll(html)
        twice = enable_performance_table_scroll(once)
        self.assertEqual(
            twice.count("<div class='performance-detail-scroll-v55'>"),
            1,
        )
        self.assertEqual(twice.count("PERFORMANCE_TABLE_SCROLL_V59"), 1)


if __name__ == "__main__":
    unittest.main()
