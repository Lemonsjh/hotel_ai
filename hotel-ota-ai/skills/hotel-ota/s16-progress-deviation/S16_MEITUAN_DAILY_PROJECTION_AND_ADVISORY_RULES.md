# S16 美团日内趋势与试探调价知识规则

本文件规定 S16 如何解释美团当日累计数据，以及如何生成只读、低置信的试探涨降价建议。所有数值必须由确定性代码产生，AI 不得自行计算或改写。

## 1. 所有平台指标必须明确写“美团”

以下指标均来自美团经营指标或由其估算：

- 美团大盘估算；
- 美团估算份额；
- 美团浏览；
- 美团一转；
- 美团二转；
- 美团商品底价；
- 美团活动后预计酒店收入；
- 美团试探涨降价建议。

普通回复不得省略“美团”，不得把这些值说成全渠道或全市场的确定事实。

## 2. 当前本店美团支付订单与同行字段

使用 `meituan_ota_business_metrics`。大盘这一组字段固定以 `PAY_ORDER_CNT` 为主：

```text
hotel_id = 当前酒店
business_date = 目标业务日
metric_code = PAY_ORDER_CNT
snapshot_time <= 请求截止时间
取最新合法采集行
```

字段优先级：

```text
本店支付订单 = PAY_ORDER_CNT.metric_value
同行平均订单 = PAY_ORDER_CNT.peer_average
支付订单排名/同行酒店数 = PAY_ORDER_CNT.competitor_rank
```

`PAY_ORDER_CNT` 某一个单元格为空或不可用时，可以使用同一 `business_date`、同一 `snapshot_time` 的 `FLOW_PAY_ORDER_CNT` 对应单元格补充：

```text
FLOW.business_date = PAY.business_date
FLOW.snapshot_time = PAY.snapshot_time
```

允许补充的字段包括：

```text
metric_value
peer_average
competitor_rank 中的同行酒店总数分母
```

同行酒店总数具有同批次共享语义。如果 PAY 行没有 `competitor_rank` 分母，同一业务日、同一 `snapshot_time` 的其它美团指标行只要带有形如 `x/20` 的 `competitor_rank`，可以使用其中共同的分母 `20` 作为 `peer_hotel_count`。其它指标的排名名次 `x` 不能冒充支付订单排名。

因此：

- `PAY_ORDER_CNT` 对应字段有值时永远优先，不能被 `FLOW_PAY_ORDER_CNT` 覆盖；
- 同批补充按单元格进行，不做整行替换；
- `metric_value` 和 `peer_average` 只允许由同批 `FLOW_PAY_ORDER_CNT` 对应字段补充；
- `peer_hotel_count` 可以由同批 `FLOW_PAY_ORDER_CNT` 或其它美团指标 `competitor_rank` 的共同分母补充；
- 不允许跨 `snapshot_time` 拼接；
- 不允许跨 `business_date`；上一业务日、昨天和历史日永远不能参与当前大盘字段补充；
- 没有合法 `PAY_ORDER_CNT` 主行时，本店订单、大盘和份额明确不可用；
- 当天同批次仍凑不齐关键字段时，明确输出当前大盘暂不可用，不能读取上一日补齐；
- 不改用 `jd01_booking_detail`、PMS 订单明细或渠道标签猜测作为代理或兜底。

注意：这里是**同批次字段互补**，不是数据回退、历史兜底或降级。普通飞书回复不得把同批补充描述成“回退到昨天”“借用了上一日”“兜底历史值”等话术。

该表约每小时采集一次，因此必须输出实际采集时间，允许相对平台页面存在约一小时延迟，不称为绝对实时值。

## 3. 美团大盘和份额估算

计算：

```text
current_estimated_market_orders
= own_pay_orders
+ peer_average_orders × (peer_hotel_count - 1)

current_estimated_market_share
= own_pay_orders / current_estimated_market_orders
```

其中：

- `own_pay_orders`：PAY `metric_value` 优先，空时仅允许同日同批 FLOW `metric_value` 补充；
- `peer_average_orders`：PAY `peer_average` 优先，空时仅允许同日同批 FLOW `peer_average` 补充；
- `peer_hotel_count`：PAY `competitor_rank` 分母优先，缺失时可由同日同批 FLOW 或其它美团指标 `competitor_rank` 的共同分母补充；
- 三者均禁止跨日、跨批次取数。

输出必须称为：

```text
美团大盘（估算）
美团估算份额
```

不得称为平台直接提供的大盘总订单或真实市场份额。

## 4. 美团日内收盘预测：历史同小时完成率优先

当目标日期等于请求当天时，S16 可以额外只读 `meituan_ota_business_metrics_hourly`，优先使用可比历史日的**同小时完成率**把当前累计值换算为预计日终值。该小时表只提供收盘预测完成率，不写回 S15，也不改变 S15 的日级基准定义。

历史完成率固定规则：

- 最多读取目标日前最近 60 个自然日；
- 候选历史日来自小时表自身实际可用日期，并复用 S15 最终平台基准的同类日期筛选层级；
- 每个指标/字段独立判断有效历史日；
- 有效历史日必须同时存在当前请求小时的精确 `snapshot_hour` 正值，以及该历史日最后一个正值；
- 缺当前小时不插值、不拿前一小时补；
- 单日完成率 = `value_at_same_hour / final_positive_value`；
- 至少 1 个筛选后的有效历史日即可使用；多个有效日取 median；
- `PAY_ORDER_CNT.metric_value`、`PAY_ORDER_CNT.peer_average`、`INTENTION_UV.metric_value` 分别计算，不共享完成率，也不强行对齐样本。

对应投影：

```text
projected_own_pay_orders
= current_own_pay_orders / own_pay_orders_completion_rate

projected_peer_average_pay_orders
= current_peer_average_pay_orders / peer_average_completion_rate

projected_browse
= current_browse / browse_completion_rate

projected_market_orders
= projected_own_pay_orders
+ projected_peer_average_pay_orders × (current_peer_hotel_count - 1)
```

其中 `current_peer_hotel_count` 始终使用**当前时点** `competitor_rank` 分母；历史小时表中的排名或圈子大小不得替代当前分母。

某一个分量没有有效历史完成率时，**仅该分量**回退现有线性节奏，其他已有历史完成率的分量继续使用历史完成率：

```text
elapsed_day_fraction = 当天已过分钟 / 1440
linear_projected_full_day = current_accumulated / elapsed_day_fraction
```

线性回退仍只在当天已过至少约 35% 时使用。不得因为一个分量缺历史，就把整个大盘或浏览预测全部改回线性外推。

预计日终值继续与 S15 历史完整日中位比较：

| 预计日终值 / 历史中位 | 解释 |
|---:|---|
| `>= 1.05` | 预计有望跑赢历史 |
| `0.95–1.05` | 预计大致接近历史 |
| `< 0.95` | 预计较难跑赢历史 |

适用于：

- 美团浏览预计日终值；
- 美团估算大盘订单预计日终值。

普通回复必须说明预测来源是“历史同小时完成率”还是“线性回退”。这些值是趋势参考，不是美团小时基准，也不是确定收盘结果。

## 5. 美团一转和二转当前累计率

### 一转

```text
first_conversion = browse_users / exposure_users
```

至少满足：

```text
exposure_users >= 300
browse_users >= 30
```

才能输出较强方向判断：当前累计高于、接近或低于历史完整日中位。

### 二转

```text
second_conversion = pay_orders / browse_users
```

至少满足：

```text
browse_users >= 50
pay_orders >= 3
```

才能输出较强方向判断。

可以估算达到历史二转中位需要的订单：

```text
required_pay_orders
= CEIL(projected_full_day_browse × historical_second_conversion_median)

additional_orders_needed
= MAX(required_pay_orders - current_pay_orders, 0)
```

必须说明它基于预计浏览量，只作趋势参考。

## 6. 试探涨降价建议

没有同一美团商品连续历史价格时，仍不得形成确定“偏高/偏低”结论，也不得进入正式执行候选。

但 S16 可以形成低置信、只读、商品级的试探涨降价建议，依据：

```text
房型当前销售进度
+ 当前美团商品底价
+ commission_rate
+ 全部有效活动系数连乘
+ 活动后预计酒店收入
+ PMS 房型历史成交 P20 / 中位 / P80
```

### 6.1 固定价格口径

```text
commission_net_base
= raw_price × (1 - commission_rate)

combined_activity_factor
= factor_1 × factor_2 × ... × factor_n

estimated_activity_net_price
= commission_net_base × combined_activity_factor
```

### 6.2 降价建议条件

必须同时满足：

- 普通全天房；
- 精确 `ota_product_id`；
- 房型总房量至少 2 间；
- 房型销售进度偏慢、明显偏慢或严重偏慢；
- 当前活动后预计酒店收入高于 PMS 房型成交中位 5% 以上；
- 有合法佣金率、活动系数和 PMS 价格参考。

幅度上限：

```text
偏慢：最多 -3%
明显偏慢：最多 -5%
严重偏慢：最多 -8%
```

### 6.3 涨价建议条件

必须同时满足：

- 普通全天房；
- 精确 `ota_product_id`；
- 房型总房量至少 2 间；
- 房型销售进度偏快或明显偏快；
- 当前仍有可售库存；
- 当前活动后预计酒店收入低于 PMS 房型 P80 的 98%；
- 有合法佣金率、活动系数和 PMS 价格参考。

幅度上限：

```text
偏快：最多 +3%
明显偏快：最多 +5%
```

### 6.4 数量、观察期和执行边界

每次最多：

- 2 个试探降价建议；
- 2 个试探涨价建议。

观察期：

- 试探涨价通常 60 分钟；
- 试探降价通常 90 分钟。

所有建议必须包含：

```text
platform = meituan
ota_product_id
当前美团底价
建议美团底价
建议变化比例
活动后预计酒店收入
PMS 房型成交参考
房型销售状态
观察期
advisory_only = true
auto_execution_eligible = false
handoff_capability = S5
```

普通回复必须说明：

> 以上是低置信试探建议，不代表同一商品历史价格结论；不自动执行，交由 S5/S6 按具体商品重新核验。

## 7. AI 禁止

AI 不得：

- 把美团数据写成全渠道数据；
- 把本店美团支付订单称为代理值；
- 使用 JD01/PMS 订单替代或兜底美团经营指标；
- 在 `PAY_ORDER_CNT` 对应字段有合法值时改用 `FLOW_PAY_ORDER_CNT` 覆盖该字段；
- 使用不同 `snapshot_time` 或不同 `business_date` 的 `FLOW_PAY_ORDER_CNT` 补充 `PAY_ORDER_CNT`；
- 使用上一业务日、昨天或历史日的同行均值、同行酒店数或本店支付订单构造当前大盘；
- 把同日同批次的字段互补描述成“回退”“兜底”“降级”或“借历史数据”；
- 把其它指标的排名名次当作支付订单排名；其它指标只允许提供同批次同行酒店总数分母；
- 在已有合法历史同小时完成率时改用线性外推；线性只允许作为对应分量没有有效完成率时的回退；
- 把预计日终值说成确定收盘结果或美团小时基准；
- 对缺失小时插值、补零或拿前一小时向后填充；
- 在样本门槛不足时强判一转或二转；
- 自行改变建议幅度；
- 自行新增未由确定性代码生成的涨降价商品；
- 把试探建议写成已执行、待执行或正式调价候选；
- 省略不含用户券、参考口径、数据时效和人工复核边界。
