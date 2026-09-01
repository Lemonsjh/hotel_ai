# SQL 变更管理

`runtime` 默认只读数据库。飞书 Agent、OpenClaw Agent 和普通业务命令不得直接执行 DDL，也不得自行运行 `CREATE VIEW`、`CREATE OR REPLACE VIEW`、`DROP VIEW`、`ALTER TABLE`、`GRANT` 或 `REVOKE`。

如果生产试运行确实需要保留或恢复 `v_openclaw_*` 视图，必须按以下流程处理：

1. 由人工 DBA 或服务器维护人从数据库导出 `SHOW CREATE VIEW` 结果。
2. 将 SQL 脱敏后提交为版本化 migration 草案，并标注 `manual_review_required`。
3. 审核表名、字段名、权限、影响范围和回滚方式。
4. 在维护窗口人工执行，不通过飞书消息或模型自动执行。

当前 active 开发映射优先使用 `config/database-source.example.json` 中的 `hotel_zhiting` 22 张源表。只有当私有 mapping profile 明确声明 `view_migration_version` 时，runtime 才应把 `v_openclaw_*` 视为已登记来源；否则必须提示 `view_migration_untracked` 风险。

不得在本目录提交真实 DSN、账号、密码、token、secret、私有主机名或客户原始数据。
