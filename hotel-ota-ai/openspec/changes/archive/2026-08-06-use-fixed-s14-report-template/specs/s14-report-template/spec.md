## ADDED Requirements

### Requirement: Fixed S14 Report Artifact

S14 本地报告生成 MUST 使用固定报告文件名 `ota_diagnosis_report.html` 和固定 `report_id` `ota_diagnosis_report`。

#### Scenario: Report directory configured

- **WHEN** 调用 S14 诊断并传入 `report_dir`
- **THEN** runtime MUST 写入 `<report_dir>/ota_diagnosis_report.html`
- **AND** `report_id` MUST 等于 `ota_diagnosis_report`
- **AND** 如果 `HOTEL_OTA_S14_REPORT_BASE_URL` 已配置，`report_url` MUST 指向该固定文件名

### Requirement: Template-Aligned S14 HTML

S14 报告 HTML MUST 参考示例模板的报告结构展示现有聚合诊断数据，且不得使用示例中的静态演示业务事实替代当前计算结果。

#### Scenario: HTML generated from aggregate diagnosis result

- **WHEN** S14 生成 HTML 报告
- **THEN** 报告 MUST 包含 `overview`、`modules`、`risks`、`missing`、`tasks` 区块
- **AND** 模块得分 MUST 来自当前 `module_scores`
- **AND** 风险、缺失字段和建议动作 MUST 来自当前诊断结果
- **AND** 报告 MUST NOT 包含 DSN、本地私有路径、token、`open_id` 或示例模板里的固定演示渠道事实

### Requirement: Legacy S14 Artifact Cleanup

S14 报告清理 MUST 仅删除过期的遗留 `s14-*.html` 产物，不得删除无关 HTML 文件。

#### Scenario: Expired legacy report and unrelated file exist

- **WHEN** 报告目录中存在过期 `s14-*.html` 和无关 `*.html`
- **THEN** 清理过程 MAY 删除过期 `s14-*.html`
- **AND** MUST 保留无关 HTML 文件
- **AND** 新报告 MUST 通过覆盖固定 `ota_diagnosis_report.html` 更新
