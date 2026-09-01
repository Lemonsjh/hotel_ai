## Why

市场数据源必须可配置、可解释、可降级。现有 QWeather 和 verified HTTP 基础不能覆盖无密钥天气、搜索活动候选和私有 calendar seed 的统一规则。

## What Changes

- 新增 weather provider 优先级与统一规范化。
- 新增只作候选的活动搜索 provider。
- 维持私有 holiday/calendar seed 为节假日和调休事实源。

## Impact

影响 market sources、S4/S9/S5 的输入质量、配置 example 和测试；不允许搜索结果直接触发调价。
