## Why

美团业务指标中可能同时存在 `曝光量` 和 `曝光人数`。当前模糊匹配 `曝光` 会把人数当次数展示，转化率也没有明确是浏览到支付还是曝光到支付，容易误导运营判断。

## What Changes

- OTA/S14 诊断指标读取时优先使用 `曝光量`。
- `曝光量` 缺失时 fallback 到 `曝光人数`，并标记单位为 `人`。
- 支付转化率输出补充口径字段，默认标记为 `view_to_payment`。
- 不改源表结构，不伪造同行均值。

## Capabilities

### New Capabilities
- `exposure-conversion-metric-basis`: 曝光与支付转化率必须带口径。

### Modified Capabilities
- None.

## Impact

影响 MySQL V4 诊断派生口径和 S14 相关测试；飞书/报告渲染可读取新增口径字段。
