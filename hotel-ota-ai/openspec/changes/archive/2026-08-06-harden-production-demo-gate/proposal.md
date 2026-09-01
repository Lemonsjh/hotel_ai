## Why

生产飞书入口必须 fail closed。用户显式请求 `demo`、演示链路或指定 `*-demo` 酒店时，runtime 不能产出演示数据，也不能在缺少真实 `hotel_id` 时回退到 demo manifest 酒店。

## What Changes

- 固化生产飞书 demo gate 的验收规则。
- 明确 `production_feishu=True` 下显式 demo、demo hotel id 和 demo fallback intent 都必须阻断或返回真实数据 data_gap。
- 保留本地 CLI / 测试环境 demo 能力。

## Capabilities

### New Capabilities
- `production-demo-gate`: 生产飞书入口禁止 demo/sample/synthetic/static fixture 兜底。

### Modified Capabilities
- None.

## Impact

这是对现有 runtime 行为的 OpenSpec 固化和验收记录，不新增生产能力，不改变本地演示路径。
