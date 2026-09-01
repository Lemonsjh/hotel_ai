## Why

部分 algorithm rules 和中性 loader 仍引用顶层旧 contract 路径；市场整体状态未完整反映事件/热度缺口；经验候选可复制敏感 summary。飞书进度测试还依赖当前时钟前的固定小时数量。

## What Changes

- 将 active runtime reference 收敛到 `contracts/v27/`，显式 legacy 路径保持历史说明。
- 使 market context、experience candidate 和进度自然语言测试遵守真实 freshness、敏感值与时间边界。
- 修正文档里的旧 `contextInjection=always` 和市场配置安全边界。

## Capabilities

### New Capabilities
- `v27-runtime-reference-integrity`: V27 active reference、市场降级和经验候选安全一致性。
- `time-aware-feishu-route-tests`: 时间过滤路由的确定性测试契约。

### Modified Capabilities
- None.

## Impact

影响 contract loader、algorithm rules、market source、experience store、进度测试、`.gitignore`、配置示例和部署文档；不改 V27 字段 ID 或算法公式。
