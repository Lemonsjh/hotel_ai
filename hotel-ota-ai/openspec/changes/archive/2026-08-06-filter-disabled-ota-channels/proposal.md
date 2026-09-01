## Why

生产酒店可以在 `hotels.config_json.channels` 中关闭某个 OTA 渠道，但当前分析读取层仍按固定 `ctrip + meituan` 表组合查询，导致关闭携程后仍出现携程诊断、排名和指标结论。渠道开关必须在读取真实 OTA 数据前生效，避免下游评分、报告和飞书展示继续使用已关闭渠道。

## What Changes

- 增加统一启用渠道解析：优先读取 `hotels.config_json.channels`，并归一到 canonical 渠道键 `meituan` / `ctrip`。
- 在 MySQL V4 OTA 模板读取层过滤禁用渠道对应的表 key。
- 保留显式 `source_platform` 查询语义：请求已禁用渠道时返回空结果和风险标记，不回退到其他渠道。
- 仅影响读/分析/展示数据入口，不改变调价任务写入和审批逻辑。

## Capabilities

### New Capabilities
- `ota-channel-read-gate`: OTA 分析读取必须遵守酒店启用渠道。

### Modified Capabilities
- None.

## Impact

影响 `runtime/adapters/database.py` 的 OTA 读模板和相关测试。下游 S14、S4/S9、竞争/促销等通过 `database_template_result("ota_*")` 读取的结果会自然继承过滤结果。
