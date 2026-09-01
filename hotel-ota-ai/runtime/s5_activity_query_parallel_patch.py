from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable

VERSION = "s5-activity-query-parallel.v1"
_SUMMARY_TEMPLATE = "ota_activity_summary"
_DETAIL_TEMPLATE = "ota_activity_product_detail"
_INSTALLED = False
_PENDING_DETAIL: ContextVar[dict[str, Any] | None] = ContextVar(
    "hotel_ota_s5_pending_activity_detail",
    default=None,
)


def _request_key(
    query: Callable[..., dict[str, Any]],
    *,
    hotel_id: str,
    target_stay_date: str,
    as_of_time: str | None,
) -> tuple[int, str, str, str]:
    return (
        id(query),
        str(hotel_id),
        str(target_stay_date),
        str(as_of_time or ""),
    )


def install() -> None:
    """Parallelize S5's two independent activity reads without changing results."""
    global _INSTALLED
    if _INSTALLED:
        return

    from runtime import s5_product_net_revenue_patch as target

    original = target._query_template
    if getattr(original, "_S5_ACTIVITY_QUERY_PARALLEL_V1", False):
        _INSTALLED = True
        return

    @wraps(original)
    def query_template_parallel(
        query: Callable[..., dict[str, Any]],
        template: str,
        *,
        hotel_id: str,
        target_stay_date: str,
        as_of_time: str | None,
    ) -> dict[str, Any]:
        key = _request_key(
            query,
            hotel_id=hotel_id,
            target_stay_date=target_stay_date,
            as_of_time=as_of_time,
        )

        pending = _PENDING_DETAIL.get()
        if template == _DETAIL_TEMPLATE and pending and pending.get("key") == key:
            _PENDING_DETAIL.set(None)
            return dict(pending["result"])

        if template != _SUMMARY_TEMPLATE:
            return original(
                query,
                template,
                hotel_id=hotel_id,
                target_stay_date=target_stay_date,
                as_of_time=as_of_time,
            )

        def run(activity_template: str) -> dict[str, Any]:
            return original(
                query,
                activity_template,
                hotel_id=hotel_id,
                target_stay_date=target_stay_date,
                as_of_time=as_of_time,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            summary_future = executor.submit(run, _SUMMARY_TEMPLATE)
            detail_future = executor.submit(run, _DETAIL_TEMPLATE)
            summary_result = summary_future.result()
            detail_result = detail_future.result()

        _PENDING_DETAIL.set({"key": key, "result": detail_result})
        return summary_result

    query_template_parallel._S5_ACTIVITY_QUERY_PARALLEL_V1 = True  # type: ignore[attr-defined]
    query_template_parallel._S5_ACTIVITY_QUERY_PARALLEL_VERSION = VERSION  # type: ignore[attr-defined]
    target._query_template = query_template_parallel
    _INSTALLED = True
