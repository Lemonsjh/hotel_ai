from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v10 import _config_group


def _item(no: int, name: str, status: str, enroll=None, effective=None, data_status="success", score=1.0, base=1.0):
    return {
        "standard_item_id": no,
        "item_name": name,
        "base_score": base,
        "item_score": score,
        "data_status": data_status,
        "source_table": "hotel_puyue.meituan_ota_promotion_status",
        "source_fields": ["promotion_name", "status", "enroll_status", "effective_status"],
        "fields": [
            {"label": "开通状态", "value": status},
            {"label": "报名状态", "value": enroll},
            {"label": "生效状态", "value": effective},
        ],
    }


class CompactConfigStatusTableTest(unittest.TestCase):
    def test_separate_headers_and_chinese_values(self):
        items = {
            15: _item(15, "优美会", "OPEN", "OPEN", "OPEN", base=3, score=3),
            16: _item(16, "商旅专享价", "OPEN", None, None, base=2, score=2),
            17: _item(17, "公益流量", "OPEN", "PENDING", "CLOSED", base=2, score=2),
            18: _item(18, "钟点房", "OPEN", None, None, base=4, score=4),
            19: _item(19, "酒店亮点", "CLOSED", None, None, "zero", 0, 2),
            20: _item(20, "预约开票", "PENDING", None, None, "pending_rule", None, 2),
            23: _item(23, "自动接单", "CLOSED", None, None, "zero", 0, 1),
        }

        html = _config_group(items)

        header = html.split("<thead><tr>", 1)[1].split("</tr></thead>", 1)[0]
        self.assertEqual(header.count("<th>"), 6)
        self.assertIn("<th>开通状态</th>", header)
        self.assertNotIn("报名状态", header)
        self.assertNotIn("生效状态", header)
        self.assertIn("已开通", html)
        self.assertIn("未开通", html)
        self.assertNotIn("暂无数据 / 暂无数据", html)
        self.assertNotIn("报名 / 生效状态", html)


if __name__ == "__main__":
    unittest.main()
