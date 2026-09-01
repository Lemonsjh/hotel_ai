## Design

新增主项目迁出结果 helper：

- `status=blocked`
- `intent=third_party_report_preview` 或 `s14_source_request`
- `blocked_reason=s14_ext_migrated_to_independent_service`
- `summary=第三方营销诊断已迁移到独立服务，本项目不再处理该入口。`
- `business_result_generated=False`
- `runtime_command=None`

路由层：

- 保留自然语言识别，避免落到菜单或其它错误意图。
- 一旦识别为第三方营销诊断相关 intent，立即返回迁出提示。
- 不 import、不调用 `build_s14_ext_third_party_preview()`、`diagnose_s14_ext_excel_file()`、`diagnose_s14_ext_mysql_template_result()`。

CLI 层：

- `s14-ext-diagnosis` 保留为 deprecated shell，返回同样迁出提示。
- 不再解析 Excel/MySQL 数据生成报告。

## Non-Goals

- 不删除 `runtime/s14_ext_third_party_diagnosis.py` 文件。
- 不实现独立服务。
- 不改当前酒店 S14 `s14-diagnosis`。

## Verification

- `openspec validate migrate-s14-ext-out-of-main-project --strict`
- 飞书路由测试：相关消息返回迁出提示，不生成业务结果。
- CLI 测试：`s14-ext-diagnosis` 返回迁出提示。
- grep 确认主飞书路由不再 import `runtime.s14_ext_third_party_diagnosis`。
