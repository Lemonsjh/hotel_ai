## ADDED Requirements

### Requirement: runtime.cli 支持模块执行
系统 MUST 支持通过 `python -m runtime.cli` 执行 CLI。

#### Scenario: 查看帮助
- **WHEN** 执行 `python -m runtime.cli --help`
- **THEN** 进程退出码必须为 0
- **AND** 标准输出必须包含 CLI 帮助内容

#### Scenario: database-query 输出
- **WHEN** 执行 `python -m runtime.cli database-query --db-kind mysql --template operation_diagnosis --hotel-id <hotel_id> --date <date>`
- **THEN** CLI 必须调用 `database_query`
- **AND** 标准输出必须是 JSON 文本
