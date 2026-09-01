# S4 环境行情感知 规则

## 核心输入字段
- `business_date`
- `calendar_context`
- `weather_context`
- `event_context`
- `competitor_context`
- `operating_context`
- `progress_context`
- `demand_signal`

## 判断逻辑
1. 先读取业务日历，识别周末、调休上班、法定节假日、节前节后和业务建议。
2. 再读取天气归一化结果，天气只作为风险和需求修正项。
3. 再叠加活动候选、S7 竞品聚合信号、S2 今日经营和 S16 当前进度。
4. 只有业务日历确认、天气可用、S2/S16 均为今日 fresh 时，才允许给 S5 输出行情增强信号。
5. 只有日历、只有天气或缺少今日经营/进度时，返回 `data_gap` 或保守诊断，不触发正式调价。

## 可配置参数
- 天气 provider 必须区分：`weather_mcp` 表示真实 OpenClaw MCP 工具，`wttr_http` 表示直接访问 wttr.in，`weather_fixture` 表示本地样例，`manual_weather` 表示人工录入。
- 未注册 MCP server 时，不得声称天气 MCP 已接入。
- 节假日和调休以 runtime 业务日历为准，不在 skill 内临时解析网页。
- 活动和竞品为候选信号，必须带置信度和来源质量。

## 异常处理
- 缺关键字段时先追问或降级为 sample/manual/RPA，不让 skill 失败退出。
- 低质量字段只能用于诊断、提示和 dry-run，不得用于真实执行。
- 天气源超时、缺字段或返回原文时，由 runtime 转为统一 `weather_context` 后再解释。
- 调休上班日即使是周六日，也不得按普通周末高需求判断。

## 指标口径（曝光/转化，务必标清）
- 美团指标里 `曝光量`(次) 与 `曝光人数`(人) 口径不同。展示曝光时**优先 `曝光量`，缺失才 fallback `曝光人数`**，并**必须标单位**（次/人）。runtime 已透出 `exposure`、`exposure_unit`、`exposure_metric_name`，按 `exposure_unit` 标注，不得把"人数"当"量"展示。
- 支付转化率必须标口径：runtime 透出 `payment_conversion_rate_basis`（`view_to_payment` 浏览→支付 / `exposure_to_payment` 曝光→支付）。展示转化率时说明是哪个口径，不得与"同行平均"混口径对比；`peer_average` 缺失或口径不明时不硬给对比结论。

## 大盘热度、区域环境信号与需求指数口径
- `market_heat_ratio` / 大盘热度只能消费 S16 的统一市场结果，不在 S4 内重新计算。
- S16 盘中口径为“预计全天大盘订单 ÷ 历史完整日大盘订单基线”；完整日口径为“完整日大盘订单 ÷ 历史完整日基线”。
- `regional_heat_context.regional_heat_index` 是区域环境信号。仅有 `event_heat` 一个可用维度时，必须展示为“周边事件单项分”，不得称为大盘热度、市场热度或综合需求指数。
- S16 大盘热度不可用时，S4 必须返回 `market_heat_calculation_status=unavailable` 和明确原因；禁止使用周边活动分或 partial 区域热度回退。
- `demand_index` 只有在其规定输入维度满足时才允许输出；缺失时返回 `data_gap`，禁止把周边事件分或区域 partial 分数当作 `demand_index`。
- 飞书输出必须分别展示“大盘热度”“周边事件/区域环境信号”“环境需求指数”，不得混用名称或数值。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- MCP/API 原始返回、活动搜索原文和竞品原始表不得外发飞书。
- S4 只输出行情信号，不能绕过 S5/S6、fresh 数据、dry-run 和审批。

## V27 可施工算法规格

# 算法来源

- 对应节点：N006 / S4 环境行情感知
- 对应 Agent：A1
- 对应 BP：P1
- 对应源文件：`references/source/source_manifest.yaml`
- 对应字段契约：`contracts/node_io_contract.yaml`
- 对应 runtime algorithm_rules：`runtime/algorithm_rules/demand_rules.yaml`

# 输入字段

## hard_required
缺失则阻断：hotel_id, data_business_date

## soft_required
缺失可继续但必须输出 data_gap：holiday_signal, weather_signal, event_signal, historical_same_period

## optional
增强判断，不阻断主链路：none

## candidate
候选字段，不稳定，不用于 live：none

## blocked_for_live
可用于诊断或 dry-run，不得用于正式执行：demo_data, sample_data, stale, missing_date

# 算法步骤

1. Normalize date environment, regional heat, historical same-period, booking progress, current traffic, current conversion, and room-type inventory signals.
2. Score demand_index with `formula_version=revised_first_formula_v27`: date_environment 20%, regional_heat 15%, historical_same_period 15%, booking_progress 20%, current_traffic 10%, current_conversion 10%, room_type_inventory_pressure 10%.
3. Apply traffic peak-valley calibration, then classify demand_level into weak/normal/strong.
4. Emit missing signal list rather than inventing market facts.

# 判断规则

阈值与分级来自 `runtime/algorithm_rules/demand_rules.yaml`：`{"weak_below": 40, "strong_at_or_above": 70, "surge_at_or_above": 85}`。
冲突处理顺序：DataGate > freshness > approval/live guard > price/budget guard > skill-specific threshold。

# 降级规则

- When hard-required fields are missing, return missing_fields and confidence=low.
- When input is demo/sample/stale, return preview_only or dry_run and block formal approval/live.
- When source capability is read-only/manual, produce recommendation or task only.

# 输出结构

- confirmed outputs：demand_index, demand_level, missing_fields
- candidate outputs：action_strength

# forbidden_actions / 禁止事项

- treat_demo_data_as_real_today_data
- create_formal_approval_from_demo_or_stale_data
- bypass_data_gate_or_approval_guard
- event_heat_score_as_market_heat
- regional_heat_partial_as_market_heat
- event_heat_score_as_demand_index

# 测试样例

- 正常样例：见 `references/v20_behavior_cases.json` 的 normal/preview case。
- 缺字段样例：见 `references/v20_behavior_cases.json` 的 missing_hard_required case。
- demo/sample/stale 阻断样例：见 `references/v20_behavior_cases.json` 的 demo_preview case。
