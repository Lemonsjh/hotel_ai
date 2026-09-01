from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v39 import enable_performance_chart_tooltip


class PerformanceChartTooltipV60Tests(unittest.TestCase):
    def _html(self) -> str:
        return (
            "<html><head></head><body>"
            "<article class='performance-card-v54'>"
            "<section class='performance-chart-v54'>"
            "<select class='performance-select-v54'><option value='revenue'>房费</option></select>"
            "<svg class='performance-svg-v54' viewBox='0 0 720 370'></svg>"
            "<script type='application/json' class='performance-data-v54'>[]</script>"
            "</section></article></body></html>"
        )

    def test_injects_hover_tooltip_style_and_script(self):
        rendered = enable_performance_chart_tooltip(self._html())

        self.assertIn("PERFORMANCE_CHART_TOOLTIP_V60", rendered)
        self.assertIn("performance-hover-tooltip-v60", rendered)
        self.assertIn("performance-hover-line-v60", rendered)
        self.assertIn("svg.addEventListener('mousemove',show)", rendered)
        self.assertIn("svg.addEventListener('mouseleave',hide)", rendered)
        self.assertIn("select.addEventListener('change',hide)", rendered)

    def test_tooltip_contains_actual_current_previous_and_yoy_values(self):
        rendered = enable_performance_chart_tooltip(self._html())

        self.assertIn("本期数值", rendered)
        self.assertIn("去年同期", rendered)
        self.assertIn("YOY", rendered)
        self.assertIn("metricText(key,metric.current)", rendered)
        self.assertIn("metricText(key,metric.previous)", rendered)
        self.assertIn("yoyText(metric.yoy)", rendered)
        self.assertIn("period.current_range", rendered)
        self.assertIn("period.previous_range", rendered)

    def test_rewrite_is_idempotent(self):
        once = enable_performance_chart_tooltip(self._html())
        twice = enable_performance_chart_tooltip(once)

        self.assertEqual(twice.count("/* PERFORMANCE_CHART_TOOLTIP_V60 */"), 2)
        self.assertEqual(twice.count("performance-hover-tooltip-v60{\n"), 1)


if __name__ == "__main__":
    unittest.main()
