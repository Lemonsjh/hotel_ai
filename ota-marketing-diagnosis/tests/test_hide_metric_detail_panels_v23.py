from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v18 import _remove_metric_detail_panels


class HideMetricDetailPanelsTest(unittest.TestCase):
    def test_removes_all_metric_detail_expanders_only(self) -> None:
        html = """
        <article id='rule-1'>
          <div class='result-area'>结果1</div>
          <details class='output-fields-panel metric-details'>
            <summary>查看全部诊断指标</summary>
            <div>5项核心指标</div>
          </details>
        </article>
        <article id='rule-2'>
          <div class='result-area'>结果2</div>
          <details class="metric-details other-class">
            <summary>查看全部诊断指标</summary>
            <div>2项核心指标</div>
          </details>
        </article>
        <details class='other-details'><summary>保留内容</summary></details>
        """

        cleaned = _remove_metric_detail_panels(html)

        self.assertNotIn("查看全部诊断指标", cleaned)
        self.assertNotIn("5项核心指标", cleaned)
        self.assertNotIn("2项核心指标", cleaned)
        self.assertIn("结果1", cleaned)
        self.assertIn("结果2", cleaned)
        self.assertIn("保留内容", cleaned)


if __name__ == "__main__":
    unittest.main()
