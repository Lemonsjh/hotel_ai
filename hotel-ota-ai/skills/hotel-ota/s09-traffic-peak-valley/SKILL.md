---
name: s09-traffic-peak-valley
description: "S9 流量峰谷：识别预订流量高峰和低谷，推荐价格、推广和任务策略。触发语：流量高峰、流量低谷、几点推广、进单时段。"
---

# S9 流量峰谷


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户询问当前是否流量高峰、低谷时段、几点开推广、进单节奏是否正常时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`

## 核心职责

- 识别小时级流量和进单规律。
- 对比今日、上周同期、商圈大盘和美团/OTA 曝光、浏览、支付转化。
- 输出 `demand_index`，作为 S5、S8、S15、S16 的公共变量。
- 判断当前状态：高峰、低谷、上升、下降、异常。
- 给 S5 调价和 S8 推广提供时段信号。

## 执行流程

1. 读取最新 S2 快照和历史订单曲线。
2. 与同星期、同小时基准线对比。
3. 高峰期：建议稳价/小幅涨价，谨慎消耗推广预算。
4. 低谷期：优先修复转化，必要时小范围推广或价格测试。

## 输出要求

返回时段分析、`demand_index`、峰谷分类、证据、建议动作。

## 安全规则

- 不直接打开或关闭推广。
- 不直接执行价格变更。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N020.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 流量峰谷诊断 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py conversion-diagnosis --hotel-id <hotel_id>
```

Allowed runtime commands: `conversion-diagnosis`, `demand-index`, `market-context`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

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

- User says "为什么转化低": route to `traffic_peak_valley` and run `conversion-diagnosis`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
