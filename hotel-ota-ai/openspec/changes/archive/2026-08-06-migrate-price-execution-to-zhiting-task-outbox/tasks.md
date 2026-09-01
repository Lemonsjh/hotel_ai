## 1. OpenSpec 与字段事实源

- [x] 1.1 阅读 `数据库数据字段说明_详细版.md`，确认 20 张表、任务表字段、商品映射字段和 `business_date` 语义。
- [x] 1.2 创建独立 OpenSpec change，覆盖 zhiting task outbox。
- [x] 1.3 `openspec validate migrate-price-execution-to-zhiting-task-outbox --strict` 通过。

## 2. TDD 红灯测试

- [x] 2.1 增加任务表 schema 和字段文档测试。
- [x] 2.2 增加 `execute_status`、`business_date`、商品展开、去重和写入开关测试。
- [x] 2.3 增加 direct API deprecated、env-check 和根上下文旧口径测试。
- [x] 2.4 增加会话 ID 标准化和会话绑定状态渲染测试。

## 3. Outbox 实现

- [x] 3.1 新增 zhiting price task outbox 模块，提供 `write_zhiting_price_tasks()`、`read_price_task_status()`。
- [x] 3.2 扩展 SQLite schema 模拟 MySQL 映射表/任务表，并提供 additive migration SQL 文档。
- [x] 3.3 S6 `execute-price` 支持 `--channel-source`、`--business-date`、写入开关和 outbox dry-run/commit。
- [x] 3.4 旧 direct API path 默认 blocked：`direct_api_execution_deprecated_use_price_task_outbox`。

## 4. Runtime 与 Feishu 收敛

- [x] 4.1 env-check 输出 `price_task_outbox_status` 和 deprecated direct API 状态。
- [x] 4.2 S6 输出明确“任务已写入/等待插件执行”，不得声称 OTA 已调价成功。
- [x] 4.3 根上下文文件同步任务表 outbox、SQLite Active Auth、BIND/ROLE/CFG、会话 ID 标准化和旧 API deprecated 口径。

## 5. 验证

- [x] 5.1 运行相关单测。
- [x] 5.2 运行 OpenSpec validate、V27 contract/drift、compileall、全量 unittest、Node 插件测试、`git diff --check`。
