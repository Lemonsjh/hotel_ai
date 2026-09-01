# S3 消息中台 规则

## 核心输入字段
- `message_type`
- `target_role`
- `priority`
- `approval_required`
- `actions`
- `risk_level`

## 判断逻辑
1. 老板看审批和经营结论
2. 运营看诊断和动作
3. 前台看执行清单
4. 敏感动作必须形成审批消息
5. 生产飞书回复优先套用 `templates/production/`；开发调试可套用 `templates/development/`
6. 命中源码、配置、原始数据、内部参数或生产调试请求时，使用 `export-refusal` 或 `debug-refusal`。
7. 命中模型/插件安装、审批绕过、订单明细外发、模型 provider 异常时，分别使用 `ops-refusal`、`approval-bypass-refusal`、`raw-order-refusal`、`model-provider-error`。
8. 普通业务回复按 `结论/数据/证据/风险/建议/审批` 6 段式输出，复杂结果先摘要，详细内容进入受控报表或 artifact。
9. 各 skill 的 runtime JSON 只能作为输入证据，不得在飞书生产回复中原样粘贴。
10. 一条消息同时包含多个敏感意图时，必须逐项说明处理结果；不能只拒绝其中一个风险点后忽略其他风险点。

## 角色权限判断
- `admin` 接收角色、安全、异常和所有高风险审批消息。
- `owner` 接收经营结论、风险、收益建议和待审批动作。
- `operator` 接收诊断证据、dry-run 任务、审批发起和跟踪结果。
- `frontdesk` 只接收具体执行清单、截图要求和反馈提醒。
- `guest` 只接收无权限提示，不发送经营数据、价格建议或审批卡片。

## 可配置参数
- 蓝图中未最终确认的阈值标记为 `configurable`。
- 多源资料冲突时输出 `needs_business_confirm`，并采用更保守建议。
- API 未确认时字段质量为 `manual_required` 或 `inferred`。

## 异常处理
- 缺关键字段时先追问或降级为 sample/manual/RPA，不让 skill 失败退出。
- 低质量字段只能用于诊断、提示和 dry-run，不得用于真实执行。
- 原始 API 状态码必须先由 runtime 转成统一枚举后再解释。
- 无 `approval_id` 的“同意/拒绝”只追问具体审批编号，不执行、不改文件、不关联其他话题。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- 必须记录请求摘要、响应码、失败原因和人工处理建议。
- 生产飞书禁止发送配置包、env、auth profile、角色表、数据库映射、OpenClaw 主配置、源码 zip、CSV、XLSX、JSON 原始数据和完整 runtime JSON。
- 生产飞书禁止展示代码片段、真实 `open_id/chat_id`、DSN、API 请求体、字段映射全量内容或密钥。
- 飞书业务 Agent 不创建、修改或删除项目文件，不修改角色表、数据库映射、环境变量或源码。
- 飞书业务 Agent 不要求用户在聊天里发送 `OrgId`、`ChannelKey`、API Secret、DSN 或 token；只提示通过 SSH/运维流程写入服务器私有环境文件。
- 飞书业务 Agent 不下载、安装或部署模型、插件、应用、二进制工具，也不得承诺已经安装。
- 飞书业务 Agent 不执行或声称执行 `git stash`、回滚、清理工作区、重启服务或修改服务器文件。
- 飞书业务 Agent 不使用 `bypass`、绕过、强制审批等方式处理调价、推广、房量或评论发布；聊天里的手动数据不得作为正式审批数据源。
- 飞书业务 Agent 不展示行级订单明细；订单相关回复只允许聚合摘要、证据日期、新鲜度、风险和建议动作。
- 模型 provider 的 billing/quota/API key 异常必须按模型服务异常解释，不得误判为美团、PMS、数据库或 OTA 数据源异常。

## V27 可施工算法规格

# 算法来源

- 对应节点：N018 / S3 消息中台
- 对应 Agent：A5
- 对应 BP：P0
- 对应源文件：`references/source/source_manifest.yaml`
- 对应字段契约：`contracts/node_io_contract.yaml`
- 对应 runtime algorithm_rules：`runtime/algorithm_rules/message_templates_policy.yaml`

# 输入字段

## hard_required
缺失则阻断：template_id, recipient_role, payload_summary

## soft_required
缺失可继续但必须输出 data_gap：approval_id, data_source_type, freshness_status, html_report_preview

## optional
增强判断，不阻断主链路：none

## candidate
候选字段，不稳定，不用于 live：none

## blocked_for_live
可用于诊断或 dry-run，不得用于正式执行：demo_data, sample_data, stale, missing_date

# 算法步骤

1. Select production/development template by environment and content_kind.
2. Block raw order rows, private config, source bundles, runtime JSON dumps, and secret-like content.
3. Render demo/stale/sample disclosure when freshness_status is not fresh.
4. Return only role-appropriate summary fields and approval card previews.

# 判断规则

阈值与分级来自 `runtime/algorithm_rules/message_templates_policy.yaml`：`{"raw_order_rows_allowed": false, "private_config_export_allowed": false, "demo_disclosure_required": true}`。
冲突处理顺序：DataGate > freshness > approval/live guard > price/budget guard > skill-specific threshold。

# 降级规则

- When hard-required fields are missing, return missing_fields and confidence=low.
- When input is demo/sample/stale, return preview_only or dry_run and block formal approval/live.
- When source capability is read-only/manual, produce recommendation or task only.

# 输出结构

- confirmed outputs：rendered_message
- candidate outputs：blocked_reason, disclosure

# forbidden_actions / 禁止事项

- treat_demo_data_as_real_today_data
- create_formal_approval_from_demo_or_stale_data
- bypass_data_gate_or_approval_guard
- send_raw_order_rows
- send_private_config_or_runtime_json

# 测试样例

- 正常样例：见 `references/v20_behavior_cases.json` 的 normal/preview case。
- 缺字段样例：见 `references/v20_behavior_cases.json` 的 missing_hard_required case。
- demo/sample/stale 阻断样例：见 `references/v20_behavior_cases.json` 的 demo_preview case。
