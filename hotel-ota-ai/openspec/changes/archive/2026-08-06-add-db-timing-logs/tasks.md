## 1. Spec

- [x] 1.1 编写数据库耗时日志 OpenSpec。
- [x] 1.2 通过 `openspec validate add-db-timing-logs --strict`。

## 2. Tests

- [x] 2.1 增加默认关闭不写日志测试。
- [x] 2.2 增加开启后写 redacted JSONL 测试。

## 3. Implementation

- [x] 3.1 在 `database_template_result()` 统一记录模板级耗时。
- [x] 3.2 日志字段只包含模板、酒店、状态、耗时、行数、风险标记等安全摘要。
- [x] 3.3 默认关闭，通过 `HOTEL_OTA_DB_TIMING_LOG=1` 开启。

## 4. Verification

- [x] 4.1 运行 `tests.runtime.test_database_timing_log`。
- [x] 4.2 运行 OpenSpec validate 和 diff 检查。
