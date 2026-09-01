from __future__ import annotations

from collections import defaultdict
import os
from typing import Any, Mapping, Sequence

_PATCH_VERSION = "s15-s16-ai-analysis.v1"
_INSTALLED = False


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _room_id(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def merge_room_daily_fallback(
    primary_rows: Sequence[Mapping[str, Any]],
    vertical_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Fill missing date/room finals from unambiguous JY01 room dimensions.

    JL01 always wins. JY01 is accepted only when the exact canonical room_type_id
    is present and all latest non-total dimensions agree on room_nights.
    Conflicting vertical values remain unavailable rather than being averaged.
    """

    result = [dict(row) for row in primary_rows]
    present: set[tuple[str, str]] = set()
    for row in result:
        key = (_day(row.get("business_date")), _room_id(row.get("room_type_id")))
        if all(key):
            present.add(key)
        row.setdefault("final_room_nights_source", "jl01_room_type_performance_daily")

    latest_by_dimension: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for source in vertical_rows:
        row = dict(source)
        day = _day(row.get("business_date"))
        room_id = _room_id(row.get("room_type_id"))
        dimension_type = str(row.get("dimension_type") or "").strip()
        dimension_name = str(row.get("dimension_name") or "").strip()
        if not day or not room_id:
            continue
        if dimension_type == "总营业指标" or dimension_name == "总营业指标":
            continue
        key = (day, room_id, dimension_type, dimension_name)
        current = latest_by_dimension.get(key)
        if current is None or (
            str(row.get("snapshot_time") or ""), int(row.get("id") or 0)
        ) > (
            str(current.get("snapshot_time") or ""), int(current.get("id") or 0)
        ):
            latest_by_dimension[key] = row

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, row in latest_by_dimension.items():
        grouped[(key[0], key[1])].append(row)

    for key, rows in grouped.items():
        if key in present:
            continue
        nights = {_number(row.get("room_nights")) for row in rows}
        nights.discard(None)
        if len(nights) != 1:
            continue
        room_nights = next(iter(nights))
        chosen = max(
            rows,
            key=lambda row: (
                str(row.get("snapshot_time") or ""),
                int(row.get("id") or 0),
            ),
        )
        revenues = {_number(row.get("room_revenue")) for row in rows}
        revenues.discard(None)
        occupancy = {_number(row.get("occupancy_rate")) for row in rows}
        occupancy.discard(None)
        adrs = {_number(row.get("adr")) for row in rows}
        adrs.discard(None)
        revpars = {_number(row.get("revpar")) for row in rows}
        revpars.discard(None)
        result.append(
            {
                "hotel_id": chosen.get("hotel_id"),
                "business_date": key[0],
                "room_type_id": key[1],
                "room_type_name": chosen.get("dimension_name"),
                "pms_room_type_id": None,
                "pms_rate_room_type_id": None,
                "room_nights": room_nights,
                "occupancy_rate": next(iter(occupancy)) if len(occupancy) == 1 else None,
                "room_revenue": next(iter(revenues)) if len(revenues) == 1 else None,
                "adr": next(iter(adrs)) if len(adrs) == 1 else None,
                "revpar": next(iter(revpars)) if len(revpars) == 1 else None,
                "snapshot_time": chosen.get("snapshot_time"),
                "final_room_nights_source": "jy01_unambiguous_room_dimension_fallback",
                "fallback_dimension_count": len(rows),
            }
        )
    return result


def enhanced_structure_summary(
    room_results: Sequence[Mapping[str, Any]],
    hotel_target_status: str,
) -> dict[str, Any]:
    from runtime.sales_progress.core import as_float, is_fast_or_normal, is_slow

    target_usable = [
        row
        for row in room_results
        if row.get("effective_target_room_nights") not in (None, 0)
        and str((row.get("target_line") or {}).get("status")) != "unavailable"
    ]
    capacity_usable = [
        row
        for row in room_results
        if str((row.get("capacity_line") or {}).get("status")) != "unavailable"
    ]
    target_slow = [
        row for row in target_usable if is_slow(str((row.get("target_line") or {}).get("status")))
    ]
    target_fast = [
        row
        for row in target_usable
        if str((row.get("target_line") or {}).get("status")) in {"fast", "significant_fast"}
    ]
    capacity_slow = [
        row for row in capacity_usable if is_slow(str((row.get("capacity_line") or {}).get("status")))
    ]
    capacity_fast = [
        row
        for row in capacity_usable
        if str((row.get("capacity_line") or {}).get("status")) in {"fast", "significant_fast"}
    ]

    total_target = sum(
        float(row["effective_target_room_nights"])
        for row in target_usable
        if as_float(row.get("effective_target_room_nights")) is not None
    )
    slow_target = sum(
        float(row["effective_target_room_nights"])
        for row in target_slow
        if as_float(row.get("effective_target_room_nights")) is not None
    )
    slow_share = slow_target / total_target if total_target > 0 else None

    labels: list[str] = []
    if is_slow(hotel_target_status) and slow_share is not None and slow_share >= 0.5:
        labels.append("broad_based_slowdown")
    if hotel_target_status == "normal" and total_target > 0:
        for row in target_slow:
            share = float(row["effective_target_room_nights"]) / total_target
            status = str((row.get("target_line") or {}).get("status"))
            if share >= 0.15 and status in {"significant_slow", "severe_slow"}:
                labels.append("room_type_structural_lag")
                break
    if target_slow and target_fast and hotel_target_status == "normal":
        labels.append("mix_offset_detected")

    basis = "target_line" if target_usable else "capacity_line_fallback"
    selected_slow = target_slow if target_usable else capacity_slow
    selected_fast = target_fast if target_usable else capacity_fast
    gap_key = "target_line" if target_usable else "capacity_line"
    with_gap = [
        row
        for row in (target_usable if target_usable else capacity_usable)
        if as_float((row.get(gap_key) or {}).get("room_gap")) is not None
    ]
    largest_negative = (
        min(with_gap, key=lambda row: float((row.get(gap_key) or {})["room_gap"]))
        if with_gap
        else None
    )
    largest_positive = (
        max(with_gap, key=lambda row: float((row.get(gap_key) or {})["room_gap"]))
        if with_gap
        else None
    )
    return {
        "structure_basis": basis,
        "room_type_count": len(room_results),
        "capacity_line_available_count": len(capacity_usable),
        "capacity_slow_room_type_count": len(capacity_slow),
        "capacity_fast_room_type_count": len(capacity_fast),
        "target_line_available_count": len(target_usable),
        "target_slow_room_type_count": len(target_slow),
        "target_fast_room_type_count": len(target_fast),
        "slow_room_type_count": len(selected_slow),
        "fast_room_type_count": len(selected_fast),
        "slow_target_share": slow_share,
        "largest_negative_gap_room_type": (
            largest_negative.get("room_type_id") if largest_negative else None
        ),
        "largest_positive_gap_room_type": (
            largest_positive.get("room_type_id") if largest_positive else None
        ),
        "labels": labels,
        "structure_labels": labels,
        "target_structure_complete": len(target_usable) == len(room_results),
        "capacity_structure_complete": len(capacity_usable) == len(room_results),
        "hotel_target_status": hotel_target_status,
        "hotel_target_on_track": is_fast_or_normal(hotel_target_status),
    }


def build_ai_response_contract(result: Mapping[str, Any]) -> dict[str, Any]:
    intent = str(result.get("intent") or "")
    if intent == "sales_baseline_demo":
        room_ids = sorted(str(key) for key in (result.get("room_types") or {}))
        sections = [
            "结论与参考口径",
            "全店容量节奏与参考完成节奏",
            "全部房型基准",
            "平台流量与转化",
            "数据质量与不可用项",
        ]
    else:
        room_ids = sorted(
            str(row.get("room_type_id"))
            for row in (result.get("room_type_results") or [])
            if row.get("room_type_id")
        )
        sections = [
            "结论",
            "全店双线",
            "全部房型双线",
            "房型结构",
            "数据时效与边界",
        ]
    return {
        "mode": "single_pass_ai_business_analysis",
        "facts_are_authoritative": True,
        "ai_role": "只负责中文组织、业务解释和可读性，不负责重新计算事实",
        "required_sections": sections,
        "required_room_type_ids": room_ids,
        "required_room_type_count": len(room_ids),
        "must_preserve_every_room_type": True,
        "must_preserve_hotel_dual_lines": True,
        "must_preserve_data_gaps": True,
        "must_preserve_numbers_and_units": True,
        "maximum_runtime_tool_calls": 1,
        "additional_database_queries_allowed": False,
        "second_verification_pass_allowed": False,
        "style": "自然、专业、简洁，使用短标题和紧凑列表，可给出业务解读但不得夸大",
        "forbidden": [
            "把房量换算为订单数",
            "省略房型",
            "把容量线和参考完成线合并为一条",
            "暴露英文内部枚举或数据库字段",
            "新增调价、推广或满房预测结论",
            "描述工具调用、重试和调试过程",
        ],
        "fallback": "若无法完整保留全部必显信息，原样发送 send_payload.text",
        "contract_version": _PATCH_VERSION,
    }


def _patch_repository() -> None:
    from runtime.sales_progress.repository import DirectSalesProgressRepository, RepositoryError

    if getattr(DirectSalesProgressRepository, "_S15_JY01_ROOM_FALLBACK_PATCHED", False):
        return
    original = DirectSalesProgressRepository.room_daily

    def room_daily(self: Any, hotel_id: str, start_date: str, end_date: str, as_of_datetime: str) -> list[dict[str, Any]]:
        primary = list(original(self, hotel_id, start_date, end_date, as_of_datetime))
        try:
            vertical = self._query(
                """
                SELECT id, hotel_id, business_date, room_type_id,
                       dimension_type, dimension_name, room_nights,
                       occupancy_rate, room_revenue, adr, revpar, snapshot_time
                FROM jy01_hotel_statistics_daily
                WHERE hotel_id=%s AND business_date BETWEEN %s AND %s
                  AND snapshot_time<=%s
                  AND room_type_id IS NOT NULL AND room_type_id<>''
                  AND dimension_type<>'总营业指标'
                  AND dimension_name<>'总营业指标'
                ORDER BY business_date, room_type_id, snapshot_time DESC, id DESC
                """,
                (hotel_id, start_date, end_date, as_of_datetime),
            )
        except RepositoryError:
            return [dict(row) for row in primary]
        return merge_room_daily_fallback(primary, vertical)

    DirectSalesProgressRepository.room_daily = room_daily
    DirectSalesProgressRepository._S15_JY01_ROOM_FALLBACK_PATCHED = True


def _patch_structure() -> None:
    from runtime.sales_progress import core
    from runtime.sales_progress import deviation_service

    core.structure_summary = enhanced_structure_summary
    deviation_service.structure_summary = enhanced_structure_summary


def _patch_cache_contract() -> None:
    from runtime.decisions import baseline as baseline_module
    from runtime.sales_progress import baseline_service

    os.environ.setdefault("HOTEL_OTA_S15_CACHE_TTL_SECONDS", "86400")
    if not getattr(baseline_module, "_S15_CACHE_CONTRACT_PATCHED", False):
        original_cached = baseline_module._cached_baseline
        original_build = baseline_module.build_baseline

        def cached(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            payload = original_cached(*args, **kwargs)
            if payload is not None and payload.get("completeness_patch_version") != _PATCH_VERSION:
                return None
            return payload

        def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(original_build(*args, **kwargs))
            payload["completeness_patch_version"] = _PATCH_VERSION
            return payload

        baseline_module._cached_baseline = cached
        baseline_module.build_baseline = build
        baseline_module._S15_CACHE_CONTRACT_PATCHED = True

    if not getattr(baseline_service, "_S15_BUILD_MARKER_PATCHED", False):
        original_service_build = baseline_service.build_baseline

        def service_build(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(original_service_build(*args, **kwargs))
            payload["completeness_patch_version"] = _PATCH_VERSION
            return payload

        baseline_service.build_baseline = service_build
        baseline_service._S15_BUILD_MARKER_PATCHED = True


def _patch_ai_delivery_contract() -> None:
    from runtime import s15_s16_runtime_patch

    if getattr(s15_s16_runtime_patch, "_S15_S16_AI_DELIVERY_PATCHED", False):
        return
    original = s15_s16_runtime_patch._direct_delivery

    def direct_delivery(result: dict[str, Any], role: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        rendered, send_payload = original(result, role)
        contract = build_ai_response_contract(result)
        send_payload["assistant_response_contract"] = contract
        send_payload["authoritative_fallback_text"] = send_payload.get("text")
        send_payload["ai_analysis_allowed"] = True
        rendered["assistant_response_contract_version"] = _PATCH_VERSION
        return rendered, send_payload

    s15_s16_runtime_patch._direct_delivery = direct_delivery
    s15_s16_runtime_patch._S15_S16_AI_DELIVERY_PATCHED = True


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _patch_repository()
    _patch_structure()
    _patch_cache_contract()
    _patch_ai_delivery_contract()
