## Context

`runtime.decisions.demand.sample_snapshot()` 是本地演示用样例快照，包含固定市场订单、HOS、OTA 健康分和需求指数。生产 Feishu 业务路径必须禁止这些值作为真实业务证据输出。

## Design

采用小步防护：

1. 保留 demo fixture，但把语义改成显式 demo/local：例如 `_demo_sample_snapshot()`。
2. 提供生产安全结果 helper，在生产上下文缺真实字段时返回：
   - `status=data_gap`
   - `source_status=data_gap`
   - 业务数字字段为 `None`
   - `risk_flags` 标明缺失真实数据
3. 对仍需 demo fixture 的本地 CLI / demo 测试路径继续显式调用 demo helper。
4. 对生产可达的 Feishu decision 路径增加测试，确保 JSON 输出中没有样例业务数字和 `sample_data` / `demo_data` 证据标记。

## Non-Goals

- 不删除本地 demo 数据生成能力。
- 不改变真实 MySQL 查询逻辑。
- 不一次性重构所有 S2/S5/S14/S16 数据口径。

## Verification

- `openspec validate guard-production-sample-snapshot --strict`
- 生产 sample guard 相关单元测试
- 相关 runtime/feishu 测试子集
- grep 检查样例数字只保留在 demo/test 或 guarded 路径中
