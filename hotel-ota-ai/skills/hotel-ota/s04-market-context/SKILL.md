---
name: s04-market-context
description: "S4 环境行情感知：识别节假日、区域活动、天气、平台规则、商圈热度和行业事件对酒店需求的影响。触发语：节假日、周边活动、行情、市场热度、需求变化。"
---

# S4 环境行情感知


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户询问节假日、本地活动、市场需求、异常流量变化、调价背后的外部因素时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`

## 核心职责

- 判断日期类型：工作日、周末、节假日、节前、节后、活动日。
- 识别酒店周边活动、交通、天气、平台规则、美团/OTA 流量变化等需求因素。
- 使用统一字段中的曝光、浏览、支付转化、流量峰谷和订单进度计算需求指数。
- 给 S5 收益决策和 S15 销售基准线提供行情信号。
- 把行情结论翻译成可执行运营建议。

## 执行流程

1. 确认酒店位置和分析日期范围。
2. 按日期输出 `demand_index` 0-100 和 `low`、`flat`、`strong`、`burst` 需求等级。
3. 说明判断依据和置信度。
4. 如果没有可靠活动数据，明确说明缺口，并采用保守判断。
5. 给出对基准线、调价、推广的影响建议。

## 输出要求

返回日期、行情等级、证据、置信度、对价格/推广/基准线的建议影响。

## 安全规则

- 不编造活动和新闻。
- 不直接触发调价，只向 S5 提供行情信号。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N006.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 市场上下文 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py market-context --hotel-id <hotel_id>
```

Allowed runtime commands: `market-context`, `demand-index`, `event-discover`, `event-bridge-check`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

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

- User says "商圈今天怎么样": route to `market_context` and run `market-context`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
