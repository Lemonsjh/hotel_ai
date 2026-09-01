from __future__ import annotations

MODULE_CONFIG = [
    {"module_id": "M01", "module_name": "经营结果与收益锚点", "weight": 20, "scope": "pms"},
    {"module_id": "M02", "module_name": "流量曝光与竞争圈", "weight": 15, "scope": "ota"},
    {"module_id": "M03", "module_name": "转化下单与路径断点", "weight": 15, "scope": "ota"},
    {"module_id": "M04", "module_name": "价格收益与房态库存", "weight": 15, "scope": "price"},
    {"module_id": "M05", "module_name": "推广效率与ROI", "weight": 10, "scope": "promotion"},
    {"module_id": "M06", "module_name": "页面展示与入口基础", "weight": 10, "scope": "content"},
    {"module_id": "M07", "module_name": "口碑信任与服务响应", "weight": 8, "scope": "reputation"},
    {"module_id": "M08", "module_name": "执行复盘与数据完整度", "weight": 7, "scope": "data_quality"},
]

MODULE_WEIGHT = {item["module_id"]: item["weight"] for item in MODULE_CONFIG}
MODULE_NAME = {item["module_id"]: item["module_name"] for item in MODULE_CONFIG}

RULE_CATALOG = [
    {"rule_id": "R-M01-01", "module_id": "M01", "name": "出租率水平", "field": "operating.occupancy_rate", "logic": "出租率越高经营底盘越稳，低于65%进入预警。"},
    {"rule_id": "R-M01-02", "module_id": "M01", "name": "RevPAR收益锚点", "field": "operating.revpar", "logic": "RevPAR用于校验ADR和出租率组合后的真实收益。"},
    {"rule_id": "R-M01-03", "module_id": "M01", "name": "收入趋势", "field": "operating.monthly_trend.revenue_mom", "logic": "连续下降会触发总分封顶，避免经营差但分数虚高。"},
    {"rule_id": "R-M02-01", "module_id": "M02", "name": "曝光规模", "field": "ota_funnel.exposure", "logic": "曝光不足通常先补流量，曝光充足但转化差则转向页面/价格。"},
    {"rule_id": "R-M02-02", "module_id": "M02", "name": "曝光到浏览一转", "field": "ota_funnel.exposure_to_view_rate", "logic": "一转低说明入口图、标题、价格、标签或排序承接弱。"},
    {"rule_id": "R-M02-03", "module_id": "M02", "name": "竞争圈位置", "field": "ota_funnel.peer_rank", "logic": "同商圈排名和同行转化用于避免只看自身绝对值。"},
    {"rule_id": "R-M03-01", "module_id": "M03", "name": "浏览到支付二转", "field": "ota_funnel.payment_conversion_rate", "logic": "二转低优先查价格梯度、评价露出、退改政策和房型卖点。"},
    {"rule_id": "R-M03-02", "module_id": "M03", "name": "订单贡献", "field": "ota_funnel.paid_orders", "logic": "支付订单是漏斗最终结果，不能只看曝光或浏览。"},
    {"rule_id": "R-M03-03", "module_id": "M03", "name": "销售额和客单价", "field": "ota_funnel.sales_revenue/avg_order_value", "logic": "订单提升但收入不升，可能是低价跑量。"},
    {"rule_id": "R-M04-01", "module_id": "M04", "name": "价格梯度", "field": "price_ladder.min/max/span", "logic": "最低价、最高价和跨度用于判断价格体系是否混乱。"},
    {"rule_id": "R-M04-02", "module_id": "M04", "name": "团购与钟点房", "field": "price_ladder.group_buy/hour_room", "logic": "团购/钟点房影响价格感知，需要和全日房一起复核。"},
    {"rule_id": "R-M04-03", "module_id": "M04", "name": "竞对价差", "field": "competitors.own_min_price_vs_competitor_avg_gap", "logic": "本店入口价明显高于竞对时需先复核引流产品。"},
    {"rule_id": "R-M05-01", "module_id": "M05", "name": "活动覆盖", "field": "promotion.activity_count", "logic": "活动覆盖只能说明入口存在，不能代表推广有效。"},
    {"rule_id": "R-M05-02", "module_id": "M05", "name": "推广ROI", "field": "promotion.promo_roi", "logic": "推广花费、推广订单金额、ROI缺失时推广效率必须保守。"},
    {"rule_id": "R-M06-01", "module_id": "M06", "name": "页面基础", "field": "page.image/video/tags", "logic": "图片、视频、房型卖点、入口标签影响一转和二转。"},
    {"rule_id": "R-M06-02", "module_id": "M06", "name": "商品/房型承接", "field": "products.product_count/room_type_count", "logic": "商品和房型承接不足会影响用户选择。"},
    {"rule_id": "R-M07-01", "module_id": "M07", "name": "评分与评价规模", "field": "reputation.rating/review_count", "logic": "评价数过少时不能只因评分高就判断口碑稳定。"},
    {"rule_id": "R-M07-02", "module_id": "M07", "name": "差评与未回复", "field": "reputation.negative_rate/unreplied", "logic": "差评和未回复影响信任与支付转化。"},
    {"rule_id": "R-M08-01", "module_id": "M08", "name": "关键字段完整度", "field": "data_quality.missing_fields", "logic": "缺字段会触发可信度扣分和总分封顶。"},
    {"rule_id": "R-M08-02", "module_id": "M08", "name": "空模块", "field": "data_quality.empty_sections", "logic": "空模块较多时，不允许把报告当作完整经营结论。"},
]

CAP_RULES = [
    {"cap_id": "C01", "name": "RevPAR低封顶", "cap_score": 75, "severity": "high", "description": "RevPAR低于收益锚点时，总分最高75，防止基础项把经营差掩盖。"},
    {"cap_id": "C02", "name": "收入趋势下降封顶", "cap_score": 78, "severity": "medium", "description": "月度收入或RevPAR明显下滑时，总分最高78。"},
    {"cap_id": "C03", "name": "订单和转化双弱封顶", "cap_score": 72, "severity": "high", "description": "支付订单弱且二转低时，总分最高72。"},
    {"cap_id": "C04", "name": "推广ROI缺失封顶", "cap_score": 85, "severity": "medium", "description": "有活动覆盖但推广花费、订单金额、ROI缺失时，推广模块和总分需保守。"},
    {"cap_id": "C05", "name": "关键字段缺失封顶", "cap_score": 70, "severity": "high", "description": "关键字段缺失较多时，总分最高70，防止缺口数据生成过强结论。"},
    {"cap_id": "C06", "name": "基础项高但经营弱封顶", "cap_score": 80, "severity": "medium", "description": "页面、口碑、数据项较好但出租率/RevPAR/订单弱时，总分最高80。"},
    {"cap_id": "C07", "name": "口碑样本过少校准", "cap_score": 88, "severity": "low", "description": "评分高但评价量过少时，口碑不能强推高总分。"},
]

OPTIMIZATION_RULES = [
    {"check_id": "O01", "name": "分数提升且收益提升", "logic": "分数、订单、RevPAR、收入同步提升，才算有效优化。"},
    {"check_id": "O02", "name": "分数提升但收益没提升", "logic": "疑似无效优化，要复核评分项是否偏基础项。"},
    {"check_id": "O03", "name": "流量提升但订单没提升", "logic": "说明二转、价格、口碑或页面承接仍有断点。"},
    {"check_id": "O04", "name": "订单提升但收入没提升", "logic": "可能是低价跑量，应复核ADR和客单价。"},
    {"check_id": "O05", "name": "评分高但经营差", "logic": "口碑样本或基础项可能让分数失真，需要经营封顶。"},
    {"check_id": "O06", "name": "字段补齐后重算", "logic": "字段补齐后必须重算，不能沿用缺字段时期结论。"},
]
