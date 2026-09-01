## Design

`identity` intent 保留现有 auth context 解析，不接触 PMS/MySQL 经营模板。

渲染输出固定包含：

- 鉴权状态
- 当前角色
- 当前群绑定酒店
- 鉴权来源
- “本指令只检查身份和群绑定，不读取 PMS/MySQL 经营数据”
- “如需确认真实数据源，请发送‘当前数据源’或‘实时房态’”

不再输出：

- `demo_data`
- `sample_data`
- `demo/dry-run/production_locked`
- 正式审批/live 是否可用
- MySQL 是否启用

内部 `live_allowed=false` 等安全字段可以保留给机器判断，但普通飞书文本不展示这些作为身份结论。
