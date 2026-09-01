# 设计

## 方案

在 `runtime/s14_operation_diagnosis.py` 内收敛报告生成边界：

1. 定义固定 `report_id` 与文件名：
   - `report_id = "ota_diagnosis_report"`
   - `filename = "ota_diagnosis_report.html"`
2. `_write_local_report()` 每次覆盖同名报告文件，并按 `HOTEL_OTA_S14_REPORT_BASE_URL` 生成稳定 URL。
3. `_render_s14_report_html()` 改为接近示例模板的结构：
   - 顶部 header 和操作按钮。
   - 左侧/顶部导航。
   - `overview`、`modules`、`risks`、`missing`、`tasks` 区块。
   - 使用当前 `diagnose_s14_canonical_facts()` 已计算出的 `module_scores`、`cap_rules`、`risk_flags`、`missing_fields`、`action_suggestions`。
4. 旧 `s14-*.html` 只作为历史遗留产物清理；新固定文件通过覆盖更新，不需要随机文件回收。

## 风险

- 示例模板包含大量演示渠道、趋势和房型静态数据，不能直接复制为生产事实。
- 固定文件名意味着同一目录下只保留最新报告；这是用户期望的稳定引用方式，但不适合历史报告归档。
- 如果飞书入口仍期待随机 `s14-*.html`，需要同步修改入口配置；本仓库测试会以固定文件名作为新契约。

## 验证

- `openspec validate use-fixed-s14-report-template --strict`
- `python -m unittest tests.runtime.test_s14_dual_source_adapter tests.s14.test_s14_report_url`
- `python -m unittest discover -s tests/runtime`
- `git diff --check`
