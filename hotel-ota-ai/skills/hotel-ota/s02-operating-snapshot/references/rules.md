# S2 经营房态采集 规则

## 核心输入字段
- `occupancy_rate`
- `adr`
- `revpar`
- `available_rooms`
- `sold_rooms`
- `remaining_rooms`
- `orders_today`
- `risk_flags`

## 判断逻辑
1. 按统一数据契约接收 PMS/OTA/API/RPA/人工上传
2. API 未确认时使用 sample_data/manual_upload
3. 输出经营快照和字段质量
4. 飞书经营快报必须优先使用 runtime 返回的 `business_summary` 固定结构：结论、数据日期、核心指标、风险、建议动作、审批状态
5. 只有 `freshness_status=fresh` 且 `today_label_allowed=true` 时，才允许称为“今日实时经营快报”
6. 混合今日房态、昨日经营指标、sample/hardcoded 指标时，必须改称“历史/演示复盘”或“今日房态摘要”，不得包装成正式今日经营结论

## 数据库来源
- 可读取 `database-query --template operating_snapshot` 作为历史/兼容经营快照补充来源，但不得把其中 `jy01_hotel_statistics_daily.occupancy_rate` 当当前实时出租率。
- 生产 Feishu 的“实时出租率 / 当前出租率”必须走 `feishu-route --production-feishu` 的 S2 route；本地诊断可直接运行 `expected-occupancy`。
- 数据库来源必须为 `adapter_vendor=database`、`source_capability=read_only`。
- MySQL 实时出租率分子必须来自 `jd01` 已入住且 `departure_time > as_of_time`、`jd01` 当日有效预订/取消（`DATE(arrival_time)=target_business_date`，按订单号去重并扣除当日取消）、`jd04` 续住且 `checkout_time > as_of_time`。
- `target_business_date` 是 runtime 从请求当天或用户显式日期解析出的目标业务日期，不是 `jd01.business_date` 字段；`jd01` 没有同名字段时必须使用 `arrival_time` 派生。
- MySQL 实时出租率分母必须来自 `kf11` 当前总房减维修房；`kf11` 当前在住只作为房态事实和冲突提示，不参与分子。
- `jy01_hotel_statistics_daily` / `rs01_room_revenue_daily` 只能作为 T+1 历史经营指标或历史基准，不得伪装成当前实时进度。
- 表名、字段名和房态别名以 `/etc/hotel-ota-ai/database-source.json` 为准，字段变化时改配置，不改 skill。
- 字段未映射前不得用于真实执行，只能用于诊断和 dry-run。

## 可配置参数
- 蓝图中未最终确认的阈值标记为 `configurable`。
- 多源资料冲突时输出 `needs_business_confirm`，并采用更保守建议。
- API 未确认时字段质量为 `manual_required` 或 `inferred`。

## 异常处理
- 缺关键字段时先追问或降级为 sample/manual/RPA，不让 skill 失败退出。
- 低质量字段只能用于诊断、提示和 dry-run，不得用于真实执行。
- 原始 API 状态码必须先由 runtime 转成统一枚举后再解释。
- 飞书回复不得展示 runtime 原始 JSON、字段映射、SQL、订单行级明细或开发态字段；复杂结果进入受控报表。

## 安全规则
- 真实调价、房量、推广、评论发布必须审批。
- 所有写动作默认 `dry_run=true`。
- 必须记录请求摘要、响应码、失败原因和人工处理建议。

## V27 可施工算法规格

# 算法来源

- 对应节点：N005 / S2 经营房态采集
- 对应 Agent：A1
- 对应 BP：P0
- 对应源文件：`references/source/source_manifest.yaml`
- 对应字段契约：`contracts/node_io_contract.yaml`
- 对应 runtime algorithm_rules：`runtime/algorithm_rules/operating_snapshot_rules.yaml`

# 输入字段

## hard_required
缺失则阻断：hotel_id, data_business_date, available_rooms, sold_rooms

## soft_required
缺失可继续但必须输出 data_gap：adr, revpar, room_revenue, price_snapshot, inventory_snapshot

## optional
增强判断，不阻断主链路：none

## candidate
候选字段，不稳定，不用于 live：none

## blocked_for_live
可用于诊断或 dry-run，不得用于正式执行：demo_data, sample_data, stale, missing_date

# 算法步骤

1. Load PMS/OTA/database/manual_upload fields through the unified source mapping.
2. Calculate realtime occupancy through the unified `jd01` checked-in + `jd01` effective same-day reservations by `DATE(arrival_time)=target_business_date` + `jd04` numerator over `kf11` total rooms minus maintenance denominator.
3. Calculate adr=room_revenue/sold_rooms and revpar=room_revenue/available_rooms when revenue exists.
4. Attach source metadata, freshness_status, field_quality, and DataGate result.

# 判断规则

阈值与分级来自 `runtime/algorithm_rules/operating_snapshot_rules.yaml`：`{"field_coverage_warn_below": 0.8, "missing_hard_required_blocks_conclusion": true}`。
冲突处理顺序：DataGate > freshness > approval/live guard > price/budget guard > skill-specific threshold。

# 降级规则

- When hard-required fields are missing, return missing_fields and confidence=low.
- When input is demo/sample/stale, return preview_only or dry_run and block formal approval/live.
- When source capability is read-only/manual, produce recommendation or task only.

# 输出结构

- confirmed outputs：operating_snapshot, inventory_snapshot, price_snapshot, source_coverage
- candidate outputs：none

# forbidden_actions / 禁止事项

- treat_demo_data_as_real_today_data
- create_formal_approval_from_demo_or_stale_data
- bypass_data_gate_or_approval_guard

# 测试样例

- 正常样例：见 `references/v20_behavior_cases.json` 的 normal/preview case。
- 缺字段样例：见 `references/v20_behavior_cases.json` 的 missing_hard_required case。
- demo/sample/stale 阻断样例：见 `references/v20_behavior_cases.json` 的 demo_preview case。
