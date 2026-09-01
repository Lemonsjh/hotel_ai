# S16 运行时权威知识索引

本文件是 S16 运行时 AI 分析的首要知识入口。必须同时读取以下三份规则：

1. [`S16_MEITUAN_DAILY_PROJECTION_AND_ADVISORY_RULES.md`](./S16_MEITUAN_DAILY_PROJECTION_AND_ADVISORY_RULES.md)
2. [`MEITUAN_ACTIVITY_NET_PRICE_RULES.md`](./MEITUAN_ACTIVITY_NET_PRICE_RULES.md)
3. [`S16_DYNAMIC_DIAGNOSIS_KNOWLEDGE.md`](./S16_DYNAMIC_DIAGNOSIS_KNOWLEDGE.md)

## 路由与回答边界

直接询问以下问题时，由 S5 收益决策负责：

- 需要调价吗；
- 今天要不要调价；
- 哪些房型或商品需要调价；
- 需要涨价还是降价；
- 给出调价建议或具体收益候选。

S16 只在用户询问经营偏差、销售落后原因、市场、份额、流量或转化问题时，把价格作为可能原因之一进行解释。

如果某个请求已经进入 S16，S16 必须先回答已经取得的销售进度、房型结构和原因事实。不得只回复：

> 这是 S5 范围，请改问 S5。

可以在回答完 S16 事实后说明：具体收益候选、目标价格和调价任务由 S5/S6 负责。不得要求用户重新改写问题后才提供已有诊断结果。

## 规则优先级

出现表述差异时，按以下顺序执行：

```text
本文件的路由与回答边界
> S16_MEITUAN_DAILY_PROJECTION_AND_ADVISORY_RULES.md
> MEITUAN_ACTIVITY_NET_PRICE_RULES.md
> S16_DYNAMIC_DIAGNOSIS_KNOWLEDGE.md
```

其中，美团当前大盘、本店支付订单、同行平均和同行酒店数的实时取值规则，以及美团日内预计日终值的完成率/回退规则，以 `S16_MEITUAN_DAILY_PROJECTION_AND_ADVISORY_RULES.md` 为唯一权威。其它旧文档若仍写有 JD01 代理、FLOW 优先、跨日补值或把线性外推写成默认主算法，不得采用。

## 关键兼容解释

旧知识中：

> 低置信、只读、商品级的试探涨降价建议，且不能只给一个。

该试探建议必须由确定性代码生成，并满足：

- 明确为美团；
- 精确到 `ota_product_id`；
- 房型销售进度已有明确状态；
- 美团底价先扣佣金；
- 所有有效活动系数连续相乘；
- 只用活动后预计酒店收入与 PMS 房型成交 P20/中位/P80 做参考；
- 不把商品判成确定偏高或偏低；
- `advisory_only=true`；
- `auto_execution_eligible=false`；
- 交由 S5/S6 重新核验。

## 美团口径

大盘、份额、浏览、一转、二转和商品价格相关输出都必须明确写“美团”。

其中当前大盘这一组字段：

- 本店支付订单优先使用当前业务日最新合法批次的 `PAY_ORDER_CNT.metric_value`；
- 同行平均优先使用同一 PAY 行的 `peer_average`；
- PAY 对应单元格为空时，只允许同一业务日、同一 `snapshot_time` 的 `FLOW_PAY_ORDER_CNT` 对应字段补充；
- 同行酒店总数优先使用 PAY `competitor_rank` 分母；缺失时可使用同业务日同 `snapshot_time` 的其它美团指标 `competitor_rank` 的共同分母；
- 其它指标的排名名次不能冒充支付订单排名；
- 当前大盘绝不读取上一业务日、昨天或历史日来补齐；当天同批次仍不完整就标记不可用；
- 这种同批字段互补不能在飞书回复中描述成“回退”“兜底”或“降级”。

另外：

- 大盘和份额是估算值；
- 浏览和预计日终大盘优先使用 `meituan_ota_business_metrics_hourly` 的可比历史同小时完成率；
- `PAY_ORDER_CNT.metric_value`、`PAY_ORDER_CNT.peer_average`、`INTENTION_UV.metric_value` 各自独立计算完成率；
- 某一分量没有有效历史完成率时，只允许该分量线性回退，不能把其它已有历史完成率的分量一起改回线性；
- 当前大盘和当前份额仍按当前时点事实直接估算，收盘预测不改变它们；
- 一转、二转只比较当前累计率与历史完整日中位的方向；
- 预计日终趋势不冒充 S15 小时基准，也不自动触发动作。

## 不可修改边界

AI 不得：

- 改动确定性代码给出的数字和建议幅度；
- 省略“美团”“估算”“预测来源”“低置信”“不自动执行”等关键边界；
- 把美团当前支付订单改说成 JD01/PMS 代理值；
- 把同日同批次 FLOW 或其它指标的字段补充说成跨日回退、昨日兜底或历史借数；
- 声称当前大盘可以使用上一业务日同行均值、同行酒店数或本店支付订单；
- 在已有合法历史同小时完成率时，把线性外推描述成默认主算法；
- 把试探建议说成正式候选、审批结果或已执行动作；
- 删除确定性代码已经生成的异常房型或试探调价商品；
- 用“请改问 S5”代替已经取得的 S16 经营分析。
