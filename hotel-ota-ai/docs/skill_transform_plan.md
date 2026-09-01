# Skill Transform Plan

目标：在当前生产 mapping 能力边界内，先通过 `direct -> derived -> external -> estimated -> hidden` 最大化满足 Skill；无法安全定位租户、房型、商品或日期的数据必须降级为 `data_gap`、`schema_drift`、`mapping_pending` 或 `preview_only`，避免把字段缺失包装成可执行结论。

共享 transform 层由 `runtime/derived_contexts.py` 承载，当前上下文包括：

- `operating_snapshot_context`
- `progress_context`
- `price_context`
- `ota_health_context`
- `promotion_context`
- `promotion_roi_context`
- `reputation_context`
- `customer_order_context`
- `competitor_context`
- `sales_baseline_context`

| Skill | Needed Capability | Direct Fields | Derived Transform | External Bridge | Commercial Output | Status |
|---|---|---|---|---|---|---|
| S1 顶层配置 | env/config/auth 状态 | env-check、SQLite auth | readiness_stage、safe env status | 无 | 只显示可用/不可用 | direct |
| S2 经营运行快照 | 经营总览、房型房态、流量转化、市场竞态、价格与引流、推广活动状态 | PMS forecast 为必选核心；OTA metrics/price/competition/loss/activity 为并行只读视图 | 承诺销售与物理在住分离；纵表按 metric_code/unit；竞态只保留可比等级 | 无 | 六视图只读快照；不判断根因、不生成收益动作 | derived |
| S3 消息中台 | 飞书菜单/消息 | runtime router | output_profile + gate | 无 | 菜单和操作结果 | direct |
| S4 行情感知 | 日历、天气、活动、热度 | calendar seed | operating 参与需求判断 | weather/event bridge | 活动为空时隐藏 | external |
| S5 收益决策 | 商品级真实只读候选 | 必需：PMS forecast、OTA 商品价格映射、价格护栏；可选增强：S15 基准、同日流量、同行聚合/流失背景 | 精确 `hotel_id+channel+ota_product_id+stay_date`；S15 缺失仅降低候选强度；默认护栏仅预览；无精确竞品价不得跟价 | 仅确定性计算 | 候选及 S6 dry-run 资格；不写任务 | derived |
| S6 房价同步执行 | dry-run/task candidate | OTA price mapping、price task | product/task handoff | 无 | dry-run only | derived |
| S7 竞态监控 | 本店商品、同行聚合、美团竞争圈与月度流失背景、活动/权益/评分 | OTA price mapping、business metrics、competition 30d、Ctrip/Meituan `order_loss_monthly`、activity/right/ranking；竞争圈仅用 Meituan 表 | 四级可比：exact_product / peer_aggregate / loss_context / own_only；竞争圈按 `competitor_circle_name` 聚合，订单数只取竞店行字段 | 精确竞品商品集合缺失时禁止构造房型价差；不读取或展示美团订单观察、携程订单动态，携程月度流失背景仅在已有映射和数据时作为 `loss_context` | 飞书直读真实数据；不创建价格或推广任务 | derived |
| S8 推广通展示 | 近30天推广通数据 | only `meituan_ota_promotion_performance_30d`, exact `hotel_id`, latest `snapshot_time` on trigger | 仅确定性展示指标；除零返回 `not_computable`；不推断推广状态 | 无 | 只展示推广通数据；`recommendations=[]`、`actions=[]`，不规划、不审批、不执行 | derived |
| S9 流量峰谷 | 流量/转化漏斗 | OTA metric_name/value | 已有层级即输出 | event/weather 仅增强 | 不补造缺层级 | derived |
| S10 ROI 决策 | ROI | revenue/price/activity | 无成本时 estimated_roi | 无 | 保守测算参考 | estimated |
| S11 推广建议书 | 确定性只读 PromotionPlan | 不直接读取业务表；消费对齐后的 S8/S9/S10/S16 确定性结果及用户当前建议意图 | 解析建议动作、对象范围、预算/出价人工建议、观察指标、停止条件与风险；对象歧义时 `clarification_required` | 无 | 仅输出 `PromotionPlan`；不调用 AI、不审批、不建任务、不派发、不执行、不写状态 | derived |
| S12 口碑管理 | 评分/差评/未回复 | review overview/ranking | dimension/ranking summary | 无 | 口碑摘要 | direct |
| S13 评论回复 | 单条评论回复 | 当前无 review_text | review strategy only | 无 | 回复策略，不显示自动发布 | hidden_optional_module |
| S14 酒店运营诊断 | 综合诊断 | Excel/MySQL 23-table | M01-M08/覆盖率；23 表派生 operation_diagnosis，周边活动表只作为 partial event context | S14 source registry | 结论、风险、建议 | derived |
| S15 销售基准线 | 日目标/基准 | JY01/JY03/RS01 | 同周期/历史日级 baseline | 日历 | 无真实小时曲线时输出 `fallback_ratio_curve`，只作进度参考，不得称为真实历史曲线或执行依据 | derived |
| S16 进度偏差 | 当前进度 vs 目标 | JY01/JD01/RS01 | 无目标只输出当前事实 | 无 | 有目标才输出偏差 | derived |
| S17 客户订单分析 | 客源/房型/价类聚合 | JD01/JD04/RS01 | 聚合分布 | 无 | 聚合，隐私脱敏 | derived |
