from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import fmean
from typing import Any, Callable

from runtime.sales_progress.repository import DirectSalesProgressRepository, RepositoryError


SOURCE_TABLE = "jl01_room_type_performance_daily"
MAX_LOOKBACK_DAYS = 90


def _as_date(value: str | None) -> date:
    text = str(value or "")[:10]
    return datetime.strptime(text, "%Y-%m-%d").date()


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _percent(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number * 100 if 0 <= number <= 1 else number


def _day(value: Any) -> str | None:
    text = str(value or "")[:10]
    try:
        return _as_date(text).isoformat()
    except ValueError:
        return None


def _empty_result(*, days: int, start_date: str, end_date: str, reason: str) -> dict[str, Any]:
    return {
        "status": "data_gap",
        "skill_id": "S2",
        "report_type": "historical_room_type_performance",
        "period_days_requested": days,
        "period_start_date": start_date,
        "period_end_date": end_date,
        "data_business_date": end_date,
        "source_table": SOURCE_TABLE,
        "room_types": [],
        "business_result_generated": False,
        "blocked_reason": reason,
        "live_allowed": False,
        "approval_data_allowed": False,
    }


def _load_jl01_rows(repository: Any, *, hotel_id: str, start_date: str, end_date: str, as_of_time: str) -> list[dict[str, Any]]:
    """Read only JL01; this report must not inherit S15/S16's JY01 fallback."""
    query = getattr(repository, "_query", None)
    if not callable(query):
        raise RepositoryError("historical_room_type_query_unavailable")
    return list(
        query(
            """
            SELECT * FROM (
              SELECT hotel_id, business_date, room_type_id, room_type_name,
                     room_nights, occupancy_rate, room_revenue, adr, revpar, snapshot_time,
                     ROW_NUMBER() OVER (
                       PARTITION BY hotel_id, business_date, room_type_id
                       ORDER BY snapshot_time DESC, id DESC
                     ) AS rn
              FROM jl01_room_type_performance_daily
              WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
                AND snapshot_time<=%s AND room_type_id IS NOT NULL AND room_type_id<>''
            ) ranked WHERE rn=1
            """,
            (hotel_id, start_date, end_date, as_of_time),
        )
    )


def build_historical_room_type_performance(
    *,
    hotel_id: str | None,
    days: int,
    as_of_time: str,
    repository_factory: Callable[[str], Any] = DirectSalesProgressRepository.from_environment,
) -> dict[str, Any]:
    """Build a read-only, completed-day room-type report from JL01 only."""
    if not hotel_id:
        return _empty_result(days=days, start_date="-", end_date="-", reason="hotel_scope_missing")
    if not 1 <= days <= MAX_LOOKBACK_DAYS:
        return _empty_result(days=days, start_date="-", end_date="-", reason="historical_period_out_of_range")

    as_of_day = _as_date(as_of_time)
    end_day = as_of_day - timedelta(days=1)
    start_day = end_day - timedelta(days=days - 1)
    start_date, end_date = start_day.isoformat(), end_day.isoformat()
    repository = None
    try:
        repository = repository_factory(str(hotel_id))
        rows = _load_jl01_rows(
            repository,
            hotel_id=str(hotel_id),
            start_date=start_date,
            end_date=end_date,
            as_of_time=as_of_time,
        )
    except RepositoryError as exc:
        return _empty_result(days=days, start_date=start_date, end_date=end_date, reason=str(exc))
    except Exception as exc:  # Keep database exceptions from leaking into Feishu output.
        return _empty_result(days=days, start_date=start_date, end_date=end_date, reason=f"historical_room_type_query_failed:{type(exc).__name__}")
    finally:
        close = getattr(repository, "close", None)
        if callable(close):
            close()

    by_room: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    captured_at: str | None = None
    for row in rows:
        room_type_id = str(row.get("room_type_id") or "").strip()
        room_type_name = str(row.get("room_type_name") or room_type_id).strip()
        business_date = _day(row.get("business_date"))
        if not room_type_id or not room_type_name or not business_date:
            continue
        item = dict(row)
        item["business_date"] = business_date
        by_room[(room_type_id, room_type_name)].append(item)
        snapshot = str(row.get("snapshot_time") or "").strip()
        if snapshot and (captured_at is None or snapshot > captured_at):
            captured_at = snapshot

    if not by_room:
        return _empty_result(days=days, start_date=start_date, end_date=end_date, reason="historical_room_type_daily_no_rows")

    expected_days = {(start_day + timedelta(days=index)).isoformat() for index in range(days)}
    room_types: list[dict[str, Any]] = []
    for (room_type_id, room_type_name), room_rows in by_room.items():
        latest_by_day: dict[str, dict[str, Any]] = {}
        for row in room_rows:
            business_date = row["business_date"]
            previous = latest_by_day.get(business_date)
            if previous is None or str(row.get("snapshot_time") or "") >= str(previous.get("snapshot_time") or ""):
                latest_by_day[business_date] = row
        ordered = [latest_by_day[day] for day in sorted(latest_by_day)]
        occupancy_values = [value for row in ordered if (value := _percent(row.get("occupancy_rate"))) is not None]
        room_nights = sum(value for row in ordered if (value := _number(row.get("room_nights"))) is not None)
        room_revenue = sum(value for row in ordered if (value := _number(row.get("room_revenue"))) is not None)
        adr_values = [value for row in ordered if (value := _number(row.get("adr"))) is not None]
        revpar_values = [value for row in ordered if (value := _number(row.get("revpar"))) is not None]
        # JL01's ADR is the source fact.  Only derive it from revenue and nights
        # when a legacy row lacks the explicit field.
        adr = round(fmean(adr_values), 2) if adr_values else (
            round(room_revenue / room_nights, 2) if room_nights > 0 and room_revenue > 0 else None
        )
        room_types.append(
            {
                "room_type_id": room_type_id,
                "room_type_name": room_type_name,
                "covered_days": len(ordered),
                "missing_days": sorted(expected_days - set(latest_by_day)),
                "average_occupancy_rate": round(fmean(occupancy_values), 2) if occupancy_values else None,
                "adr": adr,
                "revpar": round(fmean(revpar_values), 2) if revpar_values else None,
                "room_nights": round(room_nights, 2),
            }
        )
    room_types.sort(key=lambda item: str(item["room_type_name"]))
    complete = all(item["covered_days"] == days for item in room_types)
    return {
        "status": "ok",
        "skill_id": "S2",
        "node_id": "N005",
        "report_type": "historical_room_type_performance",
        "period_days_requested": days,
        "period_start_date": start_date,
        "period_end_date": end_date,
        "data_business_date": end_date,
        "source_table": SOURCE_TABLE,
        "data_snapshot_time": captured_at,
        "freshness_status": "historical_complete" if complete else "partial",
        "data_source_type": "real_database",
        "room_types": room_types,
        "business_result_generated": True,
        "live_allowed": False,
        "approval_data_allowed": False,
    }


def render_historical_room_type_performance_reply(result: dict[str, Any]) -> str:
    if result.get("status") != "ok":
        return "历史房型经营分析\n结论：暂无可用数据。请检查房型日经营数据是否已完成入库。"
    days = result.get("period_days_requested")
    lines = [
        f"历史房型经营分析｜近 {days} 个完整业务日",
        f"周期：{result.get('period_start_date')} 至 {result.get('period_end_date')}",
        "口径：出租率、成交 ADR 和 RevPAR 均直接读取房型日表后按日均值汇总，非 OTA 挂牌价。",
    ]
    for item in result.get("room_types") or []:
        occ = item.get("average_occupancy_rate")
        adr = item.get("adr")
        detail = f"- {item.get('room_type_name')}：出租率 {occ:.1f}%" if occ is not None else f"- {item.get('room_type_name')}：出租率 -"
        detail += f"｜成交 ADR ¥{adr:.0f}" if adr is not None else "｜成交 ADR -"
        revpar = item.get("revpar")
        detail += f"｜RevPAR ¥{revpar:.0f}" if revpar is not None else "｜RevPAR -"
        detail += f"｜覆盖 {item.get('covered_days')}/{days} 天"
        lines.append(detail)
    if result.get("freshness_status") == "partial":
        lines.append("说明：部分房型存在缺失业务日，已按实际覆盖天数计算，未用其他日期补齐。")
    lines.append("边界：本次仅做历史经营分析，不创建调价、推广或审批任务。")
    return "\n".join(lines)
