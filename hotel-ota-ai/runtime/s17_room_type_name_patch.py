from __future__ import annotations

import copy
import datetime as dt
from collections import Counter
from typing import Any, Callable

_INSTALLED = False
_MISSING_ROOM_TYPE_NAME = "房型名称未映射"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _name_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    candidates: dict[str, Counter[str]] = {}
    for row in rows:
        room_type_id = _text(row.get("room_type_id"))
        room_type_name = _text(row.get("room_type_name"))
        if not room_type_id or not room_type_name:
            continue
        candidates.setdefault(room_type_id, Counter())[room_type_name] += 1
    return {
        room_type_id: sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        for room_type_id, counts in candidates.items()
    }


def _decorate_named_distribution(
    cells: list[dict[str, Any]],
    names: dict[str, str],
    *,
    id_field: str,
    public_name_field: str = "name",
) -> list[dict[str, Any]]:
    decorated: list[dict[str, Any]] = []
    for cell in cells or []:
        item = dict(cell)
        room_type_id = _text(item.get(id_field))
        room_type_name = names.get(room_type_id)
        item["room_type_id"] = room_type_id or None
        item["room_type_name"] = room_type_name or None
        item["room_type_name_status"] = "ok" if room_type_name else "unavailable"
        item[public_name_field] = room_type_name or _MISSING_ROOM_TYPE_NAME
        decorated.append(item)
    return decorated


def _booking_rows(order: Any, rows: list[dict[str, Any]], kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    hotel_id = str(kwargs["hotel_id"])
    window_start = kwargs["window_start"]
    window_end = kwargs["window_end"]
    as_of = kwargs["as_of"]
    scoped = [row for row in rows if order._text(row.get("hotel_id")) == hotel_id]
    latest, _ = order._latest(scoped, ("source_platform", "order_id"), as_of)
    selected = []
    for row in latest:
        booking_time = order._datetime(row.get("booking_time"))
        if booking_time is not None and window_start <= booking_time < window_end:
            selected.append(row)
    return selected


def _arrival_rows(order: Any, rows: list[dict[str, Any]], kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    hotel_id = str(kwargs["hotel_id"])
    window_start = kwargs["window_start"]
    window_end = kwargs["window_end"]
    as_of = kwargs["as_of"]
    scoped = [row for row in rows if order._text(row.get("hotel_id")) == hotel_id]
    latest, _ = order._latest(scoped, ("source_platform", "order_id"), as_of)
    return [
        row
        for row in latest
        if (arrival := order._datetime(row.get("arrival_time"))) is not None
        and window_start <= arrival < window_end
    ]


def _realized_rows(order: Any, rows: list[dict[str, Any]], kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    hotel_id = str(kwargs["hotel_id"])
    window_start = kwargs["window_start"]
    window_end = kwargs["window_end"]
    as_of = kwargs["as_of"]
    scoped = [row for row in rows if order._text(row.get("hotel_id")) == hotel_id]
    latest, _ = order._latest(
        scoped,
        ("business_date", "source_platform", "order_id", "room_no", "charge_subject"),
        as_of,
    )
    return [
        row
        for row in latest
        if (business_time := order._datetime(row.get("business_date"))) is not None
        and window_start <= business_time < window_end
    ]


def _physical_rows(order: Any, rows: list[dict[str, Any]], kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    hotel_id = str(kwargs["hotel_id"])
    business_date = kwargs["business_date"]
    as_of = kwargs["as_of"]
    scoped = [
        row for row in rows
        if order._text(row.get("hotel_id")) == hotel_id
        and order._datetime(row.get("snapshot_time"))
        and order._datetime(row.get("snapshot_time")) <= as_of
    ]
    snapshots = [
        order._datetime(row.get("snapshot_time"))
        for row in scoped
        if order._datetime(row.get("business_date"))
        and order._datetime(row.get("business_date")).date() == business_date
    ]
    selected = max((value for value in snapshots if value), default=None)
    batch = [row for row in scoped if order._datetime(row.get("snapshot_time")) == selected] if selected else []
    latest, _ = order._latest(batch, ("room_no",), as_of)
    return latest


def _extension_rows(order: Any, rows: list[dict[str, Any]], kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    hotel_id = str(kwargs["hotel_id"])
    as_of = kwargs["as_of"]
    scoped = [row for row in rows if order._text(row.get("hotel_id")) == hotel_id]
    latest, _ = order._latest(scoped, ("source_platform", "order_id", "room_no"), as_of)
    selected = []
    for row in latest:
        checkin = order._datetime(row.get("checkin_time"))
        checkout = order._datetime(row.get("checkout_time"))
        if checkin and checkout and checkin <= as_of < checkout:
            selected.append(row)
    return selected


def _wrap_aggregate(
    original: Callable[..., dict[str, Any]],
    selector: Callable[[Any, list[dict[str, Any]], dict[str, Any]], list[dict[str, Any]]],
    *,
    distribution_fields: tuple[tuple[str, str], ...],
    decorate_matrix: bool = False,
) -> Callable[..., dict[str, Any]]:
    def wrapped(rows: list[dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        from runtime.algorithms import customer_order as order

        result = original(rows, *args, **kwargs)
        selected = selector(order, rows, kwargs)
        names = _name_map(selected)
        for field, id_field in distribution_fields:
            result[field] = _decorate_named_distribution(
                result.get(field) or [],
                names,
                id_field=id_field,
            )
        if decorate_matrix:
            matrix = []
            for cell in result.get("booking_matrix") or []:
                item = dict(cell)
                room_type_id = _text(item.get("room_type_id"))
                item["room_type_name"] = names.get(room_type_id)
                item["room_type_name_status"] = "ok" if names.get(room_type_id) else "unavailable"
                matrix.append(item)
            result["booking_matrix"] = matrix
        result["room_type_name_coverage"] = {
            "mapped_room_type_ids": len(names),
            "display_fallback": _MISSING_ROOM_TYPE_NAME,
        }
        return result

    wrapped._s17_room_type_name_patch = True  # type: ignore[attr-defined]
    return wrapped


def _install_repository_field_patch(repository: Any) -> None:
    original = repository._mapped_rows
    if getattr(original, "_s17_room_type_name_patch", False):
        return

    def mapped_rows(
        conn: Any,
        profile: dict[str, Any],
        table_key: str,
        hotel_id: str,
        *,
        as_of: dt.datetime,
        fields: tuple[str, ...],
        extra_where: list[tuple[str, str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if table_key in {
            "reservation_snapshot",
            "room_fee_daily",
            "room_status_snapshot",
            "stayover_snapshot",
        } and "room_type_name" not in fields:
            fields = (*fields, "room_type_name")
        return original(
            conn,
            profile,
            table_key,
            hotel_id,
            as_of=as_of,
            fields=fields,
            extra_where=extra_where,
        )

    mapped_rows._s17_room_type_name_patch = True  # type: ignore[attr-defined]
    repository._mapped_rows = mapped_rows


def _install_customer_render_patch(customer: Any) -> None:
    original = customer.render_s17_summary
    if getattr(original, "_s17_room_type_name_patch", False):
        return

    def render_s17_summary(payload: dict[str, Any]) -> str:
        safe_payload = copy.deepcopy(payload or {})
        populations = safe_payload.get("populations") if isinstance(safe_payload.get("populations"), dict) else {}
        for population_id in ("realized_stay", "physical_occupancy", "extension_reconciliation"):
            population = populations.get(population_id)
            if not isinstance(population, dict):
                continue
            for cell in population.get("room_type_distribution") or []:
                cell["room_type_id"] = cell.get("room_type_name") or _MISSING_ROOM_TYPE_NAME
                cell["name"] = cell.get("room_type_name") or _MISSING_ROOM_TYPE_NAME
        return original(safe_payload)

    render_s17_summary._s17_room_type_name_patch = True  # type: ignore[attr-defined]
    customer.render_s17_summary = render_s17_summary


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.adapters import s17_repository as repository
    from runtime.algorithms import customer_arrival, customer_order
    from runtime.decisions import customer

    _install_repository_field_patch(repository)

    booking = _wrap_aggregate(
        customer_order.aggregate_bookings,
        _booking_rows,
        distribution_fields=(("room_type_order_distribution", "name"), ("room_type_room_distribution", "name")),
        decorate_matrix=True,
    )
    arrival = _wrap_aggregate(
        customer_arrival.aggregate_arrivals,
        _arrival_rows,
        distribution_fields=(("room_type_order_distribution", "name"), ("room_type_room_distribution", "name")),
    )
    realized = _wrap_aggregate(
        customer_order.aggregate_realized,
        _realized_rows,
        distribution_fields=(("room_type_distribution", "room_type_id"),),
    )
    physical = _wrap_aggregate(
        customer_order.aggregate_physical,
        _physical_rows,
        distribution_fields=(("room_type_distribution", "room_type_id"),),
    )
    extensions = _wrap_aggregate(
        customer_order.aggregate_extensions,
        _extension_rows,
        distribution_fields=(("room_type_distribution", "room_type_id"),),
    )

    customer_order.aggregate_bookings = booking
    customer_arrival.aggregate_arrivals = arrival
    customer_order.aggregate_realized = realized
    customer_order.aggregate_physical = physical
    customer_order.aggregate_extensions = extensions

    repository.aggregate_bookings = booking
    repository.aggregate_arrivals = arrival
    repository.aggregate_realized = realized
    repository.aggregate_physical = physical
    repository.aggregate_extensions = extensions

    _install_customer_render_patch(customer)
