# 设计

## 数据源与映射

- MySQL profile 必须显式读取真实库已存在的 `room_type_id` 字段，包括 `kf11_room_status_snapshot`、`rs01_room_revenue_daily`、`meituan_ota_goods_price_mapping`、`ctrip_ota_goods_price_mapping`。
- `hotel_room_type_mapping` 是当前默认权威映射源，以真实结构为准，使用 `source_room_type_name` / `ota_room_type_name` / `source_product_id` / `room_type_id`。
- `v_hotel_room_type_mapping_result` 仅作为可选兼容视图，不作为默认查询依赖。
- normalizer 不得用失败的映射解析覆盖源表已有 `room_type_id`。源表字段为可信读路径身份，写路径仍由可信 mapping/match rule/approval/guard 控制。

## 实时出租率与诊断

- 实时出租率公式仍为 `jd01 booking_status=已入住 AND departure_time>as_of_time` + `jd01 booking_status=预订 AND DATE(arrival_time)=target_business_date` + `jd04 checkout_time>as_of_time`，分母为 `kf11 total_rooms - maintenance_rooms`。
- `target_business_date` 是 runtime 从请求当天或用户显式日期解析出的目标业务日期，不是 `jd01.business_date` 字段；`jd01` 无同名字段时必须使用 `arrival_time` 派生。
- `jd01` 分子必须按订单号去重后再汇总；同一 `order_id` / `order_no` / `reservation_no` 在同步明细中出现多行时，只能贡献一次对应 `room_count`。
- `jd01 booking_status=取消 AND DATE(arrival_time)=target_business_date` 必须作为今日预订扣减项；输出保留原始今日预订、取消扣减和有效今日预订，公式分子只使用有效今日预订。
- `kf11` 当前在住房只作为辅助房态事实输出，可展示 `kf11_occupied_rooms` 与公式分子的差异，但不得覆盖公式出租率。
- `deviation`、S5/S14 handoff 使用同一公式口径；是否阻断下游由目标/基准可信度等业务条件决定，不由 `kf11` 在住数差异单独阻断。
- S2 skill 文档、触发配置和 OpenClaw skill metadata 必须把“实时出租率 / 当前出租率”路由到 `feishu-route --production-feishu` 或 `expected-occupancy`，不得继续指导 agent 运行 `snapshot` 后读取 `jy01` 口径。

## 飞书生产行为

- 当前群角色查询只读当前 `chat_id/chat_id_hash`。
- owner 可以配置 owner；owner 仍不能改自己、admin 或跨酒店成员。
- 生产 Feishu 业务必须携带可信 `chat_id` 与发送人身份；缺少上下文时只能返回 `missing_required_feishu_auth_context` / `missing_trusted_business_chat_id`，不得把 agent 漏传鉴权参数误报为“群未绑定”。
- “查身份”不谈 demo/sample/MySQL 连通。
- “当前数据源”只报告当前实际启用配置，不报告废弃天气/节假日 key。
- `Agent:` / `Model:` / `Provider:` 页脚允许存在；raw `open_id`、连接串、密钥仍禁止。

## S14 / 商圈 / HOS

- 优先从真实业务指标表读取商圈、HOS、OTA 健康分等字段并标注来源。
- 无真实字段时返回 `data_gap`；不得用昨天整日替代上周同期，不得用 demo `170/107/5.74/58`。
- S14-EXT 从主 Feishu/CLI/demo registry 解耦，只保留迁移提示或外部独立入口。
