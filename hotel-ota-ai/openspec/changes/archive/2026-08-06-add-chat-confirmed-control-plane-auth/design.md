## Decisions

- SQLite 是日常 auth 的唯一事实源；JSON 仅用于人工 bootstrap 和 SQLite 故障时的 global-admin emergency read-only 路径。
- 插件不再从 JSON 直接授权；目标账号消息一律 claim 并交给 runtime。
- 所有配置变更先创建 sealed request；确认命令只携带 request ID，服务端校验已存 payload hash、TTL、actor 和 tenant scope。
- owner/global admin 可以确认自己本酒店 request；operator request 必须由 owner/global admin 确认。
