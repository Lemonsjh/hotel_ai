from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

VERSION = "s15-s16-data-correctness.v1"
_INSTALLED = False
STALE_MINUTES = 120


def num(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_dt(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        result = value
    elif value in (None, ""):
        return None
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            result = dt.datetime.fromisoformat(text)
        except ValueError:
            result = None
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    result = dt.datetime.strptime(text, fmt)
                    break
                except ValueError:
                    pass
            if result is None:
                return None
    return result.replace(tzinfo=None) if result.tzinfo else result


def _hour(value: Any, fallback: Any = None) -> int | None:
    parsed = parse_dt(value) or parse_dt(fallback)
    if parsed:
        return parsed.hour
    value = num(value)
    return int(value) if value is not None and 0 <= value <= 23 else None


def _room_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("room_type_id")
    return None if value in (None, "") else str(value)


def select_batch(
    rows: Sequence[Mapping[str, Any]], *, expected_room_types: Sequence[str] | None = None,
    requested_hour: int | None = None, max_gap_minutes: int = STALE_MINUTES,
    as_of_datetime: Any = None,
) -> Any:
    from runtime.sales_progress.core import BatchSelection

    expected = {str(v) for v in (expected_room_types or []) if v not in (None, "")}
    as_of = parse_dt(as_of_datetime)
    grouped: dict[tuple[int | None, str], list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        snapshot = parse_dt(row.get("snapshot_time"))
        if snapshot is None or (as_of and snapshot > as_of):
            continue
        hour = _hour(row.get("snapshot_hour"), snapshot)
        grouped[(hour, snapshot.isoformat(sep=" "))].append(row)

    candidates = []
    for (hour, snapshot_text), batch in grouped.items():
        if hour is None or (requested_hour is not None and hour > requested_hour):
            continue
        ids = [_room_id(row) for row in batch]
        non_null = [v for v in ids if v]
        missing = tuple(sorted(expected - set(non_null))) if expected else ()
        valid = all(
            _room_id(row) and num(row.get("total_rooms")) is not None
            and float(row.get("total_rooms")) >= 0
            and num(row.get("available_rooms")) is not None
            and float(row.get("available_rooms")) >= 0
            and num(row.get("overbooking_rooms")) is not None
            and float(row.get("overbooking_rooms")) >= 0
            for row in batch
        )
        complete = bool(non_null) and len(non_null) == len(set(non_null)) and not missing and valid
        candidates.append((hour, parse_dt(snapshot_text) or dt.datetime.min, batch, complete, missing))
    if not candidates:
        return BatchSelection("data_gap", [], None, None, requested_hour, None, False, (), "no_candidate_batch")
    pool = [v for v in candidates if v[3]] or candidates
    hour, snapshot, batch, complete, missing = sorted(pool, key=lambda v: (v[0], v[1]), reverse=True)[0]
    gap = max((requested_hour - hour) * 60, 0) if requested_hour is not None else None
    if as_of and snapshot.date() == as_of.date() and snapshot <= as_of:
        gap = max(int((as_of - snapshot).total_seconds() // 60), 0)
    if as_of is None and gap is not None and gap > max_gap_minutes:
        return BatchSelection("data_gap", [], None, hour, requested_hour, gap, False, missing, "checkpoint_gap_exceeds_limit")
    reason = "partial_room_type_scope" if not complete else "stale_checkpoint_used" if gap is not None and gap > max_gap_minutes else None
    return BatchSelection("ok" if complete else "partial", batch, snapshot.isoformat(sep=" "), hour, requested_hour, gap, complete, missing, reason)


def current_forecast(self: Any, hotel_id: str, stay_date: str, as_of_datetime: str) -> list[dict[str, Any]]:
    return self._query(
        """
        SELECT hotel_id,stay_date,snapshot_time,room_type_id,room_type_name,
               pms_room_type_id,total_rooms,available_rooms,occupied_rooms,
               overbooking_rooms,room_revenue,adr,revpar
        FROM pms_room_type_forecast
        WHERE hotel_id=%s AND stay_date=%s AND snapshot_time=(
          SELECT MAX(snapshot_time) FROM pms_room_type_forecast
          WHERE hotel_id=%s AND stay_date=%s AND snapshot_time<=%s)
        ORDER BY room_type_id
        """, (hotel_id, stay_date, hotel_id, stay_date, as_of_datetime),
    )


def room_daily(self: Any, hotel_id: str, start_date: str, end_date: str, as_of_datetime: str) -> list[dict[str, Any]]:
    primary = self._query(
        """
        SELECT * FROM (
          SELECT hotel_id,business_date,room_type_id,room_type_name,
                 NULL AS pms_room_type_id,pms_rate_room_type_id,room_nights,
                 occupancy_rate,room_revenue,adr,revpar,snapshot_time,
                 ROW_NUMBER() OVER(PARTITION BY hotel_id,business_date,room_type_id
                   ORDER BY snapshot_time DESC,id DESC) rn
          FROM jl01_room_type_performance_daily
          WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
            AND snapshot_time<=%s AND room_type_id IS NOT NULL AND room_type_id<>'') x
        WHERE rn=1
        """, (hotel_id, start_date, end_date, as_of_datetime),
    )
    try:
        vertical = self._query(
            """
            SELECT id,hotel_id,business_date,room_type_id,dimension_type,
                   dimension_name,room_nights,occupancy_rate,room_revenue,adr,revpar,snapshot_time
            FROM jy01_hotel_statistics_daily
            WHERE hotel_id=%s AND business_date BETWEEN %s AND %s AND snapshot_time<=%s
              AND room_type_id IS NOT NULL AND room_type_id<>''
              AND dimension_type<>'总营业指标' AND dimension_name<>'总营业指标'
            ORDER BY business_date,room_type_id,snapshot_time DESC,id DESC
            """, (hotel_id, start_date, end_date, as_of_datetime),
        )
        from runtime.s15_s16_ai_analysis_patch import merge_room_daily_fallback
        return merge_room_daily_fallback(primary, vertical)
    except Exception:
        return [dict(row) for row in primary]


def room_revenue(self: Any, hotel_id: str, start_date: str, end_date: str, as_of_datetime: str) -> list[dict[str, Any]]:
    return self._query(
        """
        SELECT business_date,room_type_id,room_daily_price,SUM(room_nights) room_nights,
               SUM(room_fee) room_fee,MAX(snapshot_time) snapshot_time
        FROM (
          SELECT id,business_date,room_type_id,room_daily_price,room_nights,room_fee,snapshot_time,
                 ROW_NUMBER() OVER(PARTITION BY hotel_id,business_date,order_id,room_no,
                   charge_subject,room_type_id ORDER BY snapshot_time DESC,id DESC) rn
          FROM rs01_room_revenue_daily
          WHERE hotel_id=%s AND business_date BETWEEN %s AND %s AND snapshot_time<=%s
            AND room_type_id IS NOT NULL AND room_type_id<>''
            AND room_daily_price>0 AND room_nights>0 AND stay_type='正常'
            AND charge_subject IN ('房费','手工输入房费','调整房费')) x
        WHERE rn=1 GROUP BY business_date,room_type_id,room_daily_price
        """, (hotel_id, start_date, end_date, as_of_datetime),
    )


def current_prices(repository: Any, hotel_id: str, target_date: str, as_of_datetime: str) -> list[dict[str, Any]]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return []
    try:
        rows = query(
            """
            SELECT g.hotel_id,g.business_date,g.snapshot_time,g.ota_product_id,g.ota_product_name,
                   g.rate_plan_name,g.is_super_deal,g.ota_sale_price,m.room_type_id,m.room_type_name,
                   m.mapping_status,m.is_active mapping_active,m.is_hour_room,m.price_editable_flag
            FROM meituan_ota_goods_price_mapping g
            JOIN hotel_room_type_mapping m ON m.hotel_id=g.hotel_id
             AND CAST(m.source_product_id AS CHAR)=CAST(g.ota_product_id AS CHAR)
             AND m.source_platform IN ('美团','meituan') AND m.mapping_status='AUTO' AND m.is_active=1
            WHERE g.hotel_id=%s AND g.business_date<=%s AND g.snapshot_time=(
              SELECT MAX(snapshot_time) FROM meituan_ota_goods_price_mapping
              WHERE hotel_id=%s AND business_date<=%s AND snapshot_time<=%s)
            ORDER BY m.room_type_id,g.ota_sale_price,g.ota_product_id
            """, (hotel_id, target_date, hotel_id, target_date, as_of_datetime),
        )
    except Exception:
        return []
    result, seen = [], set()
    for source in rows:
        row = dict(source)
        key = (str(row.get("room_type_id") or ""), str(row.get("ota_product_id") or ""))
        if not all(key) or key in seen:
            continue
        seen.add(key)
        row["product_scope"] = "hour_room" if str(row.get("is_hour_room") or "").lower() in {"1","true","yes"} else "super_deal" if str(row.get("is_super_deal") or "").lower() in {"1","true","yes"} else "normal_full_day"
        result.append(row)
    return result


def _patch_analysis() -> None:
    from runtime import s15_technical_analysis, s15_technical_sources, s15_s16_technical_spec_patch
    s15_technical_analysis._current_room_prices = current_prices
    s15_technical_sources._current_room_prices = current_prices
    previous = s15_technical_analysis.build_s15_operating_analysis
    if getattr(previous, "_DATA_CORRECTNESS_V1", False):
        return

    def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = dict(previous(*args, **kwargs))
        sales = dict(result.get("sales") or {})
        repository = args[0] if args else kwargs.get("repository")
        hotel_id, target_date = kwargs.get("hotel_id"), str(kwargs.get("target_date") or "")[:10]
        as_of = kwargs.get("as_of_datetime")
        age = None
        if repository is not None and hotel_id and target_date and as_of:
            try:
                rows = repository.current_forecast(str(hotel_id), target_date, str(as_of))
                snapshots = [parse_dt(row.get("snapshot_time")) for row in rows]
                snapshots = [v for v in snapshots if v]
                current = parse_dt(as_of)
                if snapshots and current:
                    age = max(int((current - max(snapshots)).total_seconds() // 60), 0)
            except Exception:
                pass
        sales["checkpoint_gap_minutes"] = age
        if age is not None and age > STALE_MINUTES:
            sales["freshness_status"] = "stale_but_usable"
            diagnosis = list(result.get("diagnosis") or [])
            if "stale_current_sales_fact" not in diagnosis:
                diagnosis.append("stale_current_sales_fact")
            result["diagnosis"] = diagnosis
            result["actions"] = [{"action_type":"suppress_actions_due_to_stale_fact","auto_executable":False}]
        result["sales"] = sales
        result["data_correctness_patch_version"] = VERSION
        return result

    build._DATA_CORRECTNESS_V1 = True  # type: ignore[attr-defined]
    s15_technical_analysis.build_s15_operating_analysis = build
    s15_s16_technical_spec_patch.build_s15_operating_analysis = build


def _patch_cache_and_build() -> None:
    from runtime.sales_progress import baseline_service, service, deviation_service
    from runtime.decisions import baseline as decision
    previous_build = baseline_service.build_baseline
    if not getattr(previous_build, "_DATA_CORRECTNESS_V1", False):
        def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(previous_build(*args, **kwargs))
            payload["data_correctness_patch_version"] = VERSION
            return payload
        build._DATA_CORRECTNESS_V1 = True  # type: ignore[attr-defined]
        baseline_service.build_baseline = build
        service._build_baseline = build
        deviation_service.build_baseline = build
        decision.build_baseline = build
    previous_cache = decision._cached_baseline
    if not getattr(previous_cache, "_DATA_CORRECTNESS_V1", False):
        def cached(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            payload = previous_cache(*args, **kwargs)
            return payload if payload and payload.get("data_correctness_patch_version") == VERSION else None
        cached._DATA_CORRECTNESS_V1 = True  # type: ignore[attr-defined]
        decision._cached_baseline = cached


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime.sales_progress.repository import DirectSalesProgressRepository
    from runtime.sales_progress import core, baseline_service, deviation_service
    DirectSalesProgressRepository.current_forecast = current_forecast
    DirectSalesProgressRepository.room_daily = room_daily
    DirectSalesProgressRepository.room_revenue = room_revenue
    core.select_complete_batch = select_batch
    baseline_service.select_complete_batch = select_batch
    deviation_service.select_complete_batch = select_batch
    _patch_analysis()
    _patch_cache_and_build()
