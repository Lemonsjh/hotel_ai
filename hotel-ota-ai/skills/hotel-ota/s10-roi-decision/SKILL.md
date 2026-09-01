---
name: s10-roi-decision
description: "S10 ROI 决策：分析推广投入、订单收益、RevPAR 和边际回报，生成投放取舍建议。触发语：ROI、投产比、推广值不值、广告效果。"
---

# S10 ROI 决策


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户询问推广值不值、投产比是否合格、广告预算怎么控、是否继续投放时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`

## 核心职责

- 计算推广花费、归因订单、收入、ADR、RevPAR、边际 ROI。
- 美团推广余额、推广消耗、活动标签属于 P2 参考字段；缺失时不得影响 P0/P1。
- 区分流量问题和转化问题。
- 建议继续、降低、暂停或调整投放时段。
- 为 S8 和 S11 提供决策依据。

## 执行流程

1. 收集推广花费、订单、房费收入、佣金假设。
2. 在数据允许时估算扣除平台成本后的净收益。
3. 与历史 ROI 和目标 ROI 对比。
4. 数据不足时输出数据采集任务，不做伪精确判断。

## 输出要求

返回 ROI 摘要、置信度、投放决策、还缺哪些数据。

## 安全规则

- 不直接执行推广动作。
- ROI 数据口径不一致时必须说明。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N013.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 推广 ROI 决策 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py promotion-roi --hotel-id <hotel_id>
```

Allowed runtime commands: `promotion-roi`, `promotion-plan`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

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

- User says "算一下推广 ROI": route to `roi_decision` and run `promotion-roi`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
