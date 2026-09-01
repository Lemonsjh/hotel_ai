from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v10 import (
    _CONFIG_NUMBERS,
    _config_group,
    _display_number,
)
from marketing_diagnosis.reporting_v13 import _apply_customer_tail_order


class ConfigStatusOrderAndColumnsTest(unittest.TestCase):
    def _items(self):
        return {
            number: {
                "standard_item_id": number,
                "item_name": "自动接单" if number == 23 else f"配置{number}",
                "base_score": 1,
                "item_score": 1 if number != 20 else None,
                "participates_in_score": True,
                "data_status": "success" if number != 20 else "pending_rule",
                "fields": [
                    {"label": "开通状态", "value": "OPEN" if number != 20 else "PENDING"},
                    {"label": "报名状态", "value": "OPEN"},
                    {"label": "生效状态", "value": "OPEN"},
                ],
                "source_table": "hotel_puyue.meituan_ota_promotion_status",
                "source_fields": ["status"],
            }
            for number in reversed(_CONFIG_NUMBERS)
        }

    def test_config_table_keeps_auto_order_as_display_item_21(self):
        html = _config_group(self._items())
        positions = [html.index(f"id='rule-{number}'") for number in _CONFIG_NUMBERS]

        self.assertEqual(_CONFIG_NUMBERS, (15, 16, 17, 18, 19, 20, 23))
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(_display_number(23), 21)
        self.assertIn("15–21", html)
        self.assertIn("id='rule-23'", html)
        self.assertIn("<td class='config-rule-number'>21</td>", html)

    def test_registration_and_effective_columns_are_removed(self):
        html = _config_group(self._items())
        header = html.split("<thead><tr>", 1)[1].split("</tr></thead>", 1)[0]
        self.assertEqual(header.count("<th>"), 6)
        self.assertIn("<th>开通状态</th>", header)
        self.assertNotIn("报名状态", header)
        self.assertNotIn("生效状态", header)

    def test_customer_tail_order_is_auto_video_crown(self):
        source = (
            "<nav>"
            "<a href='#rule-21'><span>21</span>首页视频</a>"
            "<a href='#rule-22'><span>22</span>酒店挂冠</a>"
            "<a href='#rule-23'><span>23</span>自动接单</a>"
            "</nav>"
            "<section id='summary'><tbody>"
            "<tr data-status='success' data-title='首页视频'><td>21</td><td><a href='#rule-21'>首页视频</a></td></tr>"
            "<tr data-status='manual_pending' data-title='酒店挂冠'><td>22</td><td><a href='#rule-22'>酒店挂冠</a></td></tr>"
            "<tr data-status='zero' data-title='自动接单'><td>23</td><td><a href='#rule-23'>自动接单</a></td></tr>"
            "</tbody></section>"
            "<article class='diagnosis-card' id='rule-21'><div class='rule-no'>21</div>首页视频</article>"
            "<article class='diagnosis-card' id='rule-22'><div class='rule-no'>22</div>酒店挂冠</article>"
        )
        html = _apply_customer_tail_order(source)

        nav_auto = html.index("<span>21</span>自动接单")
        nav_video = html.index("<span>22</span>首页视频")
        nav_crown = html.index("<span>23</span>酒店挂冠")
        self.assertLess(nav_auto, nav_video)
        self.assertLess(nav_video, nav_crown)

        self.assertIn("id='rule-21'><div class='rule-no'>22</div>首页视频", html)
        self.assertIn("id='rule-22'><div class='rule-no'>23</div>酒店挂冠", html)

        summary_auto = html.index("<td>21</td><td><a href='#rule-23'>自动接单")
        summary_video = html.index("<td>22</td><td><a href='#rule-21'>首页视频")
        summary_crown = html.index("<td>23</td><td><a href='#rule-22'>酒店挂冠")
        self.assertLess(summary_auto, summary_video)
        self.assertLess(summary_video, summary_crown)


if __name__ == "__main__":
    unittest.main()
