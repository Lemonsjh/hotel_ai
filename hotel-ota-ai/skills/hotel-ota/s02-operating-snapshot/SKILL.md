---
name: s02-operating-snapshot
description: "S2 经营房态采集：采集 ADR、RevPAR、出租率、房态、库存、订单、渠道占比并生成实时经营快照。触发语：今天经营情况、实时房态、出租率、ADR、RevPAR。"
---

# S2 经营房态采集


## Reference 导航

执行本 skill 前先读取本目录 `references/` 五件套：

- `references/input_schema.json`：输入字段和字段质量。
- `references/output_schema.json`：统一输出结构。
- `references/rules.md`：多源依据、判断逻辑、异常和安全规则。
- `references/examples.md`：飞书话术、样例输入、runtime 输出和最终回复。
- `references/runtime_commands.md`：可调用的稳定脚本命令。

## 适用场景

当用户询问“今天经营情况”“实时房态”“出租率/ADR/RevPAR”“当前订单和库存”“定时经营快照”时，使用本 skill。

## 必须读取

- `{baseDir}/../_shared/common-contract.md`
- `{baseDir}/../_shared/channel-api-map.md`

## 数据来源

- 统一数据契约中的经营快照、价格快照、流量转化对象。
- 美团参考字段：HOS、房型可售状态、挂牌价、促销价、已售房量、可售房量、曝光、浏览、支付转化、订单量。
- Beyondh 参考字段：房型、房价、房态、订单、出租率。
- 订单来了参考字段：房型价格、房型库存、订单状态、房价/房态变更推送。
- API 未就绪时，使用 RPA、用户上传截图、Excel/CSV 或演示数据。

## 执行流程

1. 确定 `hotel_id`、营业日期和渠道范围。
2. 生产 Feishu 入口必须通过 `feishu-route --production-feishu` 携带可信 `chat_id` 和发送人身份。缺少可信上下文时停止，不得把鉴权缺失误报为群未绑定。
3. “实时出租率 / 当前出租率”必须走统一实时公式，不使用 `snapshot` 或 `jy01_hotel_statistics_daily.occupancy_rate` 作为实时出租率：

```bash
python runtime/hotel_ota_runtime.py feishu-route --message "实时出租率" --production-feishu --chat-id <trusted_chat_id> --open-id <trusted_sender_id>
python runtime/hotel_ota_runtime.py expected-occupancy --hotel-id <hotel_id> --date <target_business_date> --as-of-time <as_of_time>
```

4. 统一公式：`target_business_date` 是 runtime 从请求当天或用户显式日期解析出的目标业务日期，不是 `jd01.business_date` 字段；`jd01` 已入住且 `departure_time > as_of_time` + `jd01` 当日有效预订（`DATE(arrival_time)=target_business_date`，按订单号去重并扣除当日取消）+ `jd04` 续住且 `checkout_time > as_of_time`；分母为 `kf11` 总房减维修房。`kf11` 当前在住只展示房态事实和冲突提示，不参与分子。
5. 非生产本地演示或 API 未就绪时，才允许使用运行时样例，并必须标注 demo/sample：

```bash
python runtime/hotel_ota_runtime.py snapshot --hotel-id puyue
python runtime/hotel_ota_runtime.py normalize-sample --sample meituan-room-count
python runtime/hotel_ota_runtime.py normalize-sample --sample dindanll-inventory
```

6. 标准化核心指标：出租率、ADR、RevPAR、可售房、维修房、预抵、预离、OTA 占比。
7. 保存快照，并只把重要异常推送到飞书，避免重复刷屏。

## 输出要求

- 经营概览。
- 指标表：出租率、ADR、RevPAR、订单、库存、渠道占比。
- 风险项：低价、库存异常、确认率、评分、推广余额等。
- 数据时间和下一次采集时间。

## 安全规则

- 该 skill 只读取和汇总数据，不执行调价、改房量、改房态。
- 数据不完整时必须说明置信度，不得假装是实时真实数据。

## V27 架构绑定

- 本 skill 的节点/Agent/上下游/禁止动作以 `references/v27_alignment.json` 为准。
- 架构事实源只引用 `architecture/node_registry.json`、`architecture/edge_registry.json`、`architecture/scenario_chain_registry.json`。
- 字段事实源只引用 `contracts/field_registry.yaml` 和 `contracts/node_io_contract.yaml`，不要复制全量字段池。
- Demo 输入使用 `examples/demo_data/nodes/N005.json`；Demo 输出必须保留 `data_source_type=demo_data`、`approval_data_allowed=false`、`live_allowed=false`。
<!-- OpenClaw skill standardization supplement -->

## OpenClaw 标准化补充

### 业务问题
处理 经营快照 场景，只根据 runtime 证据输出结论。

### 允许输入
hotel_id, target_business_date, as_of_time, runtime context.

### 输出口径
runtime result, evidence, risk flags, data_gap, blocked_reason.

### 对应 runtime 命令

```bash
python runtime/hotel_ota_runtime.py feishu-route --message "实时出租率" --production-feishu --chat-id <trusted_chat_id> --open-id <trusted_sender_id>
python runtime/hotel_ota_runtime.py expected-occupancy --hotel-id <hotel_id> --date <target_business_date> --as-of-time <as_of_time>
```

Allowed runtime commands: `snapshot`, `database-query`, `expected-occupancy`. 只能调用 runtime 已暴露的受控命令；agent 不得自行执行 SQL、改文件或直接调用 OTA/PMS live API

### 数据来源要求
runtime CLI and controlled database-query only.

### 生产环境禁止事项和 data_gap 规则

- 生产 Feishu 必须使用 verified role；需要时由 HOTEL_OTA_REQUIRE_VERIFIED_ROLE 强制；缺少可信会话或发送人身份时返回 `missing_required_feishu_auth_context` / `missing_trusted_business_chat_id`，不得误报“群未绑定”
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

- User says "实时出租率": production Feishu route to S2 through `feishu-route --production-feishu`; local diagnosis may run `expected-occupancy`.
- `snapshot` is a historical/compatibility operating snapshot and MUST NOT be used to answer current realtime occupancy.
- If runtime returns `data_gap`, explain the missing evidence and next data requirement only.
- If verified role or permission is missing, return auth guidance before business output.
