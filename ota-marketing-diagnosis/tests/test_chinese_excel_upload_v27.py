from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from marketing_diagnosis.data_v3 import normalize_dataset
from marketing_diagnosis.excel_loader_v2 import load_excel_package
from marketing_diagnosis.reporting_v21 import build_html
from marketing_diagnosis.rules_v3 import process


class ChineseExcelUploadTest(unittest.TestCase):
    def _workbook(self, path: Path) -> None:
        wb = Workbook()
        wb.remove(wb.active)

        def add(name: str, headers: list[str], rows: list[list[object]]) -> None:
            ws = wb.create_sheet(name)
            ws.append([name])
            ws.append(["中文表头上传测试"])
            ws.append(headers)
            for row in rows:
                ws.append(row)

        add(
            "00_基本信息",
            ["是否导入", "酒店ID", "酒店名称", "诊断渠道", "诊断开始日期", "诊断结束日期"],
            [["是", "puyue", "璞悦·奢电竞酒店(贵阳花溪公园店)", "多渠道", "2026-06-16", "2026-07-15"]],
        )
        add(
            "04_流量指标",
            ["是否导入", "酒店ID", "业务日期", "平台", "统计周期类型", "指标名称", "指标值", "同行均值", "同行排名", "快照时间"],
            [
                ["是", "puyue", "2026-07-14", "美团", "日", "曝光人数", 2611, 1377, "5/20", "2026-07-14 18:00:00"],
                ["是", "puyue", "2026-07-14", "美团", "日", "浏览人数", 300, 150, "4/20", "2026-07-14 18:00:00"],
                ["是", "puyue", "2026-07-14", "美团", "日", "支付订单数", 30, 15, "3/20", "2026-07-14 18:00:00"],
                ["是", "puyue", "2026-07-14", "美团", "日", "HOS分", 5.6, None, "2/20", "2026-07-14 18:00:00"],
                ["是", "puyue", "2026-07-14", "美团", "日", "信息分", 107, None, None, "2026-07-14 18:00:00"],
            ],
        )
        add(
            "06_扫码订单",
            ["是否导入", "酒店ID", "扫码时间", "订单ID", "扫码订单数量"],
            [["是", "puyue", "2026-07-14 10:00:00", "A001", None], ["是", "puyue", "2026-07-14 11:00:00", "A002", None]],
        )
        add(
            "07_推广财务",
            ["是否导入", "酒店ID", "交易时间", "交易类型", "交易金额", "快照时间"],
            [["是", "puyue", "2026-07-08 00:00:00-23:59:59", "推⼴通⽀出", -100, "2026-07-15 12:00:00"], ["是", "puyue", "2026-07-07 00:00:00-23:59:59", "推广通支出", -100, "2026-07-15 12:00:00"]],
        )
        add(
            "08_渠道月收入",
            ["是否导入", "酒店ID", "统计月份", "维度类型", "维度名称", "房费收入", "快照时间"],
            [["是", "puyue", "2026-07", "渠道", "美团EBK", 53358.04, "2026-07-15 12:00:00"]],
        )
        add(
            "12_权益中心",
            ["是否导入", "酒店ID", "酒店名称", "权益名称", "有效房型范围", "快照时间"],
            [["是", "puyue", "璞悦·奢电竞酒店(贵阳花溪公园店)", "延迟退房", "全部房型生效", "2026-07-15 12:00:00"]],
        )
        add(
            "15_人工录入",
            ["是否导入", "酒店ID", "挂冠类型", "录入人", "录入时间"],
            [["是", "puyue", "黑金挂冠", "测试人员", "2026-07-15 14:30:00"]],
        )
        wb.save(path)

    def test_chinese_excel_generates_complete_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s14.xlsx"
            self._workbook(path)
            raw, meta = load_excel_package(path)

            self.assertEqual(meta["hotel_id"], "puyue")
            self.assertEqual(raw["promotion_finance"][0]["transaction_amount"], 200.0)
            self.assertEqual(raw["ota_funnel"][-1]["scan_order_count"], 2.0)
            flow = next(row for row in raw["ota_funnel"] if row.get("period_type") == "日")
            self.assertEqual(flow["exposure_rank_raw"], "5/20")

            normalized = normalize_dataset(raw)
            normalized["hotel_name"] = meta["hotel_name"]
            result = process(normalized)
            enriched = {
                **result,
                "hotel_id": meta["hotel_id"],
                "hotel_name": meta["hotel_name"],
                "platform": meta["platform"],
                "period_start": meta["period_start"],
                "period_end": meta["period_end"],
            }
            item22 = next(item for item in result["visual_diagnosis"]["items"] if item["standard_item_id"] == 22)
            self.assertEqual(item22["item_score"], 1.0)
            self.assertEqual(result["visual_diagnosis"]["manual_crown"]["crown_type"], "黑金挂冠")

            html = build_html(enriched)
            ids = {int(value) for value in re.findall(r"id=['\"]rule-(\d+)['\"]", html)}
            self.assertEqual(ids, set(range(1, 24)))
            self.assertIn("黑金挂冠", html)
            self.assertIn("5/20", html)


if __name__ == "__main__":
    unittest.main()
