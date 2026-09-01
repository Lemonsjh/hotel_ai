from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Mapping, Sequence

_PATCH_VERSION = "s15-s16-attachment-data-rules.v1"
_INSTALLED = False

_MATURITY_ORDER = {
    "unavailable": -1,
    "trend_only": 0,
    "weak": 1,
    "temporary": 2,
    "stable": 3,
    "strong": 4,
}
_MATURITY_LABELS = {
    "trend_only": "仅作趋势参考",
    "weak": "低",
    "temporary": "一般",
    "stable": "较高",
    "strong": "高",
}
_STATUS_LABELS = {
    "severe_slow": "严重滞后",
    "significant_slow": "明显滞后",
    "slow": "略慢",
    "normal": "正常",
    "fast": "略快",
    "significant_fast": "明显超前",
}


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: Any, digits: int = 0) -> str:
    number = _number(value)
    return "" if number is None else f"{number * 100:.{digits}f}%"


def _num(value: Any, digits: int = 1) -> str:
    number = _number(value)
    if number is None:
        return ""
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _money(value: Any) -> str:
    number = _number(value)
    if number is None:
        return ""
    return f"¥{number:,.0f}"


def _status(value: Any) -> str:
    return _STATUS_LABELS.get(str(value or ""), str(value or ""))


def _maturity(value: Any) -> str:
    return _MATURITY_LABELS.get(str(value or ""), str(value or ""))


def _week_type(context: Mapping[str, Any], weekday: int) -> bool:
    if context.get("is_adjusted_workday"):
        return False
    if context.get("is_workday") is not None:
        return not bool(context.get("is_workday"))
    if context.get("is_weekend") is not None:
        return bool(context.get("is_weekend"))
    return weekday >= 5


def _same_holiday(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_flag = bool(left.get("is_holiday"))
    right_flag = bool(right.get("is_holiday"))
    if left_flag != right_flag:
        return False
    if not left_flag:
        return True
    left_group = str(left.get("holiday_group") or left.get("holiday_name") or "")
    right_group = str(right.get("holiday_group") or right.get("holiday_name") or "")
    return bool(left_group) and left_group == right_group


def select_platform_dates(
    target_date: str,
    available_dates: Sequence[str],
    date_contexts: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[str, list[str]]:
    target = dt.date.fromisoformat(str(target_date)[:10])
    contexts = date_contexts or {}
    target_context = contexts.get(target.isoformat()) or {}
    dates = sorted(
        {
            dt.date.fromisoformat(str(value)[:10])
            for value in available_dates
            if value and str(value)[:10] < target.isoformat()
        },
        reverse=True,
    )

    def context(day: dt.date) -> Mapping[str, Any]:
        return contexts.get(day.isoformat()) or {}

    if target_context.get("season_tag"):
        m1 = [
            day
            for day in dates
            if context(day).get("season_tag") == target_context.get("season_tag")
            and _same_holiday(context(day), target_context)
            and day.weekday() == target.weekday()
        ]
        if m1:
            return "M1_season_holiday_weekday", [day.isoformat() for day in m1]
        target_week_type = _week_type(target_context, target.weekday())
        m2 = [
            day
            for day in dates
            if context(day).get("season_tag") == target_context.get("season_tag")
            and _same_holiday(context(day), target_context)
            and _week_type(context(day), day.weekday()) == target_week_type
        ]
        if m2:
            return "M2_season_holiday_week_type", [day.isoformat() for day in m2]
        m3 = [
            day
            for day in dates
            if context(day).get("season_tag") == target_context.get("season_tag")
            and _same_holiday(context(day), target_context)
        ]
        if m3:
            return "M3_season_holiday", [day.isoformat() for day in m3]
    m4 = [day for day in dates if day.weekday() == target.weekday()]
    if m4:
        return "M4_same_weekday", [day.isoformat() for day in m4]
    target_week_type = _week_type(target_context, target.weekday())
    m5 = [
        day
        for day in dates
        if _same_holiday(context(day), target_context)
        and _week_type(context(day), day.weekday()) == target_week_type
    ]
    if m5:
        return "M5_same_week_type", [day.isoformat() for day in m5]
    return "unavailable", []


def platform_maturity(sample_count: int) -> str:
    if sample_count < 3:
        return "trend_only"
    if sample_count < 7:
        return "weak"
    if sample_count < 14:
        return "temporary"
    if sample_count < 30:
        return "weak"
    return "stable"


def cap_maturity(value: Any, cap: str) -> str:
    current = str(value or "trend_only")
    return current if _MATURITY_ORDER.get(current, 0) <= _MATURITY_ORDER.get(cap, 0) else cap


def collector_health(points: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    observed = []
    missing = []
    for hour in range(24):
        point = next((item for item in points if item.get("hour") == hour), None) or {}
        capacity_count = int(((point.get("capacity") or {}).get("sample_count")) or 0)
        completion_count = int(((point.get("target_completion") or {}).get("sample_count")) or 0)
        (observed if max(capacity_count, completion_count) > 0 else missing).append(hour)
    ratio = len(observed) / 24
    if ratio < 0.40:
        maturity = "trend_only"
    elif ratio < 0.75:
        maturity = "weak"
    else:
        maturity = "temporary"
    return {
        "expected_hour_slots": 24,
        "observed_hour_slots": observed,
        "missing_hour_slots": missing,
        "collector_coverage_ratio": ratio,
        "object_maturity": maturity,
    }


class _CaptureRepository:
    def __init__(self, delegate: Any):
        self.delegate = delegate
        self.price_rows: list[dict[str, Any]] = []
        self.metric_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def room_revenue(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        rows = list(self.delegate.room_revenue(*args, **kwargs))
        self.price_rows = [dict(row) for row in rows]
        return rows

    def ota_business_metrics(
        self, platform: str, *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:
        rows = list(self.delegate.ota_business_metrics(platform, *args, **kwargs))
        self.metric_rows[str(platform)] = [dict(row) for row in rows]
        return rows


def _strict_room_daily(
    self: Any,
    hotel_id: str,
    start_date: str,
    end_date: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    return self._query(
        """
        SELECT * FROM (
          SELECT hotel_id, business_date, room_type_id, room_type_name,
                 pms_room_type_id, pms_rate_room_type_id, room_nights,
                 occupancy_rate, room_revenue, adr, revpar, snapshot_time,
                 ROW_NUMBER() OVER (
                   PARTITION BY hotel_id, business_date, room_type_id
                   ORDER BY snapshot_time DESC
                 ) AS rn
          FROM jl01_room_type_performance_daily
          WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
            AND room_type_id IS NOT NULL AND room_type_id<>''
            AND snapshot_time<=%s
        ) ranked WHERE rn=1
        """,
        (hotel_id, start_date, end_date, as_of_datetime),
    )


def _strict_hourly_facts(
    rows: Sequence[Mapping[str, Any]],
    selected_dates: Sequence[str],
) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], tuple[str, ...]]:
    from runtime.sales_progress.core import (
        calculate_room_fact,
        date_part,
        expected_room_type_set,
        select_complete_batch,
    )

    expected = expected_room_type_set(rows)
    if not expected:
        return {}, ()
    result: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for day in selected_dates:
        day_rows = [row for row in rows if date_part(row.get("stay_date")) == day]
        for hour in range(24):
            selected = select_complete_batch(
                day_rows,
                expected_room_types=expected,
                requested_hour=hour,
            )
            if selected.complete and selected.rows:
                result[(day, hour)] = [
                    calculate_room_fact(row) for row in selected.rows
                ]
    return result, expected


def _postprocess_baseline(
    payload: dict[str, Any],
    capture: _CaptureRepository,
    *,
    target_date: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    from runtime.sales_progress.metrics import build_metric_baselines, build_price_baselines
    from runtime.sales_progress.repository import CTRIP_METRICS, MEITUAN_METRICS

    if payload.get("status") != "ok":
        payload["spec_alignment_version"] = _PATCH_VERSION
        return payload

    selected_dates = set(str(day) for day in (payload.get("selected_dates") or []))
    price_rows = [
        row for row in capture.price_rows if _date(row.get("business_date")) in selected_dates
    ]
    prices = build_price_baselines(price_rows)
    for room_id, room in (payload.get("room_types") or {}).items():
        room["price_baseline"] = prices.get(str(room_id), {"status": "unavailable"})

    registries = {
        "meituan": MEITUAN_METRICS,
        "ctrip": CTRIP_METRICS,
    }
    ota: dict[str, Any] = {}
    for platform, registry in registries.items():
        rows = capture.metric_rows.get(platform) or []
        available_dates = [
            _date(row.get("business_date")) for row in rows if _date(row.get("business_date"))
        ]
        tier, metric_dates = select_platform_dates(
            target_date, available_dates, date_contexts
        )
        metric_date_set = set(metric_dates)
        filtered = [
            row for row in rows if _date(row.get("business_date")) in metric_date_set
        ]
        baseline = build_metric_baselines(filtered, registry, platform)
        baseline["selected_tier"] = tier
        baseline["selected_dates"] = metric_dates
        baseline["history_day_count"] = len(baseline.get("daily_points") or [])
        baseline["maturity"] = platform_maturity(baseline["history_day_count"])
        ota[platform] = baseline
    payload["ota_baselines"] = ota

    hotel = payload.get("hotel") or {}
    health = collector_health(hotel.get("hourly_points") or [])
    hotel["baseline_health"] = health
    cap = str(health["object_maturity"])
    for point in hotel.get("hourly_points") or []:
        point["maturity"] = cap_maturity(point.get("maturity"), cap)
    for room in (payload.get("room_types") or {}).values():
        room_health = collector_health(room.get("hourly_points") or [])
        room["baseline_health"] = room_health
        room_cap = str(room_health["object_maturity"])
        for point in room.get("hourly_points") or []:
            point["maturity"] = cap_maturity(point.get("maturity"), room_cap)

    payload["spec_alignment_version"] = _PATCH_VERSION
    payload["user_visible_policy"] = {
        "hide_semantically_unavailable_families": True,
        "retain_low_sample_and_incomplete_coverage": True,
        "do_not_use_jy01_room_dimension_as_jl01_substitute": True,
    }
    return payload


def _nearest_point(
    points: Sequence[Mapping[str, Any]], hour: int
) -> Mapping[str, Any] | None:
    exact = next((item for item in points if item.get("hour") == hour), None)
    if exact and max(
        int(((exact.get("capacity") or {}).get("sample_count")) or 0),
        int(((exact.get("target_completion") or {}).get("sample_count")) or 0),
    ) > 0:
        return exact
    earlier = [
        item
        for item in points
        if isinstance(item.get("hour"), int)
        and int(item["hour"]) <= hour
        and max(
            int(((item.get("capacity") or {}).get("sample_count")) or 0),
            int(((item.get("target_completion") or {}).get("sample_count")) or 0),
        )
        > 0
    ]
    return max(earlier, key=lambda item: int(item["hour"])) if earlier else None


def _as_of_hour(value: Any) -> int:
    text = str(value or "")
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).hour
    except ValueError:
        return 23


def _distribution_text(distribution: Mapping[str, Any], *, digits: int = 0) -> str:
    median = _pct(distribution.get("median"), digits)
    if not median:
        return ""
    p25 = _pct(distribution.get("p25"), digits)
    p80 = _pct(distribution.get("p80"), digits)
    count = int(distribution.get("sample_count") or 0)
    band = f"（{p25}–{p80}）" if p25 and p80 else ""
    return f"{median}{band}，样本{count}天"


def _metric_line(
    platform: Mapping[str, Any],
    label: str,
    fields: Sequence[tuple[str, str, bool]],
) -> str | None:
    parts = []
    baselines = platform.get("baselines") or {}
    for key, name, percent in fields:
        median = ((baselines.get(key) or {}).get("median"))
        if median is None:
            continue
        parts.append(
            f"{name}{_pct(median, 1) if percent else _num(median)}"
        )
    if not parts:
        return None
    sample_count = int(platform.get("history_day_count") or 0)
    maturity = _maturity(platform.get("maturity"))
    return f"- {label}：" + "；".join(parts) + f"；样本{sample_count}天，成熟度{maturity}。"


def build_s15_user_message(payload: Mapping[str, Any]) -> str:
    if payload.get("status") != "ok":
        return "S15 销售基准暂不可用。"

    hotel = payload.get("hotel") or {}
    points = hotel.get("hourly_points") or []
    target = _number(hotel.get("effective_target_room_nights"))
    revenue = _number((hotel.get("historical_revenue_target") or {}).get("median"))
    target_date = payload.get("target_date") or payload.get("business_date") or "-"
    selected_dates = payload.get("selected_dates") or []
    health = hotel.get("baseline_health") or collector_health(points)
    lines = [f"S15 销售基准（{target_date}，真实数据库）"]
    header_parts = []
    if target is not None:
        header_parts.append(
            f"历史同类日参考最终已售{_num(target)}间（历史中位数，非人工目标）"
        )
    if revenue is not None:
        header_parts.append(f"参考收入{_money(revenue)}")
    header_parts.append(f"选中{len(selected_dates)}个同类历史日期")
    lines.append("参考口径：" + "；".join(header_parts) + "。")
    lines.append(
        f"基准健康：24小时中{len(health.get('observed_hour_slots') or [])}个时点有真实样本，"
        f"整体成熟度{_maturity(health.get('object_maturity'))}。"
    )

    lines.extend(["", "一、全店24小时销售节奏"])
    for point in points:
        hour = point.get("hour")
        if not isinstance(hour, int):
            continue
        capacity = point.get("capacity") or {}
        completion = point.get("target_completion") or {}
        capacity_text = _distribution_text(capacity)
        completion_text = _distribution_text(completion)
        if not capacity_text and not completion_text:
            continue
        parts = []
        if capacity_text:
            parts.append(f"容量节奏{capacity_text}")
        if completion_text:
            parts.append(f"参考完成节奏{completion_text}")
            if target is not None and _number(completion.get("median")) is not None:
                expected = target * float(completion["median"])
                parts.append(f"折算应售{_num(expected)}间")
        lines.append(f"- {hour:02d}时：" + "；".join(parts) + "。")
    missing = health.get("missing_hour_slots") or []
    if missing:
        lines.append(
            "- 缺少真实小时样本："
            + "、".join(f"{int(hour):02d}时" for hour in missing)
            + "；不插值、不补零。"
        )

    lines.extend(["", "二、房型基准（当前时点）"])
    current_hour = _as_of_hour(payload.get("as_of_datetime"))
    room_lines = 0
    for room_id, room in sorted((payload.get("room_types") or {}).items(), key=lambda item: str(item[0])):
        point = _nearest_point(room.get("hourly_points") or [], current_hour)
        if not point:
            continue
        capacity = point.get("capacity") or {}
        completion = point.get("target_completion") or {}
        price = room.get("price_baseline") or {}
        parts = []
        capacity_text = _distribution_text(capacity)
        completion_text = _distribution_text(completion)
        if capacity_text:
            parts.append(f"容量节奏{capacity_text}")
        if completion_text:
            parts.append(f"参考完成节奏{completion_text}")
        room_target = _number(room.get("effective_target_room_nights"))
        if room_target is not None:
            parts.append(f"参考最终已售{_num(room_target)}间")
        if _number(price.get("median")) is not None:
            price_parts = []
            if _number(price.get("p20")) is not None:
                price_parts.append(f"P20 {_money(price.get('p20'))}")
            price_parts.append(f"中位{_money(price.get('median'))}")
            if _number(price.get("p80")) is not None:
                price_parts.append(f"P80 {_money(price.get('p80'))}")
            parts.append("成交价" + "、".join(price_parts))
        if not parts:
            continue
        room_name = room.get("room_type_name") or room.get("room_type_id") or room_id
        observed_hour = point.get("hour")
        lines.append(f"- {room_name}（{int(observed_hour):02d}时）：{'；'.join(parts)}。")
        room_lines += 1
    if room_lines == 0:
        lines.pop()
        lines.pop()

    platform_lines = []
    ota = payload.get("ota_baselines") or {}
    mt = _metric_line(
        ota.get("meituan") or {},
        "美团",
        (
            ("browse_uv", "浏览人数中位", False),
            ("first_conversion", "曝光到浏览", True),
            ("second_conversion", "浏览到支付", True),
        ),
    )
    ct = _metric_line(
        ota.get("ctrip") or {},
        "携程",
        (
            ("detail_visitor_count", "详情访客中位", False),
            ("list_to_detail_ratio", "列表曝光到详情", True),
            ("detail_to_submit_ratio", "详情到提交", True),
        ),
    )
    if mt:
        platform_lines.append(mt)
    if ct:
        platform_lines.append(ct)
    if platform_lines:
        lines.extend(["", "三、平台流量与转化基准", *platform_lines])

    return "\n".join(lines)


def _line_parts(line: Mapping[str, Any], label: str) -> str | None:
    if _number(line.get("actual_progress")) is None or _number(line.get("baseline_median")) is None:
        return None
    parts = [
        f"{label}：当前{_pct(line.get('actual_progress'), 1)}",
        f"历史同时点{_pct(line.get('baseline_median'), 1)}",
    ]
    if _number(line.get("baseline_p25")) is not None and _number(line.get("baseline_p80")) is not None:
        parts.append(
            f"常见区间{_pct(line.get('baseline_p25'), 1)}–{_pct(line.get('baseline_p80'), 1)}"
        )
    if _number(line.get("delta_pp")) is not None:
        delta = float(line["delta_pp"])
        parts.append(f"偏差{'+' if delta > 0 else ''}{delta:.1f}个百分点")
    if _number(line.get("expected_sold")) is not None:
        parts.append(f"同时点应售{_num(line.get('expected_sold'))}间")
    if _number(line.get("room_gap")) is not None:
        gap = float(line["room_gap"])
        parts.append(f"较参考{'多' if gap >= 0 else '少'}{_num(abs(gap))}间")
    status = _status(line.get("status"))
    if status:
        parts.append(status)
    return "；".join(parts)


def build_s16_user_message(report: Mapping[str, Any]) -> str:
    if report.get("status") not in {"ok", "partial"}:
        return "S16 销售进度暂不可判断。"

    hotel = report.get("hotel_result") or {}
    target_date = report.get("target_date") or "-"
    as_of = str(report.get("as_of_datetime") or "-")
    time_text = as_of[11:16] if len(as_of) >= 16 else as_of
    actual = _number(hotel.get("committed_sold"))
    total = _number(hotel.get("total_rooms"))
    target = _number(hotel.get("effective_target_room_nights"))
    header = []
    if actual is not None and total is not None:
        header.append(f"当前承诺已售{_num(actual)}/{_num(total)}间")
    if target is not None:
        header.append(f"历史同类日参考最终已售{_num(target)}间")
    lines = [
        f"S16 销售进度（{target_date}，截至{time_text}，真实数据库）",
        "；".join(header) + "。承诺已售是销售承诺口径，不等同于物理在住房。",
        "",
        "一、全店双线",
    ]
    capacity_text = _line_parts(hotel.get("capacity_line") or {}, "容量节奏")
    target_text = _line_parts(hotel.get("target_line") or {}, "参考完成节奏")
    if capacity_text:
        lines.append("- " + capacity_text + "。")
    if target_text:
        lines.append("- " + target_text + "。")
    statuses = [
        _status((hotel.get("capacity_line") or {}).get("status")),
        _status((hotel.get("target_line") or {}).get("status")),
    ]
    statuses = [value for value in statuses if value]
    if statuses:
        if len(set(statuses)) == 1:
            lines.append(f"- 综合：两条可用节奏线均为{statuses[0]}。")
        else:
            lines.append(f"- 综合：容量线{statuses[0]}，参考完成线{statuses[-1]}。")

    room_lines = []
    for row in report.get("room_type_results") or []:
        room_name = row.get("room_type_name") or row.get("room_type_id")
        parts = []
        cap = _line_parts(row.get("capacity_line") or {}, "容量")
        target_line = _line_parts(row.get("target_line") or {}, "参考完成")
        if cap:
            parts.append(cap)
        if target_line:
            parts.append(target_line)
        if not parts:
            continue
        room_lines.append(f"- {room_name}：" + "；".join(parts) + "。")
    if room_lines:
        lines.extend(["", "二、房型进度", *room_lines])

    structure = report.get("structure_summary") or {}
    structure_lines = []
    capacity_available = int(structure.get("capacity_line_available_count") or 0)
    if capacity_available:
        structure_lines.append(
            f"- 容量线可判断{capacity_available}个房型："
            f"滞后{int(structure.get('capacity_slow_room_type_count') or 0)}个，"
            f"超前{int(structure.get('capacity_fast_room_type_count') or 0)}个。"
        )
    target_available = int(structure.get("target_line_available_count") or 0)
    if target_available:
        structure_lines.append(
            f"- 参考完成线可判断{target_available}个房型："
            f"滞后{int(structure.get('target_slow_room_type_count') or 0)}个，"
            f"超前{int(structure.get('target_fast_room_type_count') or 0)}个。"
        )
    labels = structure.get("labels") or structure.get("structure_labels") or []
    label_map = {
        "broad_based_slowdown": "多数房型普遍滞后",
        "room_type_structural_lag": "重要房型存在结构性滞后",
        "mix_offset_detected": "快慢房型相互抵消",
    }
    visible_labels = [label_map.get(str(item), "") for item in labels]
    visible_labels = [item for item in visible_labels if item]
    if visible_labels:
        structure_lines.append("- 结构判断：" + "；".join(visible_labels) + "。")
    if structure_lines:
        lines.extend(["", "三、结构", *structure_lines])

    gap = report.get("checkpoint_gap_minutes")
    if gap is not None:
        lines.extend(["", f"数据时效：完整房型批次距请求约{int(gap)}分钟。"])
    lines.append("结果只说明销售节奏与房型结构，不直接推断满房，也不直接触发调价或推广。")
    return "\n".join(lines)


def build_ai_response_contract(result: Mapping[str, Any]) -> dict[str, Any]:
    intent = str(result.get("intent") or "")
    if intent == "sales_baseline_demo":
        room_ids = sorted(str(key) for key in (result.get("room_types") or {}))
        required_sections = ["参考口径", "全店24小时节奏", "全部可用房型基准"]
    else:
        room_ids = sorted(
            str(row.get("room_type_id"))
            for row in (result.get("room_type_results") or [])
            if row.get("room_type_id")
        )
        required_sections = ["全店双线", "全部可用房型进度", "可用结构判断"]
    return {
        "mode": "single_pass_ai_business_analysis",
        "facts_are_authoritative": True,
        "maximum_runtime_tool_calls": 1,
        "additional_database_queries_allowed": False,
        "second_verification_pass_allowed": False,
        "required_sections": required_sections,
        "required_room_type_ids": room_ids,
        "must_preserve_every_room_type_with_available_facts": True,
        "must_preserve_all_available_hour_slots": True,
        "retain_low_sample_and_incomplete_coverage": True,
        "hide_semantically_unavailable_families": True,
        "must_not_mention": [
            "市场总订单基准不可用",
            "市场份额基准不可用",
            "稳定市场转化不可用",
            "引流价排名基准不可用",
            "参考完成线可判断0个",
            "各房型参考最终已售暂不可用",
        ],
        "forbidden": [
            "修改事实数字或单位",
            "把房量换算成订单数",
            "把容量节奏和参考完成节奏合并",
            "省略有可用事实的房型",
            "省略已有真实小时样本或采集覆盖缺口",
            "从JY01任意非总计维度替代JL01房型日终",
            "再次查库或重跑能力",
        ],
        "fallback": "无法完整遵守时原样发送authoritative_fallback_text",
        "contract_version": _PATCH_VERSION,
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.sales_progress import baseline_service, deviation_service, presentation, repository, service
    import runtime.sales_progress as package
    from runtime.decisions import baseline as baseline_decision
    from runtime import s15_s16_ai_analysis_patch

    repository.DirectSalesProgressRepository.room_daily = _strict_room_daily
    baseline_service._hourly_facts = _strict_hourly_facts

    original_build = baseline_service.build_baseline

    def aligned_build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        delegate = args[0] if args else kwargs.get("repository")
        capture = _CaptureRepository(delegate)
        if args:
            call_args = (capture, *args[1:])
            call_kwargs = kwargs
        else:
            call_args = ()
            call_kwargs = dict(kwargs)
            call_kwargs["repository"] = capture
        payload = dict(original_build(*call_args, **call_kwargs))
        return _postprocess_baseline(
            payload,
            capture,
            target_date=str(kwargs.get("target_date") or payload.get("target_date")),
            date_contexts=kwargs.get("date_contexts"),
        )

    baseline_service.build_baseline = aligned_build
    service._build_baseline = aligned_build
    deviation_service.build_baseline = aligned_build
    package.build_baseline = service.build_baseline
    baseline_decision.build_baseline = service.build_baseline

    previous_cached = baseline_decision._cached_baseline

    def cached(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        payload = previous_cached(*args, **kwargs)
        if payload is not None and payload.get("spec_alignment_version") != _PATCH_VERSION:
            return None
        return payload

    baseline_decision._cached_baseline = cached

    presentation.build_s15_user_message = build_s15_user_message
    presentation.build_s16_user_message = build_s16_user_message
    s15_s16_ai_analysis_patch.build_ai_response_contract = build_ai_response_contract
