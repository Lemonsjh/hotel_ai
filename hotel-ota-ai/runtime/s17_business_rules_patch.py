from __future__ import annotations

import copy
import re
from collections import Counter
from typing import Any


_INSTALLED = False
_OPTIONAL_S17_SOURCES = {
    "meituan_scan_order",
    "meituan_monthly_background",
    "provider_order_detail",
    "provider_profile_background",
    "room_mix_background",
}
_FULL_OPERATIONAL_UNITS = {"orders", "rooms", "guest_name_keys"}


def _channel(value: Any) -> str:
    raw = str(value or "").strip().casefold()
    if raw.startswith(("美团", "meituan")):
        return "meituan"
    if raw.startswith(("携程", "ctrip")):
        return "ctrip"
    if raw.startswith(("飞猪", "fliggy")):
        return "fliggy"
    return "unknown"


def _patch_route_alias(route_patch: Any) -> None:
    original = route_patch._is_s17_message
    if getattr(original, "_s17_complete_alias_patch", False):
        return

    def is_s17_message(message: Any) -> bool:
        raw = str(message or "").strip().lower()
        if re.match(r"^(?:完整(?:的|版)?|详细(?:的|版)?|全部)\s*s0?17(?:\s|$)", raw):
            return True
        return original(message)

    is_s17_message._s17_complete_alias_patch = True  # type: ignore[attr-defined]
    route_patch._is_s17_message = is_s17_message


def _visible_cells(
    cells: list[dict[str, Any]], *, count_field: str, max_output_cells: int
) -> tuple[list[dict[str, Any]], int]:
    visible: list[dict[str, Any]] = []
    for cell in cells:
        try:
            cohort = max(int(float(cell.get(count_field) or 0)), 0)
        except (TypeError, ValueError):
            cohort = 0
        visible.append(
            {
                **cell,
                "privacy_cohort_size": cohort,
                "suppression_status": "visible_operational_aggregate",
            }
        )
    truncated = max(len(visible) - max_output_cells, 0)
    return visible[:max_output_cells], truncated


def _patch_operational_aggregate_suppression(repository: Any) -> None:
    original = repository.suppress_cells
    if getattr(original, "_s17_operational_aggregate_patch", False):
        return

    def suppress_cells(
        cells: list[dict[str, Any]], *, count_field: str,
        minimum_cohort_size: int, max_output_cells: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if cells:
            units = {str(cell.get("unit") or "") for cell in cells}
            # Hotel-level operational distributions are not person-level cohorts.
            # Keep privacy suppression for contact-proxy/provider/profile cells.
            if units.intersection(_FULL_OPERATIONAL_UNITS) and "contact_proxy_keys" not in units:
                return _visible_cells(
                    cells, count_field=count_field, max_output_cells=max_output_cells
                )
            first = cells[0]
            if (
                ("customer_source" in first and "record_count" in first)
                or ("room_type_id" in first and "record_count" in first)
            ):
                return _visible_cells(
                    cells, count_field=count_field, max_output_cells=max_output_cells
                )
        return original(
            cells,
            count_field=count_field,
            minimum_cohort_size=minimum_cohort_size,
            max_output_cells=max_output_cells,
        )

    suppress_cells._s17_operational_aggregate_patch = True  # type: ignore[attr-defined]
    repository.suppress_cells = suppress_cells


def _patch_booking_channels(order: Any, repository: Any) -> None:
    original = order.aggregate_bookings

    def wrapped(rows: list[dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(rows, *args, **kwargs)
        hotel_id, start, end, as_of = (
            str(kwargs["hotel_id"]), kwargs["window_start"], kwargs["window_end"], kwargs["as_of"]
        )
        scoped = [row for row in rows if order._text(row.get("hotel_id")) == hotel_id]
        latest, _ = order._latest(scoped, ("source_platform", "order_id"), as_of)
        selected = [
            row for row in latest
            if (when := order._datetime(row.get("booking_time"))) is not None and start <= when < end
        ]
        order_counts: dict[str, int] = {}
        room_counts: dict[str, int] = {}
        total_rooms = 0
        for row in selected:
            channel = _channel(row.get("member_level") or row.get("booking_product_tag"))
            rooms = max(int(order._number(row.get("room_count")) or 0), 0)
            order_counts[channel] = order_counts.get(channel, 0) + 1
            room_counts[channel] = room_counts.get(channel, 0) + rooms
            total_rooms += rooms
        result["booking_channel_order_distribution"] = order._distribution(
            Counter(order_counts), len(selected), unit="orders"
        )
        result["booking_channel_room_distribution"] = order._distribution(
            Counter(room_counts), total_rooms, unit="rooms"
        )
        result["booking_channel_unknown_orders"] = order_counts.get("unknown", 0)
        result["booking_channel_unknown_rooms"] = room_counts.get("unknown", 0)
        result["booking_channel_share_denominator"] = "all_orders_in_booking_window"
        return result

    order.aggregate_bookings = wrapped
    repository.aggregate_bookings = wrapped


def _patch_arrivals(arrival: Any, order: Any, repository: Any) -> None:
    original = arrival.aggregate_arrivals

    def wrapped(rows: list[dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        all_result = original(rows, *args, **kwargs)
        hotel_id, start, end, as_of = (
            str(kwargs["hotel_id"]), kwargs["window_start"], kwargs["window_end"], kwargs["as_of"]
        )
        scoped = [row for row in rows if order._text(row.get("hotel_id")) == hotel_id]
        latest, _ = order._latest(scoped, ("source_platform", "order_id"), as_of)
        planned_rows = [
            row for row in latest
            if (when := order._datetime(row.get("arrival_time"))) is not None
            and start <= when < end
            and order._status(row.get("booking_status") or row.get("order_status")) != "cancelled"
        ]
        planned = original(planned_rows, *args, **kwargs)
        planned_nights = 0
        for row in planned_rows:
            rooms = max(int(order._number(row.get("room_count")) or 0), 0)
            _, nights = order._stay_bucket(
                order._datetime(row.get("arrival_time")), order._datetime(row.get("departure_time"))
            )
            if nights is not None and nights > 0:
                planned_nights += rooms * nights
        total = int(all_result.get("arrival_order_count") or 0)
        cancelled = int(all_result.get("current_cancelled_orders") or 0)
        planned_count = int(planned.get("arrival_order_count") or 0)
        planned.update({
            "population_definition": "latest JD01 arrival-window orders; planned-arrival structure excludes cancelled orders",
            "arrival_window_order_count": total,
            "arrival_order_count": planned_count,
            "planned_arrival_order_count": planned_count,
            "planned_arrival_booked_rooms": planned.get("booked_rooms"),
            "planned_room_nights": planned_nights,
            "current_cancelled_orders": cancelled,
            "current_cancelled_share": order._ratio(cancelled, total),
            "current_non_cancelled_orders": planned_count,
            "missing_dedup_key_count": all_result.get("missing_dedup_key_count"),
            "cancelled_orders_excluded_from_planned_arrival_structure": True,
        })
        return planned

    arrival.aggregate_arrivals = wrapped
    repository.aggregate_arrivals = wrapped


def _patch_realized(order: Any, repository: Any) -> None:
    def aggregate_realized(
        rows: list[dict[str, Any]], *, hotel_id: str,
        window_start: Any, window_end: Any, as_of: Any,
    ) -> dict[str, Any]:
        scoped = [row for row in rows if order._text(row.get("hotel_id")) == hotel_id]
        latest, missing = order._latest(
            scoped,
            ("business_date", "source_platform", "order_id", "room_no", "charge_subject"),
            as_of,
        )
        approved_subjects = set(order._approved_room_charge_subjects())
        approved_subjects.add("加收全天")
        source_nights: Counter[str] = Counter()
        source_fee: Counter[str] = Counter()
        source_records: Counter[str] = Counter()
        room_nights: Counter[str] = Counter()
        room_fee: Counter[str] = Counter()
        room_records: Counter[str] = Counter()
        room_names: dict[str, str] = {}
        stay_groups: dict[tuple[str, str, str, str], list[tuple[dict[str, Any], float]]] = {}
        reconciliation_amount = 0.0
        excluded_unapproved_charge_amount = 0.0
        excluded_unapproved_charge_record_count = 0
        unmapped = 0

        for row in latest:
            business_time = order._datetime(row.get("business_date"))
            if business_time is None or not window_start <= business_time < window_end:
                continue
            nights = max(order._number(row.get("room_nights")) or 0, 0)
            fee = order._number(row.get("room_fee")) or 0
            charge_subject = order._text(row.get("charge_subject"))
            source = order._text(row.get("customer_source")) or "unknown"
            room_type_id = order._text(row.get("room_type_id"))
            room_type_name = order._text(row.get("room_type_name"))
            if room_type_id and room_type_name:
                room_names.setdefault(room_type_id, room_type_name)
            if nights == 0:
                reconciliation_amount += fee
                continue
            if charge_subject not in approved_subjects:
                excluded_unapproved_charge_record_count += 1
                excluded_unapproved_charge_amount += fee
                continue

            source_fee[source] += fee
            source_records[source] += 1
            if room_type_id:
                room_fee[room_type_id] += fee
                room_records[room_type_id] += 1
            else:
                unmapped += 1

            stay_key = (
                order._text(row.get("business_date")),
                order._text(row.get("source_platform")),
                order._text(row.get("order_id")),
                order._text(row.get("room_no")),
            )
            stay_groups.setdefault(stay_key, []).append((row, nights))

        for group in stay_groups.values():
            representative, _ = min(
                group,
                key=lambda item: (
                    0 if order._text(item[0].get("charge_subject")) == "房费" else 1,
                    order._text(item[0].get("charge_subject")),
                ),
            )
            nights = max(item[1] for item in group)
            source = order._text(representative.get("customer_source")) or "unknown"
            room_type_id = order._text(representative.get("room_type_id"))
            room_type_name = order._text(representative.get("room_type_name"))
            if room_type_id and room_type_name:
                room_names.setdefault(room_type_id, room_type_name)
            source_nights[source] += nights
            if room_type_id:
                room_nights[room_type_id] += nights

        total_nights = float(sum(source_nights.values()))
        total_fee = float(sum(source_fee.values()))
        source_keys = sorted(
            set(source_nights) | set(source_fee),
            key=lambda key: (-source_nights[key], -source_fee[key], key),
        )
        room_keys = sorted(
            set(room_nights) | set(room_fee),
            key=lambda key: (-room_nights[key], -room_fee[key], key),
        )
        return {
            "population_id": "realized_stay",
            "population_definition": "latest approved RS01 lodging-charge records in business-date window",
            "window_field": "business_date",
            "window_start": window_start.isoformat(sep=" "),
            "window_end": window_end.isoformat(sep=" "),
            "as_of_datetime": as_of.isoformat(sep=" "),
            "source": "rs01_room_revenue_daily",
            "grain": "charge rows latest by business_date+source_platform+order_id+room_no+charge_subject; room nights deduplicated across charge subjects",
            "unit": "room_nights_currency_and_adr",
            "approved_charge_subjects": sorted(approved_subjects),
            "charge_subject_policy_revision": "s17-lodging-charge-subjects.v2",
            "realized_stay_evidence_rule": "positive room_nights independent of charge_subject",
            "room_night_count_rule": "max positive room_nights once per business_date+source_platform+order_id+room_no across approved lodging subjects",
            "realized_room_nights": total_nights,
            "realized_room_fee": round(total_fee, 2),
            "realized_adr": round(total_fee / total_nights, 2) if total_nights else None,
            "source_distribution": [
                {
                    "customer_source": key,
                    "realized_room_nights": source_nights[key],
                    "realized_room_fee": round(source_fee[key], 2),
                    "record_count": source_records[key],
                    "room_night_share": order._ratio(source_nights[key], total_nights),
                    "revenue_share": order._ratio(source_fee[key], total_fee),
                }
                for key in source_keys
            ],
            "room_type_distribution": [
                {
                    "room_type_id": key,
                    "room_type_name": room_names.get(key) or "房型名称未映射",
                    "realized_room_nights": room_nights[key],
                    "realized_room_fee": round(room_fee[key], 2),
                    "record_count": room_records[key],
                    "realized_adr": round(room_fee[key] / room_nights[key], 2) if room_nights[key] else None,
                }
                for key in room_keys
            ],
            "reconciliation_amount": round(reconciliation_amount, 2),
            "excluded_unapproved_charge_record_count": excluded_unapproved_charge_record_count,
            "excluded_unapproved_charge_amount": round(excluded_unapproved_charge_amount, 2),
            "unmapped_count": unmapped,
            "missing_dedup_key_count": missing,
        }

    order.aggregate_realized = aggregate_realized
    repository.aggregate_realized = aggregate_realized


def _patch_guest_frequency(guest: Any, frequency_patch: Any) -> None:
    original = guest.aggregate_real_guest_frequency

    def level(count: int) -> str:
        if count <= 0:
            return "窗口内0次"
        if count == 1:
            return "窗口内1次"
        if count == 2:
            return "窗口内2次"
        return "窗口内3–4次" if count <= 4 else "窗口内5次及以上"

    guest.guest_frequency_level = level

    def wrapped(
        realized_rows: list[dict[str, Any]], booking_rows: list[dict[str, Any]],
        *args: Any, **kwargs: Any,
    ) -> dict[str, Any]:
        # charge_subject describes revenue classification, not whether a stay happened.
        # Reuse the mature guest-frequency algorithm by normalizing every positive-night
        # RS01 row to an approved subject inside this frequency-only copy.
        frequency_rows: list[dict[str, Any]] = []
        for row in realized_rows:
            candidate = dict(row)
            if max(guest._number(row.get("room_nights")) or 0, 0) > 0:
                candidate["charge_subject"] = "房费"
            frequency_rows.append(candidate)
        result = original(frequency_rows, booking_rows, *args, **kwargs)
        hotel_id, start, end, as_of = (
            str(kwargs["hotel_id"]), kwargs["window_start"], kwargs["window_end"], kwargs["as_of"]
        )
        scoped = [row for row in realized_rows if guest._text(row.get("hotel_id")) == hotel_id]
        latest, _ = guest._latest(
            scoped, ("business_date", "source_platform", "order_id", "room_no", "charge_subject"), as_of
        )
        valid_names = {
            name for row in latest
            if (when := guest._visit_time(row)) is not None and start <= when < end
            and (name := guest.normalize_guest_name(row.get("guest_name"))) is not None
        }
        evaluable = int(result.get("unique_guest_name_count") or 0)
        rank = {"窗口内1次": 0, "窗口内2次": 1, "窗口内3–4次": 2, "窗口内5次及以上": 3}
        result["frequency_distribution"] = sorted(
            result.get("frequency_distribution") or [],
            key=lambda cell: rank.get(str(cell.get("name") or ""), 99),
        )
        result.update({
            "status": "ok" if valid_names else "unavailable",
            "reason": None if valid_names else "no_valid_guest_names_in_window",
            "valid_guest_name_count": len(valid_names),
            "realized_frequency_guest_name_count": evaluable,
            "unique_guest_name_count_semantics": "realized_frequency_guest_name_count",
            "customer_name_total_rule": "distinct_normalized_valid_guest_name_in_window",
            "frequency_evaluable_name_rule": "valid_guest_name_with_positive_room_nights_realized_stay_evidence",
            "visit_count_rule": "distinct_realized_stay_order_per_guest_name_independent_of_charge_subject",
            "charge_subject_filter_for_frequency": False,
            "frequency_level_rule": {
                "1": "窗口内1次", "2": "窗口内2次",
                "3-4": "窗口内3–4次", "5+": "窗口内5次及以上"
            },
        })
        return result

    guest.aggregate_real_guest_frequency = wrapped
    frequency_patch.aggregate_real_guest_frequency = wrapped


def _patch_repository(repository: Any) -> None:
    original_query = repository.query_mysql_s17

    def query(conn: Any, args: Any, profile: dict[str, Any]) -> dict[str, Any]:
        safe_profile = profile
        columns = (
            ((profile.get("columns") or {}).get(repository.CORE_TABLES["booking"]) or {})
            if isinstance(profile, dict) else {}
        )
        if not columns.get("member_level") and columns.get("booking_product_tag"):
            safe_profile = copy.deepcopy(profile)
            safe_profile.setdefault("columns", {}).setdefault(
                repository.CORE_TABLES["booking"], {}
            )["member_level"] = columns["booking_product_tag"]
        payload = original_query(conn, args, safe_profile)
        payload["data_gaps"] = [
            item for item in payload.get("data_gaps") or []
            if str(item) not in _OPTIONAL_S17_SOURCES
        ]
        privacy = payload.get("privacy_policy")
        if isinstance(privacy, dict):
            privacy["hotel_operational_aggregate_small_cell_suppression"] = False
            privacy["person_or_profile_cohort_small_cell_suppression"] = True
        return payload

    repository.query_mysql_s17 = query


def _patch_renderer(customer: Any) -> None:
    previous = customer.render_s17_summary
    customer.CHANNEL_LABELS["ctrip"] = "携程"

    def render(payload: dict[str, Any]) -> str:
        lines = []
        hidden = (
            "当前物理在住", "到店订单（按计划到店时间统计）：",
            "到店 cohort（", "真实住客到店频率（",
            "预订渠道（由产品标签批准字典派生）：", "实际入住房型：",
        )
        for line in previous(payload).splitlines():
            if line.startswith(hidden):
                continue
            lines.append(
                line.replace("到店订单入住时长结构：", "计划到店订单入住时长结构：")
                .replace("到店 cohort 入住时长结构：", "计划到店订单入住时长结构：")
                .replace("批准房费科目金额", "住宿相关收入")
                .replace("房费科目核查：", "住宿收费科目核查：")
                .replace("（JD04，不与物理在住相加）", "（JD04，独立口径）")
                .replace("、物理在住和续住属于不同统计口径", "和续住属于不同统计口径")
                .replace("、物理在住和续住是不同统计口径", "和续住是不同统计口径")
            )
        populations = payload.get("populations") if isinstance(payload.get("populations"), dict) else {}
        booking = populations.get("pms_booking_created") if isinstance(populations.get("pms_booking_created"), dict) else {}
        arrival = populations.get("pms_arrival_cohort") if isinstance(populations.get("pms_arrival_cohort"), dict) else {}
        realized = populations.get("realized_stay") if isinstance(populations.get("realized_stay"), dict) else {}
        frequency = populations.get("real_guest_frequency") if isinstance(populations.get("real_guest_frequency"), dict) else {}
        additions = []
        channels = booking.get("booking_channel_order_distribution") or []
        if booking.get("booking_channel_status") != "unavailable" and channels:
            additions.append(
                "预订渠道（全部订单为分母，未知渠道保留）："
                + customer._distribution_text(channels, labels=customer.CHANNEL_LABELS, suffix="单")
                + "。"
            )
        if arrival:
            additions.append(
                "计划到店订单："
                f"{customer._display_number(arrival.get('planned_arrival_order_count', arrival.get('arrival_order_count')))} 单，"
                f"{customer._display_number(arrival.get('booked_rooms'))} 间预订房，"
                f"计划入住 {customer._display_number(arrival.get('planned_room_nights'))} 间夜；"
                f"窗口内取消 {customer._display_number(arrival.get('current_cancelled_orders'))} 单"
                f"（{customer._display_percent(arrival.get('current_cancelled_share'))}），"
                "取消订单不计入计划到店结构。"
            )
            if arrival.get("room_type_room_distribution"):
                additions.append(
                    "计划到店房型："
                    + customer._distribution_text(
                        arrival["room_type_room_distribution"], suffix="间预订房"
                    )
                    + "。"
                )
        realized_room_types = realized.get("room_type_distribution") or []
        if realized_room_types:
            additions.append(
                "实际入住房型："
                + customer._distribution_text(
                    realized_room_types,
                    name_field="room_type_name",
                    value_field="realized_room_nights",
                    suffix="间夜",
                )
                + "。"
            )
        if frequency.get("status") == "ok":
            additions.append(
                f"客户姓名：窗口内识别到 {int(frequency.get('valid_guest_name_count') or 0)} 个有效客户姓名"
                "（按姓名归并，不代表唯一自然人）；"
                f"其中 {int(frequency.get('realized_frequency_guest_name_count') or 0)} 个姓名有已实现住宿频次证据。"
            )
            cells = frequency.get("frequency_distribution") or []
            additions.append(
                "已实现住宿频次："
                + (
                    customer._distribution_text(cells, suffix="位") + "。"
                    if cells else "当前没有可展示的频次分布。"
                )
            )
        boundary = next((i for i, line in enumerate(lines) if line.startswith("边界：")), len(lines))
        lines[boundary:boundary] = additions
        return "\n".join(lines)

    customer.render_s17_summary = render


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.adapters import s17_repository as repository
    from runtime.algorithms import customer_arrival, customer_order, guest_frequency
    from runtime.decisions import customer
    import runtime.s17_feishu_route_patch as route_patch
    import runtime.s17_guest_frequency_patch as frequency_patch

    _patch_route_alias(route_patch)
    _patch_operational_aggregate_suppression(repository)
    _patch_realized(customer_order, repository)
    _patch_repository(repository)
    _patch_booking_channels(customer_order, repository)
    _patch_arrivals(customer_arrival, customer_order, repository)
    _patch_guest_frequency(guest_frequency, frequency_patch)
    _patch_renderer(customer)
