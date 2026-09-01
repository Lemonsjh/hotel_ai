# S14 综合运营诊断规则

## 权威标准

本规则以项目权威 MD 的 `S14 综合运营诊断` 章节为准。S14 是确定性诊断编排层，不是第二套经营算法。

## 唯一允许的数据源

S14 只能消费以下能力已经生成的 versioned result：

- S2：当前经营、承诺已售、库存和可售状态。
- S4：市场、日历、天气、事件和需求背景。
- S7：竞态、竞争圈、价格位置、商品与 canonical 映射质量。
- S8：活动、权益、推广计划、人工清单和内容入口。
- S9：曝光、浏览、一转、二转及竞争圈对比。
- S10：推广效果、成本、收益、ROI 观察窗口和归因限制。
- S12：评分、趋势、主题、未回复和紧急风险。
- S15：基准 owner，只提供全店/房型销售节奏及市场、流量、转化、价格等基准，以及基准成熟度、样本和观察窗口。
- S16：偏差/诊断 owner，只提供基于 S15 基准形成的全店/房型进度偏差、gap、偏差原因、紧急度和下游方向。
- S17：订单、客源和已抑制客户聚合。

S14 不得直接读取或接受：

- Excel、CSV、截图、人工表格或 RPA 原始结果；
- `operation_diagnosis`、`daily_metrics`、`order_snapshot`、`price_snapshot` 等数据库模板；
- OTA/PMS 业务表；
- sample、demo、synthetic 或 hardcoded 指标；
- 其他酒店、其他平台、其他目标日或旧合同结果。

第三方 Excel/临时库诊断属于已经迁出的 S14-EXT，不得重新接回主 S14。

## S15 / S16 职责唯一来源

S14 必须按“数据角色”消费 S15 与 S16，禁止把二者当作同一指标的并列候选来源。

| 数据角色 | 唯一 owner | S14 允许消费的内容 |
|---|---|---|
| 当前经营事实 | 对应领域 capability | 销售当前值优先 S2；流量/转化当前值优先 S9；价格当前值优先 S7；其他字段按正式领域合同取值 |
| 基准 | S15 | `baseline`、基准曲线、样本/成熟度、基准观察窗口和基准质量 |
| 偏差与诊断 | S16 | `progress_status`、`gap/deviation`、`deviation_reasons`、`urgency`、下游方向 |

强制规则：

1. S15 只作为基准 owner，不作为当日 actual、偏差或诊断结论的展示来源。
2. S16 只作为偏差/诊断 owner。即使 S16 payload 为追溯携带了 actual 或 baseline 副本，这些字段也不得成为 S14 的业务展示来源或 fallback。
3. S14 不允许在 S15 与 S16 之间按“最新值”“非空值”“更高置信度”自动选值，也不允许平均、拼接、覆盖或合并两套同名字段。
4. 非 owner 重复字段只允许用于内部一致性校验；若与 owner 值不一致，生成 `execution_data_quality` 冲突并阻断受影响轴，但业务输出不得并排展示两套值。
5. S14 不得自行计算 `actual - baseline`、`gap`、完成率或偏差方向来替代 S16。S16 缺失/blocked 时，即使 S14 同时拿到了 actual 与 S15 baseline，也必须把对应偏差字段置为缺口。
6. S16 固定依赖 S15。S15 缺失、冲突、过期或 blocked 时，S16 的偏差结果不得被当作独立可信结论。
7. 当前领域 capability 没有正式提供某个 actual 字段时，S14 返回 `data_gap`；不得用 S15/S16 中的副本补 current actual。

因此 S14 的职责链固定为：

```text
领域事实 capability -> S15 基准 -> S16 偏差/诊断 -> S14 编排展示
```

而不是：

```text
S15 值 <-> S16 值 -> S14 二选一/合并/重算
```

## 请求身份

一次诊断固定：

```text
organization_id
hotel_id
target_business_date
as_of_datetime
contract_revision
policy_revision
```

每个 capability result 至少携带：

```text
capability_id,result_id,result_version,status
organization_id,hotel_id,target_business_date,as_of_datetime
effective_window,captured_at,source_grain,source_units
deterministic_payload,evidence_refs,quality_flags
contract_revision,policy_revision
```

对齐规则：

1. organization、exact hotel 和目标营业日必须一致。
2. `captured_at <= request.as_of_datetime`。
3. result 的 as-of 不得晚于请求 as-of。
4. 合同和策略 revision 必须相同，或显式列入兼容 revision。
5. 不同能力可以有不同 `effective_window` 和抓取时点，不要求相同 `snapshot_time`。
6. 同一 capability 出现多个 result 时返回冲突，不自动挑选。
7. 缺失能力仅降级其关联模块，并生成 `missing_input` item。
8. S15/S16 的同名字段不得绕过“职责唯一来源”规则成为并列展示来源。

## 固定八模块

| module_id | 权重 | capability 来源 |
|---|---:|---|
| `operating_revenue` | 20 | S2 当前事实 + S15 基准 + S16 偏差/诊断 |
| `traffic_competition` | 15 | S4/S7/S9 |
| `conversion_orders` | 15 | S9/S17 |
| `price_inventory` | 15 | S2/S7 |
| `promotion_roi` | 10 | S8/S10 |
| `content_entry` | 10 | S7/S8 |
| `reputation_service` | 8 | S12 |
| `execution_data_quality` | 7 | 全部结果 |

权重只用于展示综合风险，不能覆盖单项事实、动作规则或权限。

## 确定性 item

上游 capability 可在 `deterministic_payload.diagnostic_items` 中提供确定性 item。S14只做字段规范化、身份校验、稳定 ID、排序和根因聚合，不重算上游指标。

稳定 ID 输入：

```text
hotel_id
target_business_date
module_id
issue_code
scope
sorted(evidence_refs)
```

输出必须包含：

```text
item_id,module_id,issue_code,issue_type,severity,status,confidence
impact,evidence_refs,conflicts,missing_inputs,next_checks
eligible_handoff,forbidden_conclusions,direct_execution_allowed
blocked_by,root_cause_cluster_id
```

`direct_execution_allowed` 永远为 `false`。缺少量化证据时 `impact.value=null`。

## 冲突传播

身份不一致、未来快照、版本不兼容、重复 capability、canonical 房型缺失、单位冲突和轴数据冲突优先形成 `execution_data_quality` item。

S16 固定依赖 S15。S15 缺失、冲突、过期或 blocked 时，S16 item 保留，但必须带：

```text
blocked_by=<S15 上游问题 item_id>
```

不得把“基线缺口”包装成“销售严重落后”。

当 S15/S16 对同一基准或当前值携带了不同副本时，S14 只保留 owner 值用于业务投影；非 owner 值只进入内部冲突证据。不得通过重新计算产生“第三个值”来消除冲突。

## 七轴与三层投影

第一层固定七轴：

```text
sales_progress
market_orders
market_share
browse_users
first_conversion
second_conversion
price
```

七轴必须按角色取值：`actual` 来自对应领域 capability，`baseline` 来自 S15，`delta/gap/status/reason` 在该轴存在 S16 正式输出时来自 S16。S14 不得补算缺失的 `delta`、`gap`、完成率或金额，也不得用 S15/S16 的重复字段互相回退。某角色缺失时该字段保持空并标记 `data_gap`；owner 之间不一致时标记 `conflict`，但不并排展示多套业务值。

第二层只保留：

- 已达到异常阈值的 canonical `room_type_id`；
- 或存在 conflict/data_gap/stale 的 canonical `room_type_id`。

缺少 canonical `room_type_id` 时不得把酒店均值摊给房型。

第三层只保留上游已有 `product_facts`，以及请求中已经存在的 S5/S6/S8/S13 handoff。S14不得生成商品候选或任务。

## 风险、覆盖率和排序

```text
critical=100
high=75
medium=50
low=25
info=0

item_risk = severity_points * confidence
coverage_score = SUM(observed_module_weight) / 100
observed_risk_score = SUM(module_weight*module_risk) / SUM(observed_module_weight)
observed_health_score = 100-observed_risk_score
```

默认最低覆盖率：

```text
diagnosis-default.v1:min_score_coverage=0.80
```

低于阈值时 `observed_health_score=not_computable`，但已有事实和核查建议继续展示。

排序固定为：

```text
severity -> status/issue_type -> module -> issue_code -> item_id
```

飞书首屏只展示前5项，完整结果保存全部 item。

## handoff

只允许已经存在的：

- S5：收益/价格建议；
- S6：当前价格和直接调价候选；
- S8：推广计划和人工清单；
- S13：评论草稿。

handoff 必须同时匹配 capability、hotel、scope、target date 和 candidate hash。S14不创建任务、不申请确认、不审批、不写任务表、不调用 OTA/Provider。

## AI边界

AI只能解释已经存在的 item 和 handoff。AI不得新增异常、修改数字、排序、严重度、健康分、冲突状态、价格、预算或执行动作。AI失败不影响确定性输出。

## 旧入口处理

以下主 S14 路径已经废止，并必须返回 `data_gap`：

```text
Excel direct source
MySQL operation_diagnosis payload
database-query --template operation_diagnosis
sample/manual/RPA fallback
```

阻断码：

```text
s14_direct_source_removed_use_versioned_capability_results
```
