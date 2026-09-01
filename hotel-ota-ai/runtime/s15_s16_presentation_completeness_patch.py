from __future__ import annotations

from typing import Any, Mapping, Sequence

_VERSION = "s15-s16-presentation-completeness.v1"
_INSTALLED = False
_THRESHOLDS = {
    "severe_slow_max_pp": -25.0,
    "significant_slow_max_pp": -15.0,
    "slow_max_pp": -8.0,
    "normal_max_pp_exclusive": 8.0,
    "fast_max_pp_exclusive": 15.0,
    "significant_fast_min_pp": 15.0,
    "structure_slow_target_share": 0.50,
    "structure_important_room_share": 0.15,
}
_STATUS = {
    "severe_slow": "严重滞后",
    "significant_slow": "明显滞后",
    "slow": "偏慢",
    "normal": "正常",
    "fast": "偏快",
    "significant_fast": "明显超前",
}
_MATURITY = {
    "trend_only": "趋势参考",
    "weak": "低",
    "temporary": "一般",
    "stable": "较高",
    "strong": "高",
}


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any, digits: int = 1) -> str:
    number = _n(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _pct(value: Any, digits: int = 1) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.{digits}f}%"


def _pp(value: Any) -> str:
    number = _n(value)
    if number is None:
        return "—"
    return f"{number:+.1f}pp"


def _money(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"¥{number:,.0f}"


def _band(distribution: Mapping[str, Any], digits: int = 1) -> str:
    median = _n(distribution.get("median"))
    if median is None:
        return "—"
    p25 = _n(distribution.get("p25"))
    p80 = _n(distribution.get("p80"))
    value = _pct(median, digits)
    if p25 is not None and p80 is not None:
        value += f"〔{_pct(p25, digits)}–{_pct(p80, digits)}〕"
    return value


def _pickup_text(distribution: Mapping[str, Any]) -> str:
    median = _n(distribution.get("median"))
    if median is None:
        return "—"
    p25 = _n(distribution.get("p25"))
    p80 = _n(distribution.get("p80"))
    value = f"{median:+.1f}间"
    if p25 is not None and p80 is not None:
        value += f"〔{p25:+.1f}–{p80:+.1f}〕"
    return value


def _compress_hours(values: Sequence[int]) -> str:
    hours = sorted({int(value) for value in values})
    if not hours:
        return "无"
    groups: list[tuple[int, int]] = []
    start = end = hours[0]
    for hour in hours[1:]:
        if hour == end + 1:
            end = hour
        else:
            groups.append((start, end))
            start = end = hour
    groups.append((start, end))
    return "、".join(
        f"{start:02d}:00"
        if start == end
        else f"{start:02d}:00–{end:02d}:00"
        for start, end in groups
    )


def add_pickup_baselines(
    selected_dates: Sequence[str],
    hourly: Mapping[tuple[str, int], Sequence[Mapping[str, Any]]],
    hotel: dict[str, Any],
    rooms: Mapping[str, dict[str, Any]],
) -> None:
    from runtime.sales_progress.core import aggregate_hotel, as_float, summarize

    def observed_hour(facts: Sequence[Mapping[str, Any]]) -> int | None:
        if not facts:
            return None
        value = facts[0].get("source_observed_hour")
        return int(value) if value is not None else None

    for hour in range(24):
        hotel_values: list[float] = []
        room_values: dict[str, list[float]] = {
            str(room_id): [] for room_id in rooms
        }
        if hour > 0:
            for day in selected_dates:
                earlier = list(hourly.get((day, hour - 1), []))
                current = list(hourly.get((day, hour), []))
                if not earlier or not current:
                    continue
                earlier_observed = observed_hour(earlier)
                current_observed = observed_hour(current)
                if (
                    earlier_observed is None
                    or current_observed is None
                    or current_observed != earlier_observed + 1
                ):
                    continue
                left = as_float(
                    aggregate_hotel(earlier).get("committed_sold")
                )
                right = as_float(
                    aggregate_hotel(current).get("committed_sold")
                )
                if left is not None and right is not None:
                    hotel_values.append(right - left)
                earlier_by_room = {
                    str(row.get("room_type_id")): row
                    for row in earlier
                    if row.get("room_type_id")
                }
                current_by_room = {
                    str(row.get("room_type_id")): row
                    for row in current
                    if row.get("room_type_id")
                }
                for room_id in room_values:
                    left_row = earlier_by_room.get(room_id) or {}
                    right_row = current_by_room.get(room_id) or {}
                    left_value = as_float(left_row.get("committed_sold"))
                    right_value = as_float(right_row.get("committed_sold"))
                    if left_value is not None and right_value is not None:
                        room_values[room_id].append(
                            right_value - left_value
                        )
        hotel_point = next(
            (
                point
                for point in hotel.get("hourly_points") or []
                if point.get("hour") == hour
            ),
            None,
        )
        if hotel_point is not None:
            hotel_point["pickup"] = summarize(hotel_values)
            hotel_point["pickup_interval"] = (
                f"{hour - 1:02d}:00→{hour:02d}:00" if hour else None
            )
        for room_id, room in rooms.items():
            point = next(
                (
                    item
                    for item in room.get("hourly_points") or []
                    if item.get("hour") == hour
                ),
                None,
            )
            if point is not None:
                point["pickup"] = summarize(
                    room_values.get(str(room_id), [])
                )
                point["pickup_interval"] = (
                    f"{hour - 1:02d}:00→{hour:02d}:00"
                    if hour
                    else None
                )


def _point_at_or_before(
    points: Sequence[Mapping[str, Any]],
    hour: int,
) -> Mapping[str, Any] | None:
    exact = next(
        (
            point
            for point in points
            if isinstance(point.get("hour"), int)
            and int(point["hour"]) == hour
        ),
        None,
    )
    if exact:
        return exact
    earlier = [
        point
        for point in points
        if isinstance(point.get("hour"), int)
        and int(point["hour"]) <= hour
    ]
    return (
        max(earlier, key=lambda point: int(point["hour"]))
        if earlier
        else None
    )


def enrich_deviation(
    report: Mapping[str, Any],
    baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(report)
    if result.get("status") not in {"ok", "partial"}:
        return result

    hotel = dict(result.get("hotel_result") or {})
    total = _n(hotel.get("total_rooms"))
    available = _n(hotel.get("available_rooms"))
    committed = _n(hotel.get("committed_sold"))
    overbooking = _n(hotel.get("overbooking_rooms")) or 0.0
    hotel["remaining_sellable_rooms"] = available
    hotel["overbooking_risk"] = bool(
        overbooking > 0
        or (
            total not in (None, 0)
            and committed is not None
            and committed > total
        )
    )
    hotel["overbooking_committed_rooms"] = overbooking

    comparison_hour = int(
        result.get("observed_hour")
        if result.get("observed_hour") is not None
        else result.get("requested_hour") or 0
    )
    baseline = baseline or {}
    hotel_point = _point_at_or_before(
        ((baseline.get("hotel") or {}).get("hourly_points") or []),
        comparison_hour,
    )
    if hotel_point:
        hotel["capacity_maturity"] = hotel_point.get("capacity_maturity")
        hotel["target_completion_maturity"] = hotel_point.get(
            "target_completion_maturity"
        )
        hotel["capacity_confidence"] = hotel_point.get(
            "capacity_confidence"
        )
        hotel["target_completion_confidence"] = hotel_point.get(
            "target_completion_confidence"
        )

    baseline_rooms = baseline.get("room_types") or {}
    enriched_rooms: list[dict[str, Any]] = []
    for source in result.get("room_type_results") or []:
        row = dict(source)
        room_id = str(row.get("room_type_id") or "")
        room_baseline = baseline_rooms.get(room_id) or {}
        point = _point_at_or_before(
            room_baseline.get("hourly_points") or [],
            comparison_hour,
        )
        if point:
            row["capacity_maturity"] = point.get("capacity_maturity")
            row["target_completion_maturity"] = point.get(
                "target_completion_maturity"
            )
            row["capacity_confidence"] = point.get(
                "capacity_confidence"
            )
            row["target_completion_confidence"] = point.get(
                "target_completion_confidence"
            )
            row["maturity"] = point.get("combined_maturity") or point.get(
                "maturity"
            )
        enriched_rooms.append(row)

    result["hotel_result"] = hotel
    result["room_type_results"] = enriched_rooms
    result["thresholds_used"] = dict(_THRESHOLDS)
    result["presentation_version"] = _VERSION
    return result


def _tier_label(value: Any) -> str:
    labels = {
        "P0_previous_year_approved_window": "上年批准可比窗口",
        "P1_season_holiday_weekday": "同季节·同节假日·同星期",
        "P2_season_holiday_week_type": "同季节·同节假日·同工作日类型",
        "P3_season_holiday": "同季节·同节假日",
        "P4_same_weekday": "同星期",
        "P5_same_week_type": "同工作日类型",
        "P5_cold_start": "冷启动宽口径",
        "M1_season_holiday_weekday": "同季节·同节假日·同星期",
        "M2_season_holiday_week_type": "同季节·同节假日·同工作日类型",
        "M3_season_holiday": "同季节·同节假日",
        "M4_same_weekday": "同星期",
        "M5_same_week_type": "同工作日类型",
        "unavailable": "无可比日期",
    }
    text = str(value or "")
    return labels.get(text, text or "未标注")


def _gap_phrase(value: Any, *, unit: str = "间") -> str:
    number = _n(value)
    if number is None:
        return "—"
    if abs(number) < 1e-9:
        return f"与检查点一致（0{unit}）"
    return (
        f"检查点领先 {_num(abs(number))}{unit}"
        if number > 0
        else f"检查点落后 {_num(abs(number))}{unit}"
    )


def _remaining_phrase(value: Any) -> str:
    number = _n(value)
    if number is None:
        return "—"
    if abs(number) < 1e-9:
        return "已达到参考终值"
    return (
        f"距参考终值还差 {_num(number)}间"
        if number > 0
        else f"已超过参考终值 {_num(abs(number))}间"
    )


def _s15_hour_lines(
    point: Mapping[str, Any],
    target: float | None,
) -> list[str]:
    capacity = point.get("capacity") or {}
    completion = point.get("target_completion") or {}
    pickup = point.get("pickup") or {}
    if (
        _n(capacity.get("median")) is None
        and _n(completion.get("median")) is None
    ):
        return []
    hour = int(point.get("hour") or 0)
    first: list[str] = []
    if _n(capacity.get("median")) is not None:
        first.append(f"容量 {_band(capacity)}")
    if _n(completion.get("median")) is not None:
        completion_text = f"完成 {_band(completion)}"
        if target is not None:
            completion_text += (
                f" · 应售 "
                f"{_num(target * float(completion['median']))}间"
            )
        first.append(completion_text)
    second: list[str] = []
    if _n(pickup.get("median")) is not None:
        second.append(f"净增 {_pickup_text(pickup)}")
    samples = []
    if int(capacity.get("sample_count") or 0):
        samples.append(f"容量{int(capacity.get('sample_count') or 0)}")
    if int(completion.get("sample_count") or 0):
        samples.append(
            f"完成{int(completion.get('sample_count') or 0)}"
        )
    if int(pickup.get("sample_count") or 0):
        samples.append(f"净增{int(pickup.get('sample_count') or 0)}")
    if samples:
        second.append("样本 " + "/".join(samples) + "天")
    quality = []
    if _n(point.get("capacity_confidence")) is not None:
        quality.append(
            f"容量{_pct(point.get('capacity_confidence'), 0)}"
        )
    if _n(point.get("target_completion_confidence")) is not None:
        quality.append(
            f"完成{_pct(point.get('target_completion_confidence'), 0)}"
        )
    maturity = _MATURITY.get(str(point.get("maturity") or ""))
    if maturity:
        quality.append(f"成熟度{maturity}")
    if quality:
        second.append("质量 " + "/".join(quality))
    lines = [f"{hour:02d}:00  " + "  ｜  ".join(first)]
    if second:
        lines.append("       " + "  ·  ".join(second))
    return lines


def build_s15_user_message(payload: Mapping[str, Any]) -> str:
    if payload.get("status") != "ok":
        return "📈 S15 销售基准\n当前没有可用的同类历史基准。"

    hotel = payload.get("hotel") or {}
    target = _n(hotel.get("effective_target_room_nights"))
    revenue = _n(
        (hotel.get("historical_revenue_target") or {}).get("median")
    )
    health = hotel.get("baseline_health") or {}
    selected_dates = payload.get("selected_dates") or []
    as_of = str(payload.get("as_of_datetime") or "")
    time_text = as_of[11:16] if len(as_of) >= 16 else ""
    title = f"📈 S15 销售基准｜{payload.get('target_date') or '-'}"
    if time_text:
        title += f" {time_text}"

    target_dates = hotel.get("target_series_dates") or []
    lines = [
        title,
        (
            "目标来源  历史同类日推理（非人工目标）"
            + (
                f"  ·  参考终值 {_num(target)}间"
                if target is not None
                else ""
            )
            + (
                f"  ·  参考收入 {_money(revenue)}"
                if revenue is not None
                else ""
            )
        ),
        (
            f"样本口径  容量 {len(selected_dates)}天 / "
            f"{_tier_label(payload.get('selected_tier'))}"
            + (
                f"  ·  完成 {len(target_dates)}天 / "
                f"{_tier_label(hotel.get('target_series_tier'))}"
                if target_dates
                else ""
            )
        ),
    ]

    observed = health.get("observed_hour_slots") or []
    fallback_only = health.get("fallback_only_hour_slots") or []
    missing = health.get("missing_hour_slots") or []
    grid_coverage = _n(health.get("hour_grid_coverage"))
    checkpoint_coverage = _n(health.get("display_checkpoint_coverage"))
    health_parts = [
        f"精确小时 {len(observed)}/24",
        f"前序回退 {len(fallback_only)}",
        f"缺失 {len(missing)}",
    ]
    if grid_coverage is not None:
        health_parts.append(f"小时网格覆盖 {_pct(grid_coverage, 1)}")
    if checkpoint_coverage is not None:
        health_parts.append(
            f"摘要节点覆盖 {_pct(checkpoint_coverage, 1)}"
        )
    health_parts.append(
        "整体成熟度 "
        + _MATURITY.get(
            str(health.get("object_maturity") or ""),
            "未评估",
        )
    )
    if _n(hotel.get("capacity_series_confidence")) is not None:
        health_parts.append(
            "容量置信度 "
            + _pct(hotel.get("capacity_series_confidence"), 0)
        )
    if _n(hotel.get("target_series_confidence")) is not None:
        health_parts.append(
            "完成置信度 "
            + _pct(hotel.get("target_series_confidence"), 0)
        )
    lines.append("基准健康  " + "  ·  ".join(health_parts))

    lines.extend(["", "【全店小时节奏】"])
    for point in hotel.get("hourly_points") or []:
        lines.extend(_s15_hour_lines(point, target))
    if fallback_only:
        lines.append(f"前序批次回退  {_compress_hours(fallback_only)}")
    if missing:
        lines.append(
            f"采集缺口  {_compress_hours(missing)}（不插值、不补零）"
        )

    lines.extend(["", "【房型基准｜当前时点】"])
    try:
        current_hour = int(as_of[11:13])
    except (ValueError, IndexError):
        current_hour = 23

    for _, room in sorted(
        (payload.get("room_types") or {}).items(),
        key=lambda item: str(
            item[1].get("room_type_name") or item[0]
        ),
    ):
        points = [
            point
            for point in room.get("hourly_points") or []
            if isinstance(point.get("hour"), int)
            and int(point["hour"]) <= current_hour
            and (
                _n((point.get("capacity") or {}).get("median"))
                is not None
                or _n(
                    (point.get("target_completion") or {}).get("median")
                )
                is not None
            )
        ]
        point = (
            max(points, key=lambda item: int(item["hour"]))
            if points
            else None
        )
        if not point:
            continue

        capacity = point.get("capacity") or {}
        completion = point.get("target_completion") or {}
        pickup = point.get("pickup") or {}
        price = room.get("price_baseline") or {}
        room_target = _n(room.get("effective_target_room_nights"))
        name = (
            room.get("room_type_name")
            or room.get("room_type_id")
            or "未知房型"
        )
        lines.append(
            f"• {name}  ·  {int(point.get('hour') or 0):02d}:00"
        )

        pace_parts = []
        if _n(capacity.get("median")) is not None:
            pace_parts.append(
                f"容量 {_band(capacity)} "
                f"n={int(capacity.get('sample_count') or 0)}"
            )
        if _n(completion.get("median")) is not None:
            pace_parts.append(
                f"完成 {_band(completion)} "
                f"n={int(completion.get('sample_count') or 0)}"
            )
        if _n(pickup.get("median")) is not None:
            pace_parts.append(
                f"净增 {_pickup_text(pickup)} "
                f"n={int(pickup.get('sample_count') or 0)}"
            )
        if pace_parts:
            lines.append("  节奏  " + "  ｜  ".join(pace_parts))

        baseline_parts = []
        target_dates_for_room = room.get("target_series_dates") or []
        if room_target is not None:
            baseline_parts.append(
                f"参考终值 {_num(room_target)}间"
                f"（{len(target_dates_for_room)}天 / "
                f"{_tier_label(room.get('target_series_tier'))}）"
            )
        price_parts = []
        for key, label in (
            ("p20", "P20"),
            ("median", "中位"),
            ("p80", "P80"),
        ):
            if _n(price.get(key)) is not None:
                price_parts.append(f"{label} {_money(price.get(key))}")
        if price_parts:
            price_dates = room.get("price_series_dates") or []
            baseline_parts.append(
                "成交价 "
                + " / ".join(price_parts)
                + f"（{len(price_dates)}天 / "
                f"{_tier_label(room.get('price_series_tier'))}）"
            )
        if baseline_parts:
            lines.append("  基准  " + "  ｜  ".join(baseline_parts))
        quality_parts = []
        maturity_label = _MATURITY.get(str(point.get("maturity") or ""))
        if maturity_label:
            quality_parts.append(f"成熟度 {maturity_label}")
        if _n(point.get("capacity_confidence")) is not None:
            quality_parts.append(
                "容量置信度 "
                + _pct(point.get("capacity_confidence"), 0)
            )
        if _n(point.get("target_completion_confidence")) is not None:
            quality_parts.append(
                "完成置信度 "
                + _pct(point.get("target_completion_confidence"), 0)
            )
        if _n(room.get("price_series_confidence")) is not None:
            quality_parts.append(
                "价格置信度 "
                + _pct(room.get("price_series_confidence"), 0)
            )
        if quality_parts:
            lines.append("  质量  " + "  ·  ".join(quality_parts))

    ota_lines: list[str] = []
    ota = payload.get("ota_baselines") or {}
    for key, label in (("meituan", "美团"), ("ctrip", "携程")):
        platform = ota.get(key) or {}
        baselines = platform.get("baselines") or {}
        values: list[str] = []
        if key == "meituan":
            fields = (
                ("browse_uv", "浏览", False),
                ("first_conversion", "曝光→浏览", True),
                ("second_conversion", "浏览→支付", True),
            )
        else:
            fields = (
                ("detail_visitor_count", "详情访客", False),
                ("list_to_detail_ratio", "列表曝光→详情访客", True),
                ("detail_to_submit_ratio", "详情访客→提交", True),
            )
        for metric, metric_label, percent in fields:
            median = _n((baselines.get(metric) or {}).get("median"))
            if median is not None:
                values.append(
                    f"{metric_label} "
                    f"{_pct(median) if percent else _num(median)}"
                )
        if values:
            ota_lines.append(f"• {label}  " + "  ｜  ".join(values))
            ota_lines.append(
                f"  样本  {int(platform.get('history_day_count') or 0)}天 / "
                f"{_tier_label(platform.get('selected_tier'))}"
                f"  ·  成熟度 "
                f"{_MATURITY.get(str(platform.get('maturity') or ''), '未评估')}"
            )
    if ota_lines:
        lines.extend(["", "【平台流量与转化】", *ota_lines])

    lines.extend(
        [
            "",
            "口径说明",
            "• 容量节奏＝承诺已售 ÷ 可售总房量；"
            "参考完成节奏＝承诺已售 ÷ 历史最终已售。",
            "• 净增允许为负，表示取消、库存调整或源数据修订。",
        ]
    )
    return "\n".join(lines)


def _line_block(
    name: str,
    line: Mapping[str, Any],
    *,
    remaining: float | None = None,
    maturity: Any = None,
    confidence: Any = None,
) -> list[str]:
    if _n(line.get("actual_progress")) is None or _n(
        line.get("baseline_median")
    ) is None:
        return []
    history = f"历史 {_pct(line.get('baseline_median'))}"
    if _n(line.get("baseline_p25")) is not None and _n(
        line.get("baseline_p80")
    ) is not None:
        history += (
            f"〔{_pct(line.get('baseline_p25'))}"
            f"–{_pct(line.get('baseline_p80'))}〕"
        )
    status = _STATUS.get(str(line.get("status") or ""), "")
    first = (
        f"{name}  当前 {_pct(line.get('actual_progress'))}"
        f"  ·  {history}"
        f"  ·  偏差 {_pp(line.get('delta_pp'))}"
        + (f"  ·  {status}" if status else "")
    )
    second_parts = [
        f"同时点应售 {_num(line.get('expected_sold'))}间",
        _gap_phrase(line.get("room_gap")),
    ]
    if remaining is not None:
        second_parts.append(_remaining_phrase(remaining))
    quality = []
    maturity_label = _MATURITY.get(str(maturity or ""))
    if maturity_label:
        quality.append(f"成熟度 {maturity_label}")
    if _n(confidence) is not None:
        quality.append(f"置信度 {_pct(confidence, 0)}")
    if quality:
        second_parts.append(" / ".join(quality))
    return [first, "       " + "  ·  ".join(second_parts)]


def build_s16_user_message(report: Mapping[str, Any]) -> str:
    if report.get("status") not in {"ok", "partial"}:
        return "📊 S16 销售进度\n当前事实或销售基准不足，暂不能判断。"

    hotel = report.get("hotel_result") or {}
    actual = _n(hotel.get("committed_sold"))
    total = _n(hotel.get("total_rooms"))
    remaining = _n(hotel.get("remaining_sellable_rooms"))
    target = _n(hotel.get("effective_target_room_nights"))
    target_remaining = _n(
        (hotel.get("target_line") or {}).get("remaining_target_gap")
    )
    as_of = str(report.get("as_of_datetime") or "-")
    time_text = as_of[11:16] if len(as_of) >= 16 else as_of

    header = [
        f"📊 S16 销售进度｜{report.get('target_date') or '-'} {time_text}",
        (
            f"当前  已售 {_num(actual)}/{_num(total)}间"
            f"  ·  剩余可售 {_num(remaining)}间"
            + (
                f"  ·  历史参考终值 {_num(target)}间"
                if target is not None
                else ""
            )
        ),
    ]
    if target_remaining is not None:
        header.append("终值进度  " + _remaining_phrase(target_remaining))

    cap = hotel.get("capacity_line") or {}
    tgt = hotel.get("target_line") or {}
    cap_status = _STATUS.get(str(cap.get("status") or ""))
    tgt_status = _STATUS.get(str(tgt.get("status") or ""))
    if cap_status and tgt_status:
        conclusion = (
            f"两条节奏线均{cap_status}"
            if cap_status == tgt_status
            else f"容量线{cap_status}；参考完成线{tgt_status}"
        )
        header.append(f"结论  {conclusion}")
    if hotel.get("overbooking_risk"):
        header.append(
            "⚠ 超售风险  当前超售承诺 "
            f"{_num(hotel.get('overbooking_committed_rooms'))}间"
        )

    lines = header + ["", "【全店双线】"]
    lines.extend(
        _line_block(
            "容量线",
            cap,
            maturity=hotel.get("capacity_maturity"),
            confidence=hotel.get("capacity_confidence"),
        )
    )
    lines.extend(
        _line_block(
            "参考完成线",
            tgt,
            remaining=target_remaining,
            maturity=hotel.get("target_completion_maturity"),
            confidence=hotel.get("target_completion_confidence"),
        )
    )

    lines.extend(["", "【房型双线】"])
    room_name_by_id: dict[str, str] = {}
    for row in sorted(
        report.get("room_type_results") or [],
        key=lambda item: str(
            item.get("room_type_name")
            or item.get("room_type_id")
            or ""
        ),
    ):
        room_id = str(row.get("room_type_id") or "")
        name = row.get("room_type_name") or room_id or "未知房型"
        if room_id:
            room_name_by_id[room_id] = str(name)
        sold = _n(row.get("committed_sold"))
        room_total = _n(row.get("total_rooms"))
        room_available = _n(row.get("available_rooms"))
        lines.append(
            f"• {name}  ·  已售 {_num(sold)}/{_num(room_total)}间"
            f"  ·  余 {_num(room_available)}间"
        )
        cap_line = row.get("capacity_line") or {}
        tgt_line = row.get("target_line") or {}
        lines.extend(
            "  " + item
            for item in _line_block(
                "容量",
                cap_line,
                maturity=row.get("capacity_maturity"),
                confidence=row.get("capacity_confidence"),
            )
        )
        if _n(tgt_line.get("delta_pp")) is not None:
            lines.extend(
                "  " + item
                for item in _line_block(
                    "完成",
                    tgt_line,
                    remaining=_n(tgt_line.get("remaining_target_gap")),
                    maturity=row.get("target_completion_maturity"),
                    confidence=row.get("target_completion_confidence"),
                )
            )

    structure = report.get("structure_summary") or {}
    lines.extend(["", "【结构汇总】"])
    lines.append(
        "容量线  可判断 "
        f"{int(structure.get('capacity_line_available_count') or 0)}个"
        f"  ·  滞后 "
        f"{int(structure.get('capacity_slow_room_type_count') or 0)}个"
        f"  ·  超前 "
        f"{int(structure.get('capacity_fast_room_type_count') or 0)}个"
    )
    target_available = int(
        structure.get("target_line_available_count") or 0
    )
    if target_available:
        lines.append(
            f"完成线  可判断 {target_available}个"
            f"  ·  滞后 "
            f"{int(structure.get('target_slow_room_type_count') or 0)}个"
            f"  ·  超前 "
            f"{int(structure.get('target_fast_room_type_count') or 0)}个"
            f"  ·  滞后目标份额 "
            f"{_pct(structure.get('slow_target_share'))}"
        )
        negative_id = str(
            structure.get("largest_negative_gap_room_type") or ""
        )
        positive_id = str(
            structure.get("largest_positive_gap_room_type") or ""
        )
        if negative_id:
            lines.append(
                "最大负检查点差  "
                + room_name_by_id.get(negative_id, negative_id)
            )
        if positive_id:
            lines.append(
                "最大正检查点差  "
                + room_name_by_id.get(positive_id, positive_id)
            )

    reconciliation = report.get("structure_reconciliation") or {}
    if reconciliation.get("status") in {"ok", "conflict"}:
        status_text = (
            "一致" if reconciliation.get("status") == "ok" else "存在冲突"
        )
        lines.append(
            f"酒店/房型检查点对账  {status_text}"
            f"  ·  差异 {_num(reconciliation.get('difference'))}间"
        )

    policy_version = report.get("policy_version") or "s16-deviation.v1"
    lines.extend(
        [
            "",
            (
                "判定阈值  偏慢≤-8pp · 明显滞后≤-15pp · "
                "严重滞后≤-25pp"
                "  ｜  偏快≥+8pp · 明显超前≥+15pp"
                f"  ·  {policy_version}"
            ),
        ]
    )
    gap = report.get("checkpoint_gap_minutes")
    if gap is not None:
        lines.append(
            f"数据时效  完整房型批次距请求约 {int(gap)}分钟"
        )
    lines.append(
        "边界  只判断销售节奏与房型结构；"
        "不推断晚间剩余需求，不自动生成调价或推广建议。"
    )
    return "\n".join(lines)


def direct_output_contract(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mode": "locked_deterministic_business_view",
        "ai_analysis_allowed": False,
        "must_send_authoritative_text_verbatim": True,
        "analysis_handoff": "S14",
        "maximum_runtime_tool_calls": 1,
        "additional_database_queries_allowed": False,
        "forbidden": [
            "引用上一条S15或S16结果追加新结论",
            "把累计应售区间解释成剩余可卖空间或未来需求",
            "省略房型双线、同时点应售、检查点差或数据边界",
            "自动给出调价、推广、满房或晚间销量预测",
        ],
        "contract_version": _VERSION,
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import runtime.sales_progress as package
    from runtime import (
        s15_s16_ai_analysis_patch,
        s15_s16_runtime_patch,
        s15_s16_spec_alignment_patch,
    )
    from runtime.decisions import baseline as baseline_decision
    from runtime.sales_progress import (
        baseline_service,
        deviation_service,
        presentation,
        service,
    )

    s15_s16_spec_alignment_patch._PATCH_VERSION = _VERSION

    previous_sales_lines = baseline_service._sales_lines

    def sales_lines(
        selected_dates,
        hourly,
        room_daily_rows,
        hotel_daily_rows,
    ):
        hotel, rooms = previous_sales_lines(
            selected_dates,
            hourly,
            room_daily_rows,
            hotel_daily_rows,
        )
        add_pickup_baselines(selected_dates, hourly, hotel, rooms)
        return hotel, rooms

    baseline_service._sales_lines = sales_lines

    previous_deviation = deviation_service.build_deviation

    def deviation(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return enrich_deviation(
            previous_deviation(*args, **kwargs),
            kwargs.get("baseline"),
        )

    deviation_service.build_deviation = deviation
    service._build_deviation = deviation
    package.build_deviation = service.build_deviation

    presentation.build_s15_user_message = build_s15_user_message
    presentation.build_s16_user_message = build_s16_user_message
    s15_s16_ai_analysis_patch.build_ai_response_contract = (
        direct_output_contract
    )

    previous_direct_delivery = s15_s16_runtime_patch._direct_delivery

    def direct_delivery(
        result: dict[str, Any],
        role: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        rendered, send_payload = previous_direct_delivery(result, role)
        contract = direct_output_contract(result)
        send_payload["assistant_response_contract"] = contract
        send_payload["authoritative_fallback_text"] = send_payload.get("text")
        send_payload["locked_fact_body"] = send_payload.get("text")
        send_payload["ai_analysis_allowed"] = False
        rendered["assistant_response_contract_version"] = _VERSION
        rendered["text_locked"] = True
        return rendered, send_payload

    s15_s16_runtime_patch._direct_delivery = direct_delivery

    previous_cached = baseline_decision._cached_baseline

    def cached(*args: Any, **kwargs: Any):
        payload = previous_cached(*args, **kwargs)
        if (
            payload is not None
            and payload.get("spec_alignment_version") != _VERSION
        ):
            return None
        return payload

    baseline_decision._cached_baseline = cached
