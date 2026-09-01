from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable

from runtime.adapters import database as database_adapter
from runtime.algorithms import s2_operating_views
from runtime.algorithms.s2_operating_views import FLOW_SOURCE_TABLE, _flow_view

VERSION = "s2-business-metrics-business-date.v2"
SOURCE_TABLE = FLOW_SOURCE_TABLE
_INSTALLED = False
_S2_MEITUAN_BUSINESS_DATE_ONLY: ContextVar[bool] = ContextVar(
    "s2_meituan_business_date_only",
    default=False,
)
_ORIGINAL_LATEST_SNAPSHOT_CLAUSE = database_adapter._latest_snapshot_clause


def _latest_snapshot_clause(
    table: str,
    columns: dict[str, str],
    scope_parts: list[str],
    scope_params: list[Any],
) -> tuple[str, list[Any]]:
    """Bypass global snapshot filtering only for S2's Meituan daily metrics read."""
    if _S2_MEITUAN_BUSINESS_DATE_ONLY.get() and str(table) == SOURCE_TABLE:
        return "", []
    return _ORIGINAL_LATEST_SNAPSHOT_CLAUSE(table, columns, scope_parts, scope_params)


def _query_exact_meituan_metrics(
    query: Callable[..., dict[str, Any]],
    *,
    hotel_id: str,
    business_date: str,
) -> dict[str, Any]:
    """Read every Meituan metric row for one exact business_date.

    Source contract: hotel_id + business_date + metric_code is unique and all
    metric codes for the business day are synchronously persisted. Therefore
    snapshot_time is evidence/freshness metadata only and must not filter rows.
    """
    token = _S2_MEITUAN_BUSINESS_DATE_ONLY.set(True)
    try:
        return query(
            "ota_business_metrics",
            hotel_id,
            date=str(business_date)[:10],
            source_platform="meituan",
        )
    finally:
        _S2_MEITUAN_BUSINESS_DATE_ONLY.reset(token)


def _payload_rows(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows") or []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _replace_market_meituan_rows(
    market_result: dict[str, Any],
    meituan_result: dict[str, Any],
    *,
    business_date: str,
) -> dict[str, Any]:
    """Keep non-Meituan market rows and replace Meituan rows with S2's full day set."""
    result = dict(market_result or {})
    payload = result.get("payload")
    if not isinstance(payload, dict):
        return result
    payload = dict(payload)
    target_date = str(business_date)[:10]
    existing_rows = _payload_rows(result)
    meituan_rows = [
        row
        for row in _payload_rows(meituan_result)
        if s2_operating_views._platform(row) == "meituan"
        and str(row.get("business_date") or "")[:10] == target_date
    ]
    kept_rows = [row for row in existing_rows if s2_operating_views._platform(row) != "meituan"]
    rows = [*kept_rows, *meituan_rows]
    payload["rows"] = rows
    for key in ("row_count", "raw_row_count", "filtered_row_count"):
        if key in payload:
            payload[key] = len(rows)
    payload["s2_meituan_business_date_policy"] = "hotel_id_business_date_only"
    result["payload"] = payload
    return result


def _wrap_optional_loader(
    previous: Callable[..., dict[str, dict[str, Any]]],
) -> Callable[..., dict[str, dict[str, Any]]]:
    def load_s2_optional_results(
        query: Callable[..., dict[str, Any]],
        *,
        hotel_id: str,
        business_date: str,
        as_of_time: str | None,
    ) -> dict[str, dict[str, Any]]:
        def scoped_query(template: str, query_hotel_id: str, **kwargs: Any) -> dict[str, Any]:
            platform = str(kwargs.get("source_platform") or "").strip().lower()
            if template == "ota_business_metrics" and platform in {"meituan", "美团"}:
                return _query_exact_meituan_metrics(
                    query,
                    hotel_id=query_hotel_id,
                    business_date=str(kwargs.get("date") or business_date)[:10],
                )
            return query(template, query_hotel_id, **kwargs)

        results = dict(
            previous(
                scoped_query,
                hotel_id=hotel_id,
                business_date=business_date,
                as_of_time=as_of_time,
            )
            or {}
        )
        flow_result = results.get("flow_conversion")
        market_result = results.get("market_metrics")
        if isinstance(flow_result, dict) and isinstance(market_result, dict):
            results["market_metrics"] = _replace_market_meituan_rows(
                market_result,
                flow_result,
                business_date=business_date,
            )
        return results

    load_s2_optional_results._S2_BUSINESS_DATE_METRICS_V2 = True  # type: ignore[attr-defined]
    return load_s2_optional_results


def _load_exact_historical_flow(
    router: Any,
    *,
    hotel_id: str,
    business_date: str,
) -> dict[str, Any]:
    """Read all Meituan metric rows for one historical business date."""
    try:
        raw = _query_exact_meituan_metrics(
            router.database_template_result,
            hotel_id=hotel_id,
            business_date=business_date,
        )
    except Exception as exc:  # Flow is optional evidence; do not break PMS history.
        raw = {
            "status": "data_gap",
            "reason": f"historical_flow_query_failed:{exc.__class__.__name__}",
        }
    result = dict(raw or {})
    result["_s2_requested_business_date"] = str(business_date)[:10]
    result["_s2_source_table"] = FLOW_SOURCE_TABLE
    return _flow_view(result)


def _wrap_historical_builder(previous: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def _build_historical_snapshot_result(
        router: Any,
        *,
        hotel_id: str,
        role: str,
        output_profile: str | None,
        target_business_date: str,
        as_of_time: str | None = None,
    ) -> dict[str, Any]:
        result = dict(
            previous(
                router,
                hotel_id=hotel_id,
                role=role,
                output_profile=output_profile,
                target_business_date=target_business_date,
                as_of_time=as_of_time,
            )
            or {}
        )
        if result.get("status") != "ok" or not result.get("historical_daily"):
            return result
        views_raw = result.get("operating_views")
        if not isinstance(views_raw, dict):
            return result

        business_date = str(result.get("business_date") or target_business_date)[:10]
        flow = _load_exact_historical_flow(
            router,
            hotel_id=hotel_id,
            business_date=business_date,
        )
        views = dict(views_raw)
        views["flow_conversion"] = flow
        quality_flags = [
            flag
            for flag in (views.get("quality_flags") or [])
            if not str(flag).startswith("flow_conversion:")
        ]
        if flow.get("status") != "ok":
            quality_flags.append(f"flow_conversion:{flow.get('status') or 'data_gap'}")
        views["quality_flags"] = list(dict.fromkeys(quality_flags))
        result["operating_views"] = views
        result["historical_flow_source_table"] = FLOW_SOURCE_TABLE
        result["historical_flow_snapshot_policy"] = "business_date_only_no_snapshot_filter"
        return result

    _build_historical_snapshot_result._S2_HISTORICAL_FLOW_SNAPSHOT_V1 = True  # type: ignore[attr-defined]
    return _build_historical_snapshot_result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    if not getattr(database_adapter._latest_snapshot_clause, "_S2_BUSINESS_DATE_METRICS_V2", False):
        _latest_snapshot_clause._S2_BUSINESS_DATE_METRICS_V2 = True  # type: ignore[attr-defined]
        database_adapter._latest_snapshot_clause = _latest_snapshot_clause

    from runtime import feishu_command_router as router
    from runtime import s2_historical_daily_source_patch as historical

    previous_loader = router.load_s2_optional_results
    if not getattr(previous_loader, "_S2_BUSINESS_DATE_METRICS_V2", False):
        wrapped_loader = _wrap_optional_loader(previous_loader)
        router.load_s2_optional_results = wrapped_loader
        s2_operating_views.load_s2_optional_results = wrapped_loader

    previous = historical._build_historical_snapshot_result
    if not getattr(previous, "_S2_HISTORICAL_FLOW_SNAPSHOT_V1", False):
        historical._build_historical_snapshot_result = _wrap_historical_builder(previous)
    historical.S2_HISTORICAL_FLOW_SNAPSHOT_VERSION = VERSION
