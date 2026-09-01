from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any


ITEMS = [
    (1, "月度经营趋势 YOY", 10, True), (2, "房型 RevPAR 与低效房型", 8, True),
    (3, "曝光数据分析", 4, True), (4, "流量数据分析", 15, True),
    (5, "用户来源数据", 0, False), (6, "HOS 历史得分", 3, True),
    (7, "扫码订单数据", 8, True), (8, "信息分数据", 5, True),
    (9, "推广数据", 8, True), (10, "页面展示和入口基础", 3, True),
    (11, "房型名称卖点优化", 4, True), (12, "竞争对手分析", 0, False),
    (13, "口碑分析", 10, True), (14, "权益中心", 4, True),
    (15, "优美会", 3, True), (16, "商旅专享价", 2, True),
    (17, "公益流量", 2, True), (18, "钟点房", 4, True),
    (19, "酒店亮点", 2, True), (20, "预约发票", 2, True),
    (21, "首页视频", 1, True), (22, "酒店挂冠", 1, True),
    (23, "自动接单", 1, True),
]


SOURCE_MAP: dict[int, tuple[str, list[str]]] = {
    1: ("hotel_puyue.jl02_hotel_performance_daily", ["metric_name", "value_day", "value_month", "value_year", "snapshot_time"]),
    2: ("hotel_puyue.jl01_room_type_performance_daily", ["room_type_name", "room_type_id", "metric_name", "value_day", "value_month", "value_year", "snapshot_time"]),
    3: ("hotel_puyue.meituan_ota_exposure_source_daily", ["business_date", "total_exposure", "non_ad_exposure", "ad_exposure", "ad_exposure_ratio_pct"]),
    4: ("hotel_puyue.meituan_ota_business_metrics", ["metric_code=flow*", "metric_name", "metric_value", "peer_average", "competitor_rank", "business_date"]),
    5: ("hotel_puyue.meituan_ota_user_source_monthly", ["period_month", "local_user_pct", "nonlocal_user_pct", "new_user_pct", "returning_user_pct"]),
    6: ("hotel_puyue.meituan_ota_business_metrics", ["metric_name=HOS分", "metric_value", "competitor_rank", "business_date"]),
    7: ("待提供扫码订单数据表", []),
    8: ("hotel_puyue.meituan_ota_business_metrics", ["metric_name=信息分", "metric_value", "business_date"]),
    9: ("hotel_puyue.meituan_ota_promotion_finance_detail + hotel_puyue.jy03_hotel_statistics_month", ["transaction_time", "transaction_type=推广通支出", "transaction_amount/amount", "period_month", "dimension_type=渠道", "dimension_name=美团EBK", "room_revenue"]),
    10: ("hotel_puyue.meituan_ota_joined_rights", ["hotel_name"]),
    11: ("hotel_puyue.meituan_ota_goods_price_mapping", ["room_type_name"]),
    12: ("hotel_puyue.meituan_ota_order_loss_monthly", ["competitor_hotel_name", "competitor_loss_order_count", "competitor_loss_amount", "lost_room_types_text", "follow_status"]),
    13: ("hotel_puyue.meituan_ota_review_overview", ["review_platform", "review_score", "total_review_count", "unreplied_review_count"]),
    14: ("hotel_puyue.meituan_ota_joined_rights", ["right_name", "effective_room_scope"]),
    15: ("hotel_puyue.meituan_ota_promotion_status", ["promotion_name=优美乐", "status", "enroll_status/registration_status", "effective_status"]),
    16: ("hotel_puyue.meituan_ota_promotion_status", ["promotion_name=商旅专享价", "status", "enroll_status/registration_status", "effective_status"]),
    17: ("hotel_puyue.meituan_ota_promotion_status", ["promotion_name=公益流量", "status", "enroll_status/registration_status", "effective_status"]),
    18: ("hotel_puyue.meituan_ota_promotion_status", ["promotion_name=钟点房", "status", "enroll_status/registration_status", "effective_status"]),
    19: ("hotel_puyue.meituan_ota_promotion_status", ["promotion_name=酒店亮点", "status", "enroll_status/registration_status", "effective_status"]),
    20: ("hotel_puyue.meituan_ota_promotion_status", ["promotion_code=reservation_invoice / promotion_name=预约发票", "status", "enroll_status/registration_status", "effective_status"]),
    21: ("hotel_puyue.meituan_ota_video_upload_status", ["video_type", "uploaded_count", "required_count"]),
    22: ("人工录入", ["crown_type", "operator", "recorded_at"]),
    23: ("hotel_puyue.meituan_ota_promotion_status", ["promotion_name=自动接单", "status", "enroll_status/registration_status", "effective_status"]),
}


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _pct_value(value: Any) -> float | None:
    number = _n(value)
    if number is None:
        return None
    return number / 100 if number > 1 else number


def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_n(row.get(key)) for row in rows]
    clean = [value for value in values if value is not None]
    return sum(clean) if clean else None


def _latest(rows: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    if not rows:
        return {}
    return max(rows, key=lambda row: max((str(row.get(key) or "") for key in keys), default=""))


def _daily_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    daily = [row for row in rows if str(row.get("period_type") or "").strip().lower() in {"日", "daily", "day", "当日"}]
    return daily or rows


def _latest_distinct_days(rows: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    """Keep the latest snapshot for each business day, then take at most 30 days."""
    by_day: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row.get("business_date") or "")[:10]
        if not day:
            continue
        current = by_day.get(day)
        if current is None or str(row.get("snapshot_time") or "") >= str(current.get("snapshot_time") or ""):
            by_day[day] = row
    return [by_day[key] for key in sorted(by_day)[-limit:]]


def _sum_keys(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_n(row.get(key)) for row in rows]
    clean = [value for value in values if value is not None]
    return sum(clean) if clean else None


def _field(label: str, value: Any, note: str = "", origin: str = "数据库原值") -> dict[str, Any]:
    return {"label": label, "value": value, "note": note, "origin": origin}


def _item(no: int, name: str, base: float, participates: bool, *, fields=None,
          status="missing", ratio: float | None = None, note="") -> dict[str, Any]:
    score = round(base * ratio, 2) if ratio is not None and participates else None
    return {
        "standard_item_id": no, "item_name": name, "base_score": base,
        "participates_in_score": participates, "data_status": status,
        "score_ratio": ratio, "item_score": score, "fields": fields or [], "note": note,
    }


def _score_ratio(value: float) -> float:
    return 1.0 if value > 2 else 0.8 if value >= 1.5 else 0.6 if value >= 1 else 0.0


def _status_score(row: dict[str, Any]) -> tuple[str, float | None, str]:
    raw = str(row.get("status") or row.get("open_status") or row.get("enroll_status") or "").upper()
    if raw == "OPEN":
        return "success", 1.0, "已开通 / 已参与"
    if raw == "CLOSED":
        return "zero", 0.0, "未开通 / 未参与"
    if raw == "PENDING":
        return "pending_rule", None, "状态未确定"
    return "missing", None, "未取得状态字段"


def build_visual_diagnosis(sections: dict[str, list[dict[str, Any]]], hotel_name: str = "") -> dict[str, Any]:
    by_no: dict[int, dict[str, Any]] = {}

    # 01 jl02：最新快照提供本日/本月/本年；同月去年快照提供去年同期。
    performance = sections.get("hotel_performance_daily") or []
    latest_stamp = max((str(row.get("snapshot_time") or "")[:19] for row in performance), default="")
    current_rows = [row for row in performance
                    if str(row.get("snapshot_time") or "")[:19] == latest_stamp
                    and row.get("room_type_id") in (None, "")] if latest_stamp else []
    latest_day = latest_stamp[:10]
    previous_year = str(int(latest_day[:4]) - 1) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", latest_day) else ""
    exact_previous = [row for row in performance
                      if str(row.get("snapshot_time") or "")[:4] == previous_year
                      and str(row.get("snapshot_time") or "")[5:10] == latest_day[5:10]]
    previous_candidates = exact_previous or [row for row in performance
                                              if str(row.get("snapshot_time") or "")[:4] == previous_year
                                              and str(row.get("snapshot_time") or "")[5:10] <= latest_day[5:10]]
    previous_stamp = max((str(row.get("snapshot_time") or "")[:19] for row in previous_candidates), default="")
    previous_rows = [row for row in previous_candidates
                     if str(row.get("snapshot_time") or "")[:19] == previous_stamp
                     and row.get("room_type_id") in (None, "")]
    current_by_metric = {str(row.get("metric_name") or ""): row for row in current_rows}
    previous_by_metric = {str(row.get("metric_name") or ""): row for row in previous_rows}
    revenue_name = next((name for name in current_by_metric if name == "房费"), "房费")
    cur_revenue = _n(current_by_metric.get(revenue_name, {}).get("value_month"))
    prev_revenue = _n(previous_by_metric.get(revenue_name, {}).get("value_month"))
    yoy = None if cur_revenue is None or prev_revenue in (None, 0) else (cur_revenue - prev_revenue) / prev_revenue
    ratio = status = None
    if yoy is None:
        status = "pending_rule" if prev_revenue == 0 else "missing"
    elif yoy > .2:
        status, ratio = "success", 1.0
    elif yoy < -.2:
        status, ratio = "success", 0.0
    elif yoy < 0:
        status, ratio = "success", .6
    else:
        status = "pending_rule"  # 0%–20% 和“持平”区间原文未冻结。
    performance_records = []
    for metric_name, row in current_by_metric.items():
        current_value = _n(row.get("value_month"))
        prior_value = _n(previous_by_metric.get(metric_name, {}).get("value_month"))
        metric_yoy = None if current_value is None or prior_value in (None, 0) else (current_value - prior_value) / prior_value
        performance_records.append({"metric_name": metric_name, "value_day": _n(row.get("value_day")),
                                    "value_month": current_value, "value_year": _n(row.get("value_year")),
                                    "previous_value": prior_value, "yoy": metric_yoy})
    by_no[1] = _item(1, ITEMS[0][1], 10, True, status=status, ratio=ratio, fields=[
        _field("本期值", cur_revenue, "房费 value_month"),
        _field("去年同期值", prev_revenue, "去年同期快照的房费 value_month"),
        _field("YOY", yoy, "（本期值－去年同期值）÷去年同期值", "公式计算"),
        _field("本项原始得分", round(10 * ratio, 2) if ratio is not None else None, "未折算得分", "规则计算"),
        _field("取数状态", "已取到" if current_rows else "未取到"),
    ], note="本日、本月、本年使用 jl02 最新快照；YOY 使用去年同期快照。")
    by_no[1]["records"] = performance_records

    room_rows = sections.get("room_type_performance_daily") or []
    grouped_rooms: dict[tuple[str, str], dict[str, Any]] = {}
    for row in room_rows:
        room_name = str(row.get("room_type_name") or row.get("room_name") or "").strip()
        room_id = str(row.get("room_type_id") or "").strip()
        if not room_name or not room_id:
            continue
        record = grouped_rooms.setdefault((room_id, room_name), {"room_type_id": room_id, "room_type_name": room_name})
        metric = str(row.get("metric_name") or "").strip().lower()
        if metric in {"出租率", "入住率"}:
            target = "occupancy"
        elif metric in {"revpar", "revpar值"}:
            target = "revpar"
        else:
            continue
        record[f"{target}_day"] = _n(row.get("value_day"))
        record[f"{target}_month"] = _n(row.get("value_month"))
        record[f"{target}_year"] = _n(row.get("value_year"))
    room_records = list(grouped_rooms.values())
    low_rooms = [row for row in room_records if row.get("occupancy_month") is not None and row["occupancy_month"] < 60]
    room_count = len(room_records) or None
    low_count = len(low_rooms) if room_records else None
    low_ratio = None if not room_count else low_count / room_count
    by_no[2] = _item(2, ITEMS[1][1], 8, True, status="success" if room_records else "missing", fields=[
        _field("低效房型数", low_count, "近30天出租率低于60%的房型数", "条件统计"),
        _field("在售房型数", room_count, "最新快照全部在售房型", "去重统计"),
        _field("低效房型占比", low_ratio, "低效房型数 ÷ 在售房型数", "公式计算"),
        _field("低效房型清单", "、".join(row["room_type_name"] for row in low_rooms) or None),
    ], note="当日使用 value_day；近30天使用 value_month；低效房型为近30天出租率 < 60%。")
    by_no[2]["records"] = room_records

    exposure = _latest_distinct_days(sections.get("exposure_daily") or [])
    total, non_ad, ad = (_sum(exposure, key) for key in ("total_exposure", "non_ad_exposure", "ad_exposure"))
    ad_ratio = None if total in (None, 0) or ad is None else ad / total
    if total is None:
        exp_status, exp_score = "missing", None
    elif total == 0 or ad in (None, 0):
        exp_status, exp_score = "zero", 0.0
    elif ad_ratio is not None and ad_ratio <= .2:
        exp_status, exp_score = "success", .5
    else:
        exp_status, exp_score = "success", 1.0
    daily_fields = [_field("整体曝光（近30天）", total, "SUM(total_exposure)", "区间汇总"),
                    _field("非广告曝光", non_ad, "SUM(non_ad_exposure)", "区间汇总"),
                    _field("广告曝光", ad, "SUM(ad_exposure)", "区间汇总"),
                    _field("广告曝光占比", ad_ratio, "广告曝光合计 ÷ 整体曝光合计", "公式计算")]
    for row in sorted(exposure, key=lambda x: str(x.get("business_date") or ""))[-30:]:
        row_total, row_ad = _n(row.get("total_exposure")), _n(row.get("ad_exposure"))
        daily_ratio = None if row_total in (None, 0) or row_ad is None else row_ad / row_total
        daily_fields.append(_field(f"{str(row.get('business_date') or '')[:10]} 广告曝光占比",
                                   daily_ratio,
                                   "ad_exposure ÷ total_exposure；数据库 ad_exposure_ratio_pct 用于核验",
                                   "公式计算"))
    by_no[3] = _item(3, ITEMS[2][1], 4, True, status=exp_status, ratio=exp_score, fields=daily_fields)

    funnel_rows = sections.get("ota_funnel") or []
    daily_funnel = _latest_distinct_days(_daily_rows([row for row in funnel_rows if str(row.get("platform") or "").lower() == "meituan"]))
    latest_funnel = daily_funnel[-1] if daily_funnel else {}
    funnel = {key: _sum_keys(daily_funnel, key) for key in ("exposure", "peer_exposure", "views", "peer_views", "paid_orders", "peer_paid_orders")}
    funnel["exposure_to_view_rate"] = None if funnel.get("exposure") in (None, 0) else (funnel.get("views") or 0) / funnel["exposure"]
    funnel["payment_conversion_rate"] = None if funnel.get("views") in (None, 0) else (funnel.get("paid_orders") or 0) / funnel["views"]
    for key in ("peer_exposure_to_view_rate", "peer_payment_conversion_rate"):
        values = [_n(row.get(key)) for row in daily_funnel if _n(row.get(key)) is not None]
        funnel[key] = sum(values) / len(values) if values else None
    for key in ("exposure_rank", "views_rank", "paid_orders_rank", "exposure_to_view_rate_rank", "payment_conversion_rate_rank"):
        funnel[key] = latest_funnel.get(key)
    comparisons = []
    for value_key, peer_key in (("exposure", "peer_exposure"), ("views", "peer_views"),
                                ("exposure_to_view_rate", "peer_exposure_to_view_rate"),
                                ("payment_conversion_rate", "peer_payment_conversion_rate")):
        value, peer = _n(funnel.get(value_key)), _n(funnel.get(peer_key))
        comparisons.append(None if value is None or peer in (None, 0) else value / peer)
    flow_ratio = sum(_score_ratio(v) for v in comparisons) / 4 if all(v is not None for v in comparisons) else None
    flow_fields = []
    labels = (("曝光人数", "exposure"), ("浏览人数", "views"), ("支付订单数", "paid_orders"),
              ("支付转化率", "payment_conversion_rate"), ("曝光-浏览转化率", "exposure_to_view_rate"),
              ("浏览-支付转化率", "payment_conversion_rate"))
    for label, key in labels:
        flow_fields.extend([_field(label, funnel.get(key)), _field(f"{label}同行均值", funnel.get(f"peer_{key}")),
                            _field(f"{label}同行排名", funnel.get(f"{key}_rank"))])
    by_no[4] = _item(4, ITEMS[3][1], 15, True, status="success" if flow_ratio is not None else "pending_rule",
                          ratio=flow_ratio, fields=flow_fields,
                          note="四个子项等权；任一同行均值缺失或为0时不擅自重分配15分。")

    users = _latest(sections.get("user_source_monthly") or [], "period_month", "snapshot_time")
    display_month = str(users.get("period_month") or date.today().strftime("%Y-%m"))[:7]
    by_no[5] = _item(5, ITEMS[4][1], 0, False, status="success" if users else "missing", fields=[
        _field("统计月份", display_month), _field("本地占比", _pct_value(users.get("local_user_pct"))),
        _field("异地占比", _pct_value(users.get("nonlocal_user_pct"))),
        _field("新客占比", _pct_value(users.get("new_user_pct"))),
        _field("老客占比", _pct_value(users.get("returning_user_pct"))),
    ], note="只展示，不参与总分。")

    hos_rows = _latest_distinct_days(_daily_rows([row for row in funnel_rows if str(row.get("platform") or "").lower() == "meituan" and _n(row.get("hos_score")) is not None]))
    hos_values = [_n(row.get("hos_score")) for row in hos_rows]
    hos_avg = sum(v for v in hos_values if v is not None) / len(hos_values) if hos_values else None
    latest_hos = hos_rows[-1] if hos_rows else {}
    hos_rank = _n(latest_hos.get("hos_score_rank"))
    hos_ratio = None
    hos_status = "missing"
    if hos_avg is not None:
        hos_status = "success"
        if hos_avg > 5 and hos_rank is not None and hos_rank <= 3: hos_ratio = 1.0
        elif 4 <= hos_avg <= 5: hos_ratio = .8
        elif hos_avg < 4: hos_ratio = 0.0
        else: hos_status = "pending_rule"
    hos_fields = [_field("展示范围", f"{hos_rows[0].get('business_date')} 至 {hos_rows[-1].get('business_date')}" if hos_rows else None),
                  _field("有效天数", len(hos_rows) if hos_rows else None, "实际取得的日数据条数", "区间统计"),
                  _field("近30天平均分", hos_avg, "日HOS分合计 ÷ 有效天数", "公式计算"),
                  _field("最新同行排名", hos_rank)]
    hos_fields.extend(_field(str(row.get("business_date") or "")[:10], row.get("hos_score"),
                             f"排名 {row.get('hos_score_rank') or '暂无'}") for row in hos_rows)
    by_no[6] = _item(6, ITEMS[5][1], 3, True, status=hos_status, ratio=hos_ratio, fields=hos_fields)

    by_no[7] = _item(7, ITEMS[6][1], 8, True, status="missing", fields=[_field("月扫码订单", None)],
                          note="需求未提供扫码订单数据库表，保持待接入。")

    info = _latest([row for row in funnel_rows if _n(row.get("content_score")) is not None], "business_date")
    info_value = _n(info.get("content_score"))
    info_status, info_ratio = ("zero", 0.0) if info_value is None else ("success", 1.0)
    by_no[8] = _item(8, ITEMS[7][1], 5, True, status=info_status, ratio=info_ratio,
                          fields=[_field("统计日期", info.get("business_date")), _field("信息分", info_value)],
                          note="按本次确认口径：当日信息分有值即满分，无值计0分。")

    finance = sections.get("promotion_finance") or []
    spend_rows = [r for r in finance if str(r.get("transaction_type") or "").strip() == "推广通支出"]
    spend = _sum(spend_rows, "transaction_amount")
    if spend is None: spend = _sum(spend_rows, "amount")
    revenue_row = _latest(sections.get("promotion_revenue") or [], "period_month")
    revenue = _n(revenue_row.get("room_revenue"))
    roi = None if spend in (None, 0) or revenue is None else revenue / spend
    promo_status, promo_ratio = "missing", None
    if spend == 0: promo_status = "zero"
    elif spend is not None and spend <= 1000: promo_status = "pending_rule"
    elif roi is not None:
        promo_status, promo_ratio = "success", (1.0 if roi > 10 else .6 if roi >= 5 else 0.0)
    by_no[9] = _item(9, ITEMS[8][1], 8, True, status=promo_status, ratio=promo_ratio, fields=[
        _field("近30天推广投入", spend, "transaction_type=推广通支出的金额合计", "条件汇总"),
        _field("本月美团EBK订单金额", revenue),
        _field("ROI", roi, "本月美团EBK订单金额 ÷ 近30天推广投入", "公式计算")],
        note="投入金额≤1000元的评分边界未冻结；投入为0时不计算ROI。")

    rights = sections.get("joined_rights") or []
    db_hotel_name = next((r.get("hotel_name") for r in rights if r.get("hotel_name")), None) or hotel_name
    suffix = re.search(r"[（(]([^）)]+)[）)]\s*$", str(db_hotel_name or ""))
    name_status, name_ratio = ("missing", None) if not db_hotel_name else (("success", 0.0) if not suffix else ("pending_rule", None))
    by_no[10] = _item(10, ITEMS[9][1], 3, True, status=name_status, ratio=name_ratio, fields=[
        _field("酒店展示名称", db_hotel_name),
        _field("检测到的后缀", suffix.group(1) if suffix else None, "解析名称末尾括号内容", "文本计算"),
        _field("热门商圈词命中", None)], note="热门商圈词词库尚未提供；有后缀时保持待确认。")

    products = sections.get("products") or []
    room_names = sorted({str(r.get("room_type_name") or "").strip() for r in products if r.get("room_type_name")})
    room_fields = [_field(name, len(name), "", "字符数计算") for name in room_names]
    room_status = "missing" if not room_names else ("success" if any(len(name) < 5 for name in room_names) else "pending_rule")
    room_ratio = 0.0 if room_names and any(len(name) < 5 for name in room_names) else None
    by_no[11] = _item(11, ITEMS[10][1], 4, True, status=room_status, ratio=room_ratio, fields=room_fields,
                           note="名称长度>5且命中卖点才满分；恰好5字、多房型汇总和卖点词库未冻结。")

    losses = sections.get("order_loss_monthly") or []
    loss_fields = []
    for row in losses:
        loss_fields.append(_field(str(row.get("competitor_hotel_name") or "未命名竞对"),
                                  row.get("competitor_loss_order_count"),
                                  f"流失金额 {row.get('competitor_loss_amount')}; 流失房型 {row.get('lost_room_types_text') or '暂无'}; 关注 {row.get('follow_status')}"))
    by_no[12] = _item(12, ITEMS[11][1], 0, False, status="success" if losses else "missing", fields=loss_fields,
                           note="只展示，不参与总分；follow_status 1=已关注，0=未关注。")
    by_no[12]["records"] = losses

    overviews = sections.get("review_overviews") or []
    rep_fields = []
    for platform in ("meituan", "dianping"):
        row = next((r for r in overviews if str(r.get("review_platform") or r.get("platform") or "").lower() == platform), {})
        rep_fields.extend([_field(f"{platform}评分", row.get("rating_avg") or row.get("review_score")),
                           _field(f"{platform}点评条数", row.get("review_count") or row.get("total_review_count")),
                           _field(f"{platform}未回复点评数", row.get("unreplied_review_count"))])
    by_no[13] = _item(13, ITEMS[12][1], 10, True, status="pending_rule" if overviews else "missing", fields=rep_fields,
                           note="两平台评分分别展示；合并评分方法未冻结，暂不生成本项得分。")

    rights_count = len(rights) if rights else None
    if rights_count is None: rights_status, rights_ratio = "missing", None
    elif rights_count > 5: rights_status, rights_ratio = "success", 1.0
    elif rights_count < 3: rights_status, rights_ratio = "success", 0.0
    else: rights_status, rights_ratio = "pending_rule", None
    by_no[14] = _item(14, ITEMS[13][1], 4, True, status=rights_status, ratio=rights_ratio, fields=[
        _field("已报名权益数量", rights_count, "当前权益记录行数", "行数统计"),
        *[_field(str(r.get("right_name") or "未命名权益"), r.get("effective_room_scope")) for r in rights]],
        note="3–5项在手册总表/明细存在冲突，保持待确认。")

    statuses = sections.get("promotion_status") or []
    status_specs = {
        15: ("优美会", "youmeihui", {"优美会", "优美乐"}),
        16: ("商旅专享价", "business_travel_price", {"商旅专享价"}),
        17: ("公益流量", "public_welfare_traffic", {"公益流量"}),
        18: ("钟点房", "hourly_room", {"钟点房"}),
        19: ("酒店亮点", "hotel_highlights", {"酒店亮点"}),
        20: ("预约发票", "reservation_invoice", {"预约发票", "发票", "预约开票"}),
        23: ("自动接单", "auto_order_acceptance", {"自动接单"}),
    }
    for no, (label, promotion_code, name_aliases) in status_specs.items():
        row = next((r for r in statuses if str(r.get("promotion_code") or "").strip().lower() == promotion_code), {})
        if not row:
            row = next((r for r in statuses if str(r.get("promotion_name") or "").strip() in name_aliases), {})
        st, sr, meaning = _status_score(row)
        by_no[no] = _item(no, ITEMS[no - 1][1], ITEMS[no - 1][2], True, status=st, ratio=sr, fields=[
            _field("开通状态", row.get("status")), _field("报名状态", row.get("enroll_status") or row.get("registration_status")),
            _field("生效状态", row.get("effective_status")), _field("状态含义", meaning)])

    videos = sections.get("video_upload_status") or []
    video_fields = []
    hotel_video = None
    labels = {"room_type_video": "房型视频", "hotel_preview_video": "酒店预览视频", "room_type_preview_video": "房型预览视频"}
    for kind, label in labels.items():
        row = next((r for r in videos if str(r.get("video_type") or "") == kind), {})
        uploaded, required = _n(row.get("uploaded_count")), _n(row.get("required_count"))
        video_fields.append(_field(label, uploaded, f"需上传 {required if required is not None else '暂无'}"))
        if kind == "hotel_preview_video": hotel_video = uploaded
    video_status, video_ratio = ("missing", None) if hotel_video is None else ("success", 1.0) if hotel_video > 0 else ("zero", 0.0)
    by_no[21] = _item(21, ITEMS[20][1], 1, True, status=video_status, ratio=video_ratio, fields=video_fields,
                           note="首页视频评分以 hotel_preview_video 的 uploaded_count 是否大于0判定。")
    by_no[22] = _item(22, ITEMS[21][1], 1, True, status="manual_pending", fields=[_field("挂冠类型", None)],
                           note="人工录入项；未录入不等于无挂冠。")

    ordered = [by_no.get(no) or _item(no, name, base, participates) for no, name, base, participates in ITEMS]
    for item in ordered:
        table, fields = SOURCE_MAP.get(int(item["standard_item_id"]), ("待确认", []))
        item["source_table"] = table
        item["source_fields"] = fields
    raw_score = round(sum(x["item_score"] for x in ordered if x["item_score"] is not None), 2)
    connected_base = sum(x["base_score"] for x in ordered if x["participates_in_score"] and x["item_score"] is not None)
    normalized = round(raw_score / connected_base * 100, 2) if connected_base else None
    return {"items": ordered, "raw_score": raw_score, "connected_base_score": connected_base,
            "normalized_score": normalized, "rule_version": "2026-07-13"}
