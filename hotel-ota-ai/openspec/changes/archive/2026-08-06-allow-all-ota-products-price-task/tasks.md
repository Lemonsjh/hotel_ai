## 1. Red tests

- [x] 1.1 增加 `python -m runtime.cli --help` 有输出的回归测试。
- [x] 1.2 增加 `price_editable_flag=NULL` 不阻断 readiness 的回归测试。
- [x] 1.3 增加 `is_hour_room=1` 不阻断 readiness 的回归测试。

## 2. Implementation

- [x] 2.1 补齐 `runtime.cli` 模块入口。
- [x] 2.2 删除 `price_editable_flag` 强阻断。
- [x] 2.3 删除 `is_hour_room` 强阻断。
- [x] 2.4 删除 outbox 中额外的携程 `price_editable_flag` 强阻断。

## 3. Verification

- [x] 3.1 `openspec validate allow-all-ota-products-price-task --strict` 通过。
- [x] 3.2 相关 CLI / database / runtime 单测通过。
