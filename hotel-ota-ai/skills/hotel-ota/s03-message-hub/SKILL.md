---
name: s03-message-hub
description: "S3 消息中台服务：把各 skill 输出转换为飞书通知、日报、预警、审批卡片和任务消息。触发语：发送通知、生成飞书消息、审批卡片、日报、预警。"
---

# S3 消息中台服务


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户要求发送通知、格式化飞书消息、生成审批卡片、整理日报/预警、给前台下发任务时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`
- `{baseDir}/../_shared/operating-policy.md`
- `{baseDir}/../_shared/prompts/output-template.md`
- `{baseDir}/../../../requirements/飞书输出规范.md`
- `templates/production/*.md`
- `templates/development/*.md`

## 核心职责

- 将各 skill 的结构化输出改写成适合飞书私信或群聊的中文消息。
- 将调价、房量、推广、评论回复等敏感动作转成审批消息。
- 按角色路由：老板看审批和关键经营结论，运营看诊断和任务，前台看执行任务。
- 对定时任务消息去重，避免无意义刷屏。
- 回复中不暴露密钥、签名、密码、验证码。

## 消息类型

- `daily_report`
- `warning`
- `approval_request`
- `execution_result`
- `frontdesk_task`
- `diagnosis_report`

## 执行流程

1. 读取上游 skill 输出。
2. 判断接收对象、优先级、是否需要立即发送。
3. 生成飞书可直接发送的中文正文。
4. 涉及真实执行时，必须标记 `approval_required: true`。
5. 长报告先给摘要，必要时附上 artifact 路径。
6. 生产飞书消息必须先走 runtime `feishu-output-gate` 语义；命中导出、内部参数或越权写操作时使用拒绝模板。

## 输出要求

返回消息正文、接收角色、优先级、是否立即发送、是否需要审批。

## 安全规则

- 群聊消息默认要求 @ 机器人触发。
- 审批消息必须包含 `approval_id`、动作、房型/渠道/日期、原值/建议值、数据新鲜度、dry-run 摘要、风险和审批人。
- 生产消息只输出脱敏摘要、诊断结论、证据日期、风险、建议动作和审批状态；不贴完整 runtime JSON、源码、配置、数据库原始表或 API 请求体。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N018.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 飞书消息中枢 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py feishu-output-gate --hotel-id <hotel_id>
```

Allowed runtime commands: `feishu-output-gate`, `feishu-route`, `approval-create`, `command-menu-start`, `command-menu-reply`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

### 数据来源要求
runtime CLI and controlled database-query only.

### 生产环境禁止事项和 data_gap 规则

- 生产 Feishu 必须使用 verified role；需要时由 HOTEL_OTA_REQUIRE_VERIFIED_ROLE 强制
- 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API
- demo/sample/synthetic/hardcoded 数据不得用于 production Feishu 业务结论
- 缺少必要数据必须返回 data_gap，不得编造成 0 或继续给正式结论
- 禁用渠道不得参与读取、分析和展示
- agent 不得自己编造 runtime 没有返回的结论。

### 飞书输出规则

- 生产飞书输出必须遵守 feishu-output-gate 语义
- 不得输出 DSN、token、服务器私有路径、原始订单行、payload_hash 或内部 request payload；no private path

### 写操作和审批规则

- runtime 未返回 write_performed=true、affected_rows>0、config_change_applied=true 或 audit_id 时，不得声称已执行、已删除、已写入或已配置
- dry_run_first and approval_required before any write or external execution.

### 常见用户说法和处理方式

- User says "打开菜单": route to `message_hub` and run `feishu-output-gate`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
