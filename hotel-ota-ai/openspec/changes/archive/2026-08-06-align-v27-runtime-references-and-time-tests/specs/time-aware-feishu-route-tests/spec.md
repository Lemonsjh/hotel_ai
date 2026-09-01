## ADDED Requirements

### Requirement: 确定性进度测试
飞书进度路由测试 MUST 注入或显式声明 `as_of_time`，且不得依赖执行机器当前时间或固定未来小时点数量。

#### Scenario: 下午检查点
- **WHEN** 测试使用 `as_of_time=16:40`
- **THEN** runtime 仅返回不晚于 16:40 的小时累计值

### Requirement: 防未来数据泄漏
测试 MUST 验证任何 `actual_hourly_sales` 和目标点均不晚于请求检查时间。

#### Scenario: 未来快照存在
- **WHEN** fixture 包含 22:00 数据且请求检查时间为 18:20
- **THEN** 18:20 结果不得使用 22:00 累计值
