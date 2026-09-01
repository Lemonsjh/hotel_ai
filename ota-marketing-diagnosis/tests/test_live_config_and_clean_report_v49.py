from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v13 import _latest_configuration_rows
from marketing_diagnosis.reporting_v35 import _clean_customer_html


class LiveConfigurationTests(unittest.TestCase):
    def test_each_configuration_keeps_its_own_latest_row(self):
        rows = [
            {
                "id": 1,
                "promotion_name": "优美乐",
                "status": "CLOSED",
                "snapshot_time": "2026-07-16 09:00:00",
            },
            {
                "id": 2,
                "promotion_name": "优美乐",
                "status": "OPEN",
                "snapshot_time": "2026-07-16 12:00:00",
            },
            {
                "id": 3,
                "promotion_name": "商旅专享价",
                "status": "OPEN",
                "snapshot_time": "2026-07-16 10:00:00",
            },
            {
                "id": 4,
                "promotion_name": "钟点房",
                "status": "CLOSED",
                "updated_at": "2026-07-16 13:00:00",
            },
        ]

        latest = _latest_configuration_rows(rows)
        by_name = {row["promotion_name"]: row for row in latest}

        self.assertEqual(len(latest), 3)
        self.assertEqual(by_name["优美乐"]["status"], "OPEN")
        self.assertEqual(by_name["商旅专享价"]["status"], "OPEN")
        self.assertEqual(by_name["钟点房"]["status"], "CLOSED")


class CleanCustomerReportTests(unittest.TestCase):
    def test_removes_summary_source_notes_and_audit_panels(self):
        html = """
        <html><head></head><body>
          <article id='rule-1'>
            <div class='performance-v25-summary'>
              <div><small>本月值</small><strong>100</strong></div>
              <div><small>取数状态</small><strong>完整</strong></div>
            </div>
            <table class='performance-table-v28'><tr><td>客房数</td></tr></table>
            <p class='performance-v28-caption'>category=总营业指标</p>
          </article>
          <article id='rule-9'>
            <div class='promotion-metric-v34'><small>ROI</small><strong>7.54</strong><span>booking_order_amount ÷ spend_amount</span></div>
            <div class='field-standard-note'>数据库来源：promotion</div>
            <details class='output-fields-panel metric-details'><summary>查看全部诊断指标</summary><div>字段明细</div></details>
          </article>
          <article id='rule-13'>
            <div class='reputation-metric-v32'><small>昨日新增点评数</small><strong>5</strong><span>DATE(review_time)=昨日</span></div>
          </article>
        </body></html>
        """

        cleaned = _clean_customer_html(html)

        self.assertNotIn("performance-v25-summary", cleaned)
        self.assertNotIn("本月值", cleaned)
        self.assertIn("performance-table-v28", cleaned)
        self.assertIn("客房数", cleaned)
        self.assertNotIn("category=总营业指标", cleaned)
        self.assertNotIn("field-standard-note", cleaned)
        self.assertNotIn("查看全部诊断指标", cleaned)
        self.assertNotIn("booking_order_amount ÷ spend_amount", cleaned)
        self.assertNotIn("DATE(review_time)=昨日", cleaned)
        self.assertIn("7.54", cleaned)
        self.assertIn("昨日新增点评数", cleaned)
        self.assertIn(">5<", cleaned)


if __name__ == "__main__":
    unittest.main()
