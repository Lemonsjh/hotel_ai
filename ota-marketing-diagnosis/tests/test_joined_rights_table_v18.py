from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v15 import _rights_content


class JoinedRightsTableTest(unittest.TestCase):
    def test_all_five_rights_are_rendered_without_truncation(self):
        item = {
            "fields": [
                {"label": "已报名权益数量", "value": 5},
                {"label": "延迟退房", "value": "全部房型生效"},
                {"label": "会员积分抵房费", "value": "全部房型生效"},
                {"label": "无忧取消", "value": "全部房型生效"},
                {"label": "住就送", "value": "部分房型生效"},
                {"label": "早餐赠送", "value": "全部房型生效"},
            ]
        }

        html = _rights_content(item)

        self.assertIn("已报名权益数量", html)
        self.assertIn("<strong>5</strong>", html)
        for name in (
            "延迟退房",
            "会员积分抵房费",
            "无忧取消",
            "住就送",
            "早餐赠送",
        ):
            self.assertIn(name, html)
        self.assertEqual(html.count("<tbody><tr>") + html.count("</tr><tr>"), 5)
        self.assertIn("有效房型范围", html)
        self.assertIn("当前共展示 5 项权益明细", html)

    def test_empty_rights_show_explicit_empty_row(self):
        html = _rights_content(
            {"fields": [{"label": "已报名权益数量", "value": 0}]}
        )
        self.assertIn("暂无已报名权益明细", html)
        self.assertIn("当前共展示 0 项权益明细", html)


if __name__ == "__main__":
    unittest.main()
