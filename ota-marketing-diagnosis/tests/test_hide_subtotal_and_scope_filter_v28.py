from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v22 import (
    _remove_item_one_subtotal,
    _remove_scope_selector,
)


class HideSubtotalAndScopeFilterTest(unittest.TestCase):
    def test_removes_only_item_one_subtotal_row(self) -> None:
        html = """
        <article class='diagnosis-card' id='rule-1'>
          <table><tbody>
            <tr><td><span class='field-name'>房费</span></td><td>5540</td></tr>
            <tr><td><span class='field-name'>小计</span></td><td>60447.04</td></tr>
            <tr><td><span class='field-name'>平均房价</span></td><td>145.79</td></tr>
          </tbody></table>
        </article>
        <article class='diagnosis-card' id='rule-2'>
          <table><tbody><tr><td><span class='field-name'>小计</span></td></tr></tbody></table>
        </article>
        """
        cleaned = _remove_item_one_subtotal(html)
        item_one = cleaned.split("id='rule-2'", 1)[0]
        self.assertNotIn(">小计<", item_one)
        self.assertIn(">房费<", item_one)
        self.assertIn(">平均房价<", item_one)
        self.assertIn(">小计<", cleaned.split("id='rule-2'", 1)[1])

    def test_removes_selector_but_keeps_export_button(self) -> None:
        html = """
        <div class='top-actions'>
          <select class='scope-select'><option>综合诊断</option></select>
          <button class='btn primary'>导出报告</button>
        </div>
        """
        cleaned = _remove_scope_selector(html)
        self.assertNotIn("scope-select", cleaned)
        self.assertNotIn("综合诊断", cleaned)
        self.assertIn("导出报告", cleaned)


if __name__ == "__main__":
    unittest.main()
