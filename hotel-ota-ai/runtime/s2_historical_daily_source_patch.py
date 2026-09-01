from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

VERSION = "s2-historical-daily-source.v1"
HISTORICAL_CONTRACT = "jy01_hotel_statistics_daily_v1"
HISTORICAL_SOURCE_TABLE = "jy01_hotel_statistics_daily"
HISTORICAL_ROOM_TYPE_SOURCE_TABLE = "jl01_room_type_performance_daily"
SHANGHAI_TZ = timezone(timedelta(hours=8))
_INSTALLED = False


def _now_shanghai(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI_TZ)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI_TZ)
    return current.astimezone(SHANGHAI_TZ)


def _is_historical_business_date(
    value: Any,
    *,
    now: datetime | None = None,
) -> bool:
    text = str(value or "")[:10]
    try:
        target = datetime.fromisoformat(text).date()
    except ValueError:
        return False
    return target < _now_shanghai(now).date()


def _payload(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    payload = result.get("payload")
    return dict(payload) if isinstance(payload, dict) else {}


def _daily_metrics(result: dict[str, Any] | None) -> dict[str, Any]:
    payload = _payload(result)
    metrics = payload.get("normalized_metrics")
    return dict(metrics) if isinstance(metrics, dict) else {}


def _source_pct(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.2f}%"


def _value(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _money(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _short_date(value: Any) -> str:
    text = str(value or "")[:10]
    try:
        _, month, day = text.split("-", 2)
        return f"{int(month)}/{int(day)}"
    except (TypeError, ValueError):
        return ""


def _historical_operating_payload(
    daily_result: dict[str, Any],
    *,
    hotel_id: str,
    business_date: str,
) -> tuple[str, dict[str, Any]]:
    source = _payload(daily_result)
    metrics = _daily_metrics(daily_result)
    data_date = str(source.get("data_business_date") or "")[:10]
    exact_date = data_date == business_date
    source_ok = daily_result.get("status") == "ok"
    status = "ok" if source_ok and exact_date and metrics else "data_gap"
    risk_flags = list(source.get("risk_flags") or [])
    risk_flags.append(f"historical_pms_source:{HISTORICAL_SOURCE_TABLE}")
    if not exact_date:
        risk_flags.append("historical_pms_business_date_mismatch")
    if not metrics:
        risk_flags.append("historical_pms_daily_metrics_missing")

    payload = {
        "hotel_id": hotel_id,
        "hotel_name": source.get("hotel_name"),
        "historical_daily": True,
        "source_status": "ok" if status == "ok" else "data_gap",
        "source_table": HISTORICAL_SOURCE_TABLE,
        "s2_contract": HISTORICAL_CONTRACT,
        "data_business_date": business_date,
        "data_snapshot_time": source.get("data_snapshot_time"),
        "room_count": metrics.get("room_count") or metrics.get("total_rooms"),
        "total_rooms": metrics.get("room_count") or metrics.get("total_rooms"),
        "sold_rooms": metrics.get("sold_rooms"),
        "remaining_rooms": metrics.get("remaining_rooms") or metrics.get("available_rooms"),
        "available_rooms": metrics.get("remaining_rooms") or metrics.get("available_rooms"),
        "room_nights": metrics.get("room_nights"),
        "room_revenue": metrics.get("room_revenue"),
        "orders_today": metrics.get("orders_today"),
        "occupancy_rate": metrics.get("occupancy_rate"),
        "adr": metrics.get("adr"),
        "revpar": metrics.get("revpar"),
        "room_type_forecasts": [],
        "historical_room_type_source_table": HISTORICAL_ROOM_TYPE_SOURCE_TABLE,
        "historical_room_type_detail_status": "not_loaded",
        "risk_flags": list(dict.fromkeys(risk_flags)),
    }
    return status, payload


def _build_historical_snapshot_result(
    router: Any,
    *,
    hotel_id: str,
    role: str,
    output_profile: str | None,
    target_business_date: str,
    as_of_time: str | None = None,
) -> dict[str, Any]:
    result = router._base_result("run_s02", role=role, output_profile=output_profile)
    business_date = str(target_business_date)[:10]

    if not router.database_source_enabled():
        result.update(
            {
                "status": "data_gap",
                "node_id": "N005",
                "skill_id": "S2",
                "agent_id": router.agent_id_for_node("N005"),
                "runtime_command": "snapshot",
                "business_date": business_date,
                "data_business_date": business_date,
                "data_source_type": "unavailable",
                "freshness_status": "missing_date",
                "today_label_allowed": False,
                "business_result_generated": False,
                "blocked_reason": "database_source_disabled",
                "s2_contract": HISTORICAL_CONTRACT,
                "historical_daily": True,
            }
        )
        return result

    daily_result = router.database_template_result(
        "daily_metrics",
        hotel_id,
        date=business_date,
        source_platform="pms",
    )
    status, historical_payload = _historical_operating_payload(
        daily_result,
        hotel_id=hotel_id,
        business_date=business_date,
    )
    optional_results = (
        router.load_s2_optional_results(
            router.database_template_result,
            hotel_id=hotel_id,
            business_date=business_date,
            as_of_time=as_of_time,
        )
        if status == "ok"
        else {}
    )
    operating_views = router.build_s2_operating_views(
        operating_payload=historical_payload,
        optional_results=optional_results,
    )
    operating_views["historical_daily"] = True
    operating_views["historical_source_table"] = HISTORICAL_SOURCE_TABLE
    operating_views["historical_room_type_source_table"] = HISTORICAL_ROOM_TYPE_SOURCE_TABLE
    operating_views["historical_room_type_detail_status"] = "not_loaded"
    core = dict(operating_views.get("core_operating") or {})
    core.update(
        {
            "status": status,
            "business_date": business_date,
            "snapshot_time": historical_payload.get("data_snapshot_time"),
            "source_table": HISTORICAL_SOURCE_TABLE,
            "room_count": historical_payload.get("room_count"),
            "sold_rooms": historical_payload.get("sold_rooms"),
            "remaining_rooms": historical_payload.get("remaining_rooms"),
            "room_nights": historical_payload.get("room_nights"),
            "room_revenue": historical_payload.get("room_revenue"),
            "orders_today": historical_payload.get("orders_today"),
            "occupancy_rate": historical_payload.get("occupancy_rate"),
            "adr": historical_payload.get("adr"),
            "revpar": historical_payload.get("revpar"),
        }
    )
    operating_views["core_operating"] = core
    operating_views["room_type_status"] = {
        "status": "not_loaded",
        "items": [],
        "business_date": business_date,
        "source_table": HISTORICAL_ROOM_TYPE_SOURCE_TABLE,
    }

    freshness_status = (
        (_payload(daily_result).get("freshness_status"))
        or daily_result.get("freshness_status")
        or ("historical_complete" if status == "ok" else "missing_date")
    )
    core_metrics = {
        "total_rooms": historical_payload.get("total_rooms"),
        "sold_rooms": historical_payload.get("sold_rooms"),
        "sold_room_nights_today": historical_payload.get("room_nights"),
        "sold_orders_today": historical_payload.get("orders_today"),
        "occupancy_rate": historical_payload.get("occupancy_rate"),
        "adr": historical_payload.get("adr"),
        "revpar": historical_payload.get("revpar"),
    }
    result.update(
        {
            "status": status,
            "node_id": "N005",
            "skill_id": "S2",
            "agent_id": router.agent_id_for_node("N005"),
            "runtime_command": "snapshot",
            "hotel_id": hotel_id,
            "business_result_generated": status == "ok",
            "data_source_type": daily_result.get("data_source_type") or "mysql_db",
            "source_mode": daily_result.get("source_mode") or "mysql_runtime",
            "source_status": historical_payload.get("source_status"),
            "freshness_status": freshness_status,
            "business_date": business_date,
            "data_business_date": business_date,
            "data_snapshot_time": historical_payload.get("data_snapshot_time"),
            "s2_contract": HISTORICAL_CONTRACT,
            "historical_daily": True,
            "historical_source_table": HISTORICAL_SOURCE_TABLE,
            "historical_room_type_source_table": HISTORICAL_ROOM_TYPE_SOURCE_TABLE,
            "historical_room_type_detail_status": "not_loaded",
            "today_label_allowed": False,
            "core_metrics": core_metrics,
            "operating_views": operating_views,
            "total_rooms": core_metrics["total_rooms"],
            "sold_rooms": core_metrics["sold_rooms"],
            "sold_room_nights_today": core_metrics["sold_room_nights_today"],
            "sold_orders_today": core_metrics["sold_orders_today"],
            "occupancy_rate": core_metrics["occupancy_rate"],
            "formula_version": "jy01_hotel_statistics_daily_source_v1",
            "occupancy_rate_source": HISTORICAL_SOURCE_TABLE,
            "adr": core_metrics["adr"],
            "revpar": core_metrics["revpar"],
            "risk_flags": historical_payload.get("risk_flags") or [],
            "blocked_reason": (
                "read_only_runtime_formal_live_blocked"
                if status == "ok"
                else "historical_daily_data_gap"
            ),
            "formal_approval_created": False,
            "live_execution_count": 0,
        }
    )
    return result


def _render_flow(flow: dict[str, Any]) -> list[str]:
    business_date = flow.get("business_date")
    if not business_date and flow.get("platforms"):
        business_date = next(
            (
                item.get("business_date")
                for item in flow["platforms"].values()
                if isinstance(item, dict) and item.get("business_date")
            ),
            None,
        )
    label = _short_date(business_date)
    lines = [f"\n三、流量转化（{label} 当日数据）" if label else "\n三、流量转化（当日数据）"]
    platforms = flow.get("platforms") or {}
    if not platforms:
        if flow.get("status") == "no_records":
            lines.append(
                f"- 美团：{_value(flow.get('business_date'))} 当日未查询到流量转化记录；未使用其他业务日数据。"
            )
        else:
            flags = "；".join(map(str, flow.get("quality_flags") or [])) or "来源不可用"
            lines.append(f"- 流量转化：未形成可用结果（{flags}）。")
        return lines

    for platform, item in platforms.items():
        if platform != "meituan":
            continue
        metrics = item.get("metrics") or []
        sample = "；".join(
            f"{_value(metric.get('metric_name') or metric.get('metric_code'))}={_value(metric.get('metric_value'))} {_value(metric.get('metric_unit'))}"
            for metric in metrics
        ) or "无可展示指标"
        flags = item.get("quality_flags") or []
        suffix = f"；质量标记 {'、'.join(map(str, flags))}" if flags else ""
        lines.append(
            f"- 美团：{_value(item.get('metric_count'))} 条指标，业务日 {_value(item.get('business_date'))}，"
            f"抓取 {_value(item.get('snapshot_time'))}；{sample}{suffix}。"
        )
    return lines


def render_historical_s2_reply(views: dict[str, Any]) -> str:
    core = views.get("core_operating") or {}
    flow = views.get("flow_conversion") or {}
    lines = [
        "S2 历史经营快照（真实数据只读）",
        (
            f"营业日 {_value(core.get('business_date'))}｜PMS 日终来源 {HISTORICAL_SOURCE_TABLE}"
            f"｜抓取 {_value(core.get('snapshot_time'))}"
        ),
        "\n一、经营总览（PMS 日报）",
        (
            f"- 房间数 {_value(core.get('room_count'))}，已售房 {_value(core.get('sold_rooms'))}，"
            f"剩余可售 {_value(core.get('remaining_rooms'))}，间夜 {_value(core.get('room_nights'))}，"
            f"订单 {_value(core.get('orders_today'))}。"
        ),
        (
            f"- 出租率 {_source_pct(core.get('occupancy_rate'))}；房费收入 ¥{_money(core.get('room_revenue'))}，"
            f"ADR ¥{_money(core.get('adr'))}，RevPAR ¥{_money(core.get('revpar'))}。"
        ),
        "\n二、房型经营（日终）",
        (
            f"- 历史房型明细应读取 {HISTORICAL_ROOM_TYPE_SOURCE_TABLE}；"
            "本次未使用 pms_room_type_forecast 反推或伪造历史房态。"
        ),
    ]
    lines.extend(_render_flow(flow))
    lines.extend(
        [
            "\n数据边界",
            f"- PMS 酒店级历史事实固定来自 {HISTORICAL_SOURCE_TABLE}。",
            "- 历史日期缺数据时返回 data_gap，不回退到当日 pms_room_type_forecast。",
            "- S2 仅展示经营事实，不生成诊断或执行动作。",
        ]
    )
    return "\n".join(lines)


def _wrap_send_payload(previous: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def build_feishu_send_payload(
        result: dict[str, Any],
        role: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(previous(result, role=role))
        if (
            result.get("intent") in {"run_s02", "run_s02_demo"}
            and result.get("s2_contract") == HISTORICAL_CONTRACT
            and isinstance(result.get("operating_views"), dict)
        ):
            payload["text"] = render_historical_s2_reply(result["operating_views"])
            payload["data_source_type"] = result.get("data_source_type")
            payload["freshness_status"] = result.get("freshness_status")
        return payload

    build_feishu_send_payload._S2_HISTORICAL_DAILY_SOURCE_V1 = True  # type: ignore[attr-defined]
    return build_feishu_send_payload


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router
    from runtime import feishu_output_renderer as renderer

    previous_snapshot = router._production_snapshot_result
    if not getattr(previous_snapshot, "_S2_HISTORICAL_DAILY_SOURCE_V1", False):

        def _production_snapshot_result(
            *,
            hotel_id: str,
            role: str,
            output_profile: str | None,
            target_business_date: str,
            as_of_time: str | None = None,
        ) -> dict[str, Any]:
            if not _is_historical_business_date(target_business_date):
                return previous_snapshot(
                    hotel_id=hotel_id,
                    role=role,
                    output_profile=output_profile,
                    target_business_date=target_business_date,
                    as_of_time=as_of_time,
                )
            return _build_historical_snapshot_result(
                router,
                hotel_id=hotel_id,
                role=role,
                output_profile=output_profile,
                target_business_date=target_business_date,
                as_of_time=as_of_time,
            )

        _production_snapshot_result._S2_HISTORICAL_DAILY_SOURCE_V1 = True  # type: ignore[attr-defined]
        router._production_snapshot_result = _production_snapshot_result

    previous_send = router.build_feishu_send_payload
    if not getattr(previous_send, "_S2_HISTORICAL_DAILY_SOURCE_V1", False):
        wrapped_send = _wrap_send_payload(previous_send)
        router.build_feishu_send_payload = wrapped_send
        renderer.build_feishu_send_payload = wrapped_send

    router.S2_HISTORICAL_DAILY_SOURCE_VERSION = VERSION
