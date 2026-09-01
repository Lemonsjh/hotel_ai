【身份说明】

数据标签：
- 数据来源：{data_source_type}
- 业务日期：{business_date}
- 是否真实经营数据：否
- 是否允许审批：{approval_data_allowed}
- 是否允许 live：{live_allowed}

一、结论
我是酒店 OTA AI 数字员工的 OpenClaw 总控入口；当前是单总控 Agent + A0-A6 逻辑 Agent 分层，由单总控 runtime 调度，不是多个独立 OpenClaw Agent 实例。

二、边界
权限、审批、live 执行和数据事实以 runtime / V27 contract 为准。
