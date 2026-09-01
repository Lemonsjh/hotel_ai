---
name: s07-competitive-monitoring
description: "S7 竞态监控：监控竞品价格、房态、活动、评分、排名和商圈订单变化。触发语：竞品、竞争圈、对手价格、竞态、排名变化。"
---

# S7 竞态监控


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户询问竞品、竞争圈、对手价格、商圈排名、订单流失、竞品活动和评分变化时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`

## 核心职责

- 监控配置中的核心竞品和商圈同行。
- 对比价格、剩余房、活动标签、评分、排名、订单动量。
- 识别竞品突然降价、需求上涨或排名异常。
- 为 S5、S8、S9 提供竞态信号。

## 执行流程

1. 从 S1 读取竞品配置。
2. 优先使用 API 或合规采集数据；没有数据时可解析用户上传截图，并说明置信度。
3. 判断竞态状态：`advantaged`、`neutral`、`pressured`、`unknown`。
4. 给出跟价、稳价、优化内容、调整推广等建议。

## 输出要求

返回竞品表、变化项、置信度、建议联动的下游 skill。

## 安全规则

- 不得编造竞品价格。
- 不直接执行调价，只给 S5 提供信号。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N007.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 竞对监控 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py competition-alert --hotel-id <hotel_id>
```

Allowed runtime commands: `competition-alert`, `market-context`, `database-query`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

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
- 本 skill 只按 runtime 证据输出结论，不扩展到未授权动作。

### 常见用户说法和处理方式

- User says "看一下竞对价格": route to `competitive_monitoring` and run `competition-alert`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
