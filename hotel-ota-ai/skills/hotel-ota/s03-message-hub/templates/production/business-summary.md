# 经营摘要模板

结论：{{summary}}
证据：营业日期 `{{data_business_date}}`，快照时间 `{{data_snapshot_time}}`，新鲜度 `{{freshness_status}}`。
风险：{{risk_level}}
核心指标：出租率 `{{occupancy_rate}}`，ADR `{{adr}}`，RevPAR `{{revpar}}`，可售 `{{available_rooms}}`，已售 `{{sold_rooms}}`。
建议动作：{{recommendations}}
审批状态：{{approval_status}}

规则：生产飞书只发上述摘要字段；详细数据进入受控报表，不在聊天里展开订单明细、源码、配置或 runtime 原始 JSON。
