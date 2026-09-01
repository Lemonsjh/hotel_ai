---
name: s05-revenue-decision
description: "S5 智能收益决策：基于经营快照、房型历史成交基准、销售进度、流量转化和市场热度生成只读调价候选。触发语：需要调价吗、涨价、降价、收益建议、定价策略。"
---

# S5 智能收益决策

## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户询问“今天要不要调价”“涨多少/降多少”“收益怎么做”“哪些 OTA 商品需要调整”时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`
- `{baseDir}/../_shared/operating-policy.md`
- `{baseDir}/../_shared/channel-api-map.md`

## 输入依赖

- 请求范围：精确 `hotel_id`，可选 `channel`、`ota_product_id`，以及目标 `stay_date`；未指定商品时只枚举当前已观察商品，S6 前仍须指定商品和日期。
- 必选核心：PMS 房型库存与销售进度、OTA 商品价格映射、商品当前原卖价、商品可编辑状态。
- 强证据：S15 房型历史成交价格与精确小时证据、S16 销售进度和线性预计全天市场热度、同业务日流量与转化指标。
- 增强背景：S7 酒店级同行聚合或月度流失背景。没有精确竞品商品集合时，只能作为 `peer_aggregate` / `loss_context`，不能生成同商品跟价结论。
- S5 不读取价格上下限配置，也不将其作为候选门禁、目标价边界、质量标记或输出内容。

## 执行流程

1. 通过 `revenue_decision` 真实只读路由并行读取 PMS、商品、S15、S16、流量和竞态证据；不得解析其他技能的飞书文本。
2. 按 `channel + ota_product_id + target_stay_date` 计算候选，保留价格观察业务日和抓取时点。
3. 先校验商品映射、可编辑性和数据新鲜度；再基于库存、销售进度、房型历史成交价、流量转化及 S16 市场热度判断涨价、降价或维持。S15 小时证据只标注置信度，不参与涨价、降价或维持的门槛判断。
4. 候选价以商品当前原卖价为基数，使用 S5 算法幅度计算；单次绝对变动不得超过 10%。不得读取或引用任何配置底价、顶价或默认价格区间。
5. S15 全局小时网格覆盖和当前决策小时成熟度只输出为 `formal`、`limited` 或 `weak` 的证据强度；不得阻断、触发或改变 S5 的涨价、降价或维持结论。
6. S5 只输出候选，不直接执行。正式候选交给 S6 重新读取当前商品价、校验商品映射、执行契约和审批边界。

## 飞书回复结构

- 回复顺序保持“总览 → 逐商品解析 → 边界”。
- 总览简述目标日期、候选数量、S15 时间证据和 S16 大盘热度。
- 每个商品单独一段，至少说明当前价与候选价、核心房型证据，以及未形成正式调价的主要原因。
- 相同的市场或边界信息可以精简，不必机械重复；但不能只列商品名称和价格，也不能把不同商品的原因合并成一个结论。
- 沿用现有飞书长度和安全规则，不设置 S5 专属字符额度，也不要求逐字透传 runtime 文本。

## 输出要求

- 返回商品级当前原卖价、候选原卖价、变动幅度、房型证据、市场/流量证据、阻断原因和预计酒店收入。
- 预计酒店收入仅供运营查看，不参与调价写入或审批。
- 不输出配置价格上下限、默认价格区间、相关状态、相关质量标记或相关 blocker。
- 市场热度必须直接使用 S16 的最终结果；S5 不得自行重算。

## 安全规则

- 默认 `mode` 为 `dry_run`。
- 不得绕过 S6 直接执行任何渠道写接口。
- 生产缺少核心证据时返回 `data_gap` 或 `partial`，不得以 sample/manual 数据生成真实经营结论。
- 单次候选变动绝对值不得超过 10%；该限制来自 S5 算法，不来自外部价格配置。
- 商品不可售、不可编辑、映射不可信或数据不新鲜时，不得形成正式候选；时间证据不成熟只降低解释置信度。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N015.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。

<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题

处理收益调价建议场景，只根据 runtime 证据输出结论。

### 允许输入

`hotel_id`, `business_date`, `as_of_time`, runtime context.

### 输出口径

runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py revenue-decision --hotel-id <hotel_id>
```

Allowed runtime commands: `revenue-decision`, `expected-occupancy`, `baseline-price`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API。

### 数据来源要求

runtime CLI and controlled database-query only.

### 生产环境禁止事项和 data_gap 规则

- 生产 Feishu 必须使用 verified role；需要时由 `HOTEL_OTA_REQUIRE_VERIFIED_ROLE` 强制。
- 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API。
- demo/sample/synthetic/hardcoded 数据不得用于 production Feishu 业务结论。
- 缺少必要数据必须返回 `data_gap`，不得编造成 0 或继续给正式结论。
- 禁用渠道不得参与读取、分析和展示。
- agent 不得自己编造 runtime 没有返回的结论。

### 飞书输出规则

- 生产飞书输出必须遵守 `feishu-output-gate` 语义。
- 不得输出 DSN、token、服务器私有路径、原始订单行、payload hash 或内部 request payload。
- 不得输出任何价格上下限配置或将其解释为定价依据。
- 回复保持“总览 → 逐商品解析 → 边界”；每个商品单独说明当前价、候选价和主要原因，允许精简重复信息。

### 写操作和审批规则

- runtime 未返回 `write_performed=true`、`affected_rows>0`、`config_change_applied=true` 或 `audit_id` 时，不得声称已执行、已删除、已写入或已配置。
- S5 正式候选要求商品映射可信、商品可编辑、数据新鲜和方向业务证据成立；S15 时间证据仅作置信度标记，价格上下限配置不属于 S5 输入或门禁。

### 常见用户说法和处理方式

- User says "调价建议": route to `revenue_decision` and run `revenue-decision`.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output。
