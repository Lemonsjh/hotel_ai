## Decisions

- inspect 只允许受限元数据和最多五行脱敏样例。
- mapping profile 只在服务器私有配置中保存真实表和字段名；仓库只保留无敏感 example。
- 映射不完整时返回 `data_gap`、missing fields 和候选映射，业务节点不得填补字段。
