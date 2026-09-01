# S8 推广通数据展示 runtime 命令

## 正式入口

```bash
python runtime/hotel_ota_runtime.py promotion-plan --hotel-id <hotel_id>
```

`promotion-plan` 为历史保留的命令名；当前只有一个业务能力：读取并展示推广通数据，不生成推广计划。

## 数据读取规则

- 触发命令后才读取数据库。
- 唯一业务表为 `meituan_ota_promotion_performance_30d`。
- 必须按 `hotel_id` 精确过滤。
- 默认读取该酒店最新 `snapshot_time` 对应的完整快照。
- 如由可信运行上下文注入 `as_of_time`，读取不晚于该时点的最新快照。
- 不使用 demo、sample、manual upload、RPA、其他平台数据或其他 Skill 输出补齐。

## 输出规则

- 只返回推广通原始字段和同一记录的确定性派生展示指标。
- `recommendations=[]`。
- `actions=[]`。
- `approval_required=false`。
- `write_performed=false`。
- `live_allowed=false`。
- 不展示或推断推广开通、运行、暂停状态。

## Skill 隔离规则

S8 不调用、不依赖、不编排任何其他 Skill，也不承担其他 Skill 的建议、规划、审批、任务或执行职责。

其他推广相关命令或能力不属于 S8；不得通过兼容别名把它们重定向到 S8 展示链路。
