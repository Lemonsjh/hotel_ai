from __future__ import annotations

from marketing_diagnosis.ai_analysis import build_ai_analysis
from marketing_diagnosis.cap_engine import apply_score_caps
from marketing_diagnosis.metrics_core import (
    competitor_metrics,
    funnel_metrics,
    nearby_event_metrics,
    operating_metrics,
    price_ladder_metrics,
    promotion_metrics,
    reputation_metrics,
)
from marketing_diagnosis.metrics_enrichment import enrich_metrics
from marketing_diagnosis.optimization_check import build_optimization_checks
from marketing_diagnosis.rule_catalog import MODULE_CONFIG, MODULE_NAME, MODULE_WEIGHT, RULE_CATALOG


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _module_score(module_id, rate, reasons, status="ok", source_fields=None, rule_ids=None):
    weight = MODULE_WEIGHT[module_id]
    if rate is None:
        score = 0.0
        clean_rate = None
    else:
        clean_rate = _clamp(rate)
        score = round(weight * clean_rate, 2)
    return {
        "module_id": module_id,
        "module_name": MODULE_NAME[module_id],
        "weight": weight,
        "score": score,
        "rate": round(clean_rate, 4) if clean_rate is not None else None,
        "status": status,
        "reasons": reasons,
        "source_fields": source_fields or [],
        "rule_ids": rule_ids or [],
    }


def _risk(score):
    if score < 60:
        return "high"
    if score < 80:
        return "medium"
    return "low"


def _missing_count(data_quality):
    return sum(len(v or []) for v in (data_quality.get("missing_fields") or {}).values())


def _rule_lookup():
    return {item["rule_id"]: item for item in RULE_CATALOG}


def build_rule_hits(module_scores):
    rules = _rule_lookup()
    hits = []
    for module in module_scores:
        for rule_id in module.get("rule_ids") or []:
            rule = rules.get(rule_id, {"rule_id": rule_id, "name": rule_id, "logic": ""})
            hits.append({
                "rule_id": rule_id,
                "module_id": module.get("module_id"),
                "module_name": module.get("module_name"),
                "rule_name": rule.get("name"),
                "field": rule.get("field"),
                "logic": rule.get("logic"),
                "status": module.get("status"),
                "score": module.get("score"),
                "weight": module.get("weight"),
                "reasons": module.get("reasons") or [],
            })
    return hits


def score_modules(metrics, data_quality):
    op = metrics["operating"]
    funnel = metrics["ota_funnel"]
    price = metrics["price_ladder"]
    promo = metrics["promotion"]
    rep = metrics["reputation"]
    events = metrics["nearby_events"]
    competitors = metrics["competitors"]
    missing_count = _missing_count(data_quality)
    empty_sections = data_quality.get("empty_sections") or {}

    occ = op.get("occupancy_rate")
    revpar = op.get("revpar")
    adr = op.get("adr")
    conv = funnel.get("payment_conversion_rate")
    peer_conv = funnel.get("peer_avg_conversion_rate")
    exposure = funnel.get("exposure")
    views = funnel.get("views")
    paid_orders = funnel.get("paid_orders")
    sales_revenue = funnel.get("sales_revenue")
    neg = rep.get("negative_review_rate")
    rating = rep.get("rating_avg")
    review_count = rep.get("review_count") or 0
    jump_count = len(price.get("price_jump_risks") or [])
    product_count = price.get("product_count") or 0
    active_promo = promo.get("active_activity_count") or 0
    promo_products = promo.get("activity_product_count") or 0
    keywords = rep.get("keywords") or []
    gap = competitors.get("own_min_price_vs_competitor_avg_gap")

    scores = []

    if occ is None and revpar is None:
        scores.append(_module_score("M01", None, ["经营底盘缺少出租率/RevPAR，无法评分"], "data_gap", ["hotel_daily.room_count", "hotel_daily.room_nights", "hotel_monthly.revpar"], ["R-M01-01", "R-M01-02"]))
    else:
        occ_rate = 0.45 if occ is None else 0.95 if occ >= 0.85 else 0.82 if occ >= 0.75 else 0.65 if occ >= 0.6 else 0.45
        if revpar is not None:
            occ_rate = min(0.98, occ_rate + (0.10 if revpar >= 140 else 0.05 if revpar >= 100 else -0.08 if revpar < 80 else 0))
        reasons = [f"出租率={occ}", f"ADR={adr}", f"RevPAR={revpar}"]
        scores.append(_module_score("M01", occ_rate, reasons, "ok", ["hotel_daily.room_count", "hotel_daily.room_nights", "hotel_daily.room_revenue", "hotel_monthly.revpar"], ["R-M01-01", "R-M01-02", "R-M01-03"]))

    if views is None and exposure is None:
        scores.append(_module_score("M02", None, ["OTA曝光/浏览缺失，无法判断流量入口"], "data_gap", ["ota_business_metrics.exposure", "ota_business_metrics.views"], ["R-M02-01", "R-M02-02"]))
    else:
        exposure_to_view = funnel.get("exposure_to_view_rate")
        traffic_rate = 0.55
        if (exposure or 0) >= 2000 or (views or 0) >= 300:
            traffic_rate = 0.9
        elif (exposure or 0) >= 800 or (views or 0) >= 100:
            traffic_rate = 0.75
        if exposure_to_view is not None and exposure_to_view < 0.08:
            traffic_rate = min(traffic_rate, 0.62)
        scores.append(_module_score("M02", traffic_rate, [f"曝光={exposure}", f"浏览={views}", f"曝光浏览转化={exposure_to_view}"], "ok", ["ota_funnel.exposure", "ota_funnel.views", "ota_funnel.exposure_to_view_rate"], ["R-M02-01", "R-M02-02", "R-M02-03"]))

    if conv is None:
        scores.append(_module_score("M03", None, ["支付转化率缺失，无法判断二转"], "data_gap", ["ota_business_metrics.payment_conversion_rate", "paid_orders"], ["R-M03-01", "R-M03-02"]))
    else:
        if peer_conv:
            conversion_rate = 0.9 if conv >= peer_conv else 0.65 if conv >= peer_conv * 0.75 else 0.35
        else:
            conversion_rate = 0.9 if conv >= 0.08 else 0.65 if conv >= 0.04 else 0.35
        if paid_orders is not None and paid_orders < 5:
            conversion_rate = min(conversion_rate, 0.58)
        scores.append(_module_score("M03", conversion_rate, [f"支付订单={paid_orders}", f"销售额={sales_revenue}", f"二转={conv}", f"同行均值={peer_conv}"], "ok", ["ota_funnel.payment_conversion_rate", "ota_funnel.paid_orders", "ota_funnel.sales_revenue"], ["R-M03-01", "R-M03-02", "R-M03-03"]))

    if not product_count:
        scores.append(_module_score("M04", None, ["商品/价格映射缺失，无法判断价格房型"], "data_gap", ["ota_goods_price_mapping"], ["R-M04-01", "R-M04-02"]))
    else:
        price_rate = 0.84 if not jump_count else 0.6
        if price.get("room_type_count") and price.get("room_type_count") >= 8:
            price_rate = min(0.92, price_rate + 0.06)
        if gap is not None and gap > 30:
            price_rate = min(price_rate, 0.68)
        reasons = [f"商品数={product_count}", f"房型数={price.get('room_type_count')}", f"价格跨度={price.get('price_span')}", f"竞品价差={gap}"]
        scores.append(_module_score("M04", price_rate, reasons, "ok", ["products.listed_price", "products.final_price", "competitors.price"], ["R-M04-01", "R-M04-02", "R-M04-03"]))

    if promo.get("status") == "data_gap":
        scores.append(_module_score("M05", None, ["推广活动和推广ROI字段均缺失"], "data_gap", ["ota_promotion_activity", "promo_cost", "promo_roi"], ["R-M05-01", "R-M05-02"]))
    else:
        promo_rate = 0.55
        if active_promo >= 5:
            promo_rate += 0.12
        if promo_products >= 30:
            promo_rate += 0.08
        status = "ok" if promo.get("has_cost_roi_fields") else "partial"
        if not promo.get("has_cost_roi_fields"):
            promo_rate = min(promo_rate, 0.68)
        scores.append(_module_score("M05", promo_rate, [f"活动数={promo.get('activity_count')}", f"活动商品数={promo_products}", "推广花费/ROI字段未完整接入"], status, ["ota_promotion_activity", "ota_activity_product_detail", "promo_cost", "promo_roi"], ["R-M05-01", "R-M05-02"]))

    if not product_count:
        scores.append(_module_score("M06", None, ["页面/商品基础字段缺失"], "data_gap", ["page_images", "page_video", "products"], ["R-M06-01", "R-M06-02"]))
    else:
        content_rate = 0.55
        if keywords:
            content_rate += 0.12
        if active_promo:
            content_rate += 0.05
        if events.get("upcoming_60d_count"):
            content_rate += 0.03
        scores.append(_module_score("M06", content_rate, ["商品名/房型/评价关键词已接入", "图片/视频/入口标签仍需结构化采集"], "partial", ["products.product_name", "review_rankings.rank_item_name", "page image/video/tag fields"], ["R-M06-01", "R-M06-02"]))

    if rating is None and not review_count:
        scores.append(_module_score("M07", None, ["评价分和评价概览缺失"], "data_gap", ["ota_review_detail", "ota_review_overview"], ["R-M07-01", "R-M07-02"]))
    else:
        rep_rate = 0.5 if rating is None else 0.92 if rating >= 4.7 and (neg is None or neg <= 0.03) else 0.72 if rating >= 4.4 else 0.45
        if review_count < 10:
            rep_rate = min(rep_rate, 0.65)
        scores.append(_module_score("M07", rep_rate, [f"评分={rating}", f"评价数={review_count}", f"差评率={neg}", f"未回复={rep.get('unreplied_review_count')}"], "ok", ["reviews.rating", "review_overviews.review_score", "review_overviews.unreplied"], ["R-M07-01", "R-M07-02"]))

    quality_rate = 0.92 if missing_count == 0 and not empty_sections else 0.72 if missing_count <= 3 else 0.45
    scores.append(_module_score("M08", quality_rate, [f"缺失字段数={missing_count}", f"空模块={list(empty_sections.keys())}"], "ok" if missing_count == 0 and not empty_sections else "partial", ["normalization diagnostics", "source diagnostics"], ["R-M08-01", "R-M08-02"]))
    return scores


def _notes_and_actions(metrics, module_scores, data_quality):
    operating = metrics["operating"]
    funnel = metrics["ota_funnel"]
    price = metrics["price_ladder"]
    promotion = metrics["promotion"]
    reputation = metrics["reputation"]
    events = metrics["nearby_events"]
    competitors = metrics["competitors"]
    notes = []
    actions = []
    conv = funnel.get("payment_conversion_rate")
    peer = funnel.get("peer_avg_conversion_rate")
    if conv is not None and peer is not None and conv < peer * 0.75:
        notes.append({"level": "高", "title": "浏览到支付转化低于同行", "evidence": f"本店转化率={conv:.4f}，同行均值={peer:.4f}", "suggestion": "优先检查页面包装、房型卖点、价格梯度、评论露出和退改政策。"})
        actions.append("先优化 OTA 页面包装与价格梯度，再观察支付转化率是否回升。")
    jump_count = len(price.get("price_jump_risks") or [])
    if jump_count:
        notes.append({"level": "中", "title": "价格梯度存在跳水风险", "evidence": f"风险商品数={jump_count}", "suggestion": "把团购、钟点房、全日房、活动价放在同一张价格表里复核。"})
        actions.append("整理全渠道价格梯度，避免引流价、活动价和远期价互相打架。")
    if promotion.get("status") == "partial" and not promotion.get("has_cost_roi_fields"):
        notes.append({"level": "中", "title": "推广 ROI 暂时无法核验", "evidence": "已有活动覆盖数据，但缺少推广花费、点击、推广订单、推广收入和 ROI 字段", "suggestion": "补齐推广 ROI 字段后再判断推广通/全域通是否值得加码。"})
        actions.append("补齐推广花费、点击、推广订单、推广收入和 ROI 字段，再做投放复盘。")
    neg_rate = reputation.get("negative_review_rate")
    if neg_rate is not None and neg_rate > 0.05:
        notes.append({"level": "中", "title": "差评率偏高", "evidence": f"差评率={neg_rate:.4f}", "suggestion": "提取高频差评关键词，分别落到服务、设施、卫生、隔音和页面预期管理。"})
    if events.get("upcoming_60d_count"):
        notes.append({"level": "低", "title": "存在可利用的周边需求事件", "evidence": f"未来60天周边活动数={events.get('upcoming_60d_count')}", "suggestion": "把周边活动用于需求判断、远期价格铺设和套餐设计。"})
    gap = competitors.get("own_min_price_vs_competitor_avg_gap")
    if gap is not None and gap > 30:
        notes.append({"level": "中", "title": "本店引流价高于竞对均价", "evidence": f"价差={gap:.2f}", "suggestion": "先优化入口产品和低价日历，不要直接做全量降价。"})
    if operating.get("occupancy_rate") is not None and operating["occupancy_rate"] < 0.65:
        notes.append({"level": "中", "title": "出租率偏低", "evidence": f"出租率={operating['occupancy_rate']:.4f}", "suggestion": "按订单量=流量×转化拆解，先判断是曝光不足还是二转偏弱。"})
    data_gap_modules = [item["module_id"] for item in module_scores if item.get("status") == "data_gap"]
    if data_gap_modules:
        notes.append({"level": "中", "title": "部分模块仍是数据缺口", "evidence": f"缺口模块={','.join(data_gap_modules)}", "suggestion": "不要把数据缺口当作真实经营结论，先补齐对应表和字段后再复算。"})
        actions.append("先检查数据质量和字段映射，再把报告用于外部汇报或经营决策。")
    if not notes:
        notes.append({"level": "低", "title": "当前未触发明显高风险规则", "evidence": "已接入数据未触发高风险规则", "suggestion": "继续补充连续数据，重点观察趋势而不是单次结果。"})
        actions.append("继续补齐连续数据，再做环比、同比和竞对对比。")
    return notes, actions, data_gap_modules


def process(data):
    sections = data.get("sections") or {}
    operating = operating_metrics(sections.get("hotel_daily", []), sections.get("hotel_monthly", []))
    funnel = funnel_metrics(sections.get("ota_funnel", []))
    price = price_ladder_metrics(sections.get("products", []))
    promotion = promotion_metrics(sections.get("promotions", []), sections.get("promotion_products", []))
    reputation = reputation_metrics(sections.get("reviews", []), sections.get("review_overviews", []), sections.get("review_rankings", []))
    events = nearby_event_metrics(sections.get("nearby_events", []))
    competitors = competitor_metrics(sections.get("competitors", []), own_min_price=price.get("min_price") if price.get("status") == "ok" else None)
    data_quality = {
        "status": data.get("status"),
        "missing_fields": data.get("missing_fields") or {},
        "empty_sections": data.get("empty_sections") or {},
        "diagnostics": data.get("diagnostics") or {},
        "source_diagnostics": data.get("source_diagnostics") or [],
    }
    metrics = {"operating": operating, "ota_funnel": funnel, "price_ladder": price, "promotion": promotion, "reputation": reputation, "nearby_events": events, "competitors": competitors}
    data_time_context = enrich_metrics(metrics, sections)
    module_scores = score_modules(metrics, data_quality)
    score_before_cap = round(sum(item["score"] for item in module_scores), 2)
    notes, actions, data_gap_modules = _notes_and_actions(metrics, module_scores, data_quality)
    result = {
        "status": "ok" if data.get("status") == "ok" and not data_gap_modules else "partial",
        "type": "ota_marketing",
        "boundary": "report_only",
        "score_before_cap": score_before_cap,
        "final_score": score_before_cap,
        "risk_level": _risk(score_before_cap),
        "module_config": MODULE_CONFIG,
        "module_scores": module_scores,
        "rule_hits": build_rule_hits(module_scores),
        "data_quality": data_quality,
        "data_time_context": data_time_context,
        "metrics": metrics,
        "notes": notes,
        "actions": actions,
    }
    result = apply_score_caps(result)
    result["risk_level"] = _risk(result["final_score"])
    result["optimization_checks"] = build_optimization_checks(result)
    result["ai_analysis"] = build_ai_analysis(result)
    return result
