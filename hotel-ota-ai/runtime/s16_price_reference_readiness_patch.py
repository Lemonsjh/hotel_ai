from __future__ import annotations

import re
from typing import Any, Mapping

_INSTALLED = False
VERSION = "s16-room-net-price-comparison.v2"


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _name_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[\s·・丨|_\-—（）()【】\[\]]+", "", text)


def _reference_sets(
    baseline: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}

    package = baseline.get("baseline_package") or {}
    references = list(package.get("room_type_transaction_references") or [])

    for room_id, raw_room in (baseline.get("room_types") or {}).items():
        room = raw_room if isinstance(raw_room, Mapping) else {}
        price = room.get("price_baseline") or {}
        if not any(_n(price.get(key)) is not None for key in ("p20", "median", "p80")):
            continue
        references.append(
            {
                "room_type_id": str(room_id),
                "room_type_name": room.get("room_type_name") or room_id,
                "p20": _n(price.get("p20")),
                "median": _n(price.get("median")),
                "p80": _n(price.get("p80")),
                "sample_count": int(price.get("sample_count") or 0),
                "source_row_count": int(price.get("source_row_count") or 0),
                "weighted_room_nights": _n(price.get("weighted_room_nights")),
                "reference_type": "pms_room_type_actual_transaction",
            }
        )

    for source in references:
        if not isinstance(source, Mapping):
            continue
        reference = dict(source)
        room_id = str(reference.get("room_type_id") or "").strip()
        room_name = str(reference.get("room_type_name") or "").strip()
        if not any(
            _n(reference.get(key)) is not None for key in ("p20", "median", "p80")
        ):
            continue
        if room_id:
            previous = by_id.get(room_id) or {}
            by_id[room_id] = {**previous, **reference}
        key = _name_key(room_name)
        if key:
            previous = by_name.get(key) or {}
            by_name[key] = {**previous, **reference}
    return by_id, by_name


def _reference_for_product(
    product: Mapping[str, Any],
    by_id: Mapping[str, Mapping[str, Any]],
    by_name: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    for key in (
        "room_type_id",
        "canonical_room_type_id",
        "pms_room_type_id",
    ):
        room_id = str(product.get(key) or "").strip()
        if room_id and room_id in by_id:
            return dict(by_id[room_id])
    for key in ("room_type_name", "canonical_room_type_name"):
        name = _name_key(product.get(key))
        if name and name in by_name:
            return dict(by_name[name])
    return None


def compare_product_net_price(
    product: Mapping[str, Any],
    reference: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = dict(product)
    result.update(
        {
            "comparison_allowed": False,
            "action_eligible": False,
            "price_status": "unavailable",
            "comparison_basis": (
                "estimated_hotel_net_vs_room_type_actual_transaction"
            ),
        }
    )
    if str(result.get("product_type") or "") != "普通全天房":
        result["comparison_reason"] = "non_full_day_product_reference_only"
        return result

    estimate = _n(result.get("estimated_activity_net_price"))
    ref = dict(reference or {})
    p20 = _n(ref.get("p20"))
    median = _n(ref.get("median"))
    p80 = _n(ref.get("p80"))
    sample_count = int(ref.get("sample_count") or 0)
    source_row_count = int(ref.get("source_row_count") or 0)
    reference_ready = any(value is not None for value in (p20, median, p80))

    result.update(
        {
            "baseline_p20": p20,
            "baseline_median": median,
            "baseline_p80": p80,
            "baseline_sample_count": sample_count,
            "baseline_source_row_count": source_row_count,
            "baseline_weighted_room_nights": _n(
                ref.get("weighted_room_nights")
            ),
            "reference_room_type_id": ref.get("room_type_id"),
            "reference_room_type_name": ref.get("room_type_name"),
            "history_status": (
                "room_type_transaction_available"
                if reference_ready
                else "unavailable"
            ),
            "reference_readiness": (
                "transaction_percentiles_present"
                if reference_ready
                else "unavailable"
            ),
        }
    )

    if estimate is None:
        result["comparison_reason"] = "commission_or_net_price_unavailable"
        return result
    if not reference_ready:
        result["comparison_reason"] = "room_type_transaction_reference_unavailable"
        return result

    status = "normal"
    if p80 is not None and estimate > p80:
        status = "high"
    elif p20 is not None and estimate < p20:
        status = "low"
    elif p20 is None or p80 is None:
        if median in (None, 0):
            result["comparison_reason"] = (
                "room_type_transaction_reference_unavailable"
            )
            return result
        ratio = estimate / float(median)
        status = (
            "high" if ratio >= 1.08 else "low" if ratio <= 0.95 else "normal"
        )
        result["reference_ratio_vs_pms_transaction"] = ratio

    result.update(
        {
            "comparison_allowed": True,
            "price_status": status,
            "price_cause_candidate": status == "high",
            "comparison_reason": (
                "estimated_net_vs_room_type_transaction_range"
            ),
            "comparison_note": (
                "房型历史成交分位数存在即可比较；样本数字段仅作说明，不再作为重复门禁"
            ),
        }
    )
    return result


def enrich_dynamic_price_comparison(
    dynamic: Mapping[str, Any],
    baseline: Mapping[str, Any],
) -> dict[str, Any]:
    from runtime import s16_dynamic_diagnosis as diagnosis

    result = dict(dynamic)
    by_id, by_name = _reference_sets(baseline)
    products: list[dict[str, Any]] = []
    for raw_product in result.get("product_prices") or []:
        if not isinstance(raw_product, Mapping):
            continue
        product = dict(raw_product)
        reference = _reference_for_product(product, by_id, by_name)
        products.append(compare_product_net_price(product, reference))

    result["product_prices"] = products
    result["price_comparison_version"] = VERSION
    result["price_comparison_rule"] = (
        "raw_price_then_commission_then_compound_activities_"
        "vs_room_type_transaction_p20_median_p80"
    )

    limitations = [
        str(item)
        for item in result.get("data_limitations") or []
        if "同一商品" not in str(item)
        and "可比历史价格" not in str(item)
        and "基准样本数未传递" not in str(item)
    ]
    if any(
        product.get("product_type") == "普通全天房"
        and not product.get("comparison_allowed")
        for product in products
    ):
        limitations.append(
            "部分普通全天房仍缺少佣金、活动后预计酒店到手价或可映射的房型成交分位数，未作价格定性。"
        )
    if products:
        limitations.append(
            "价格比较不含用户券；价格高低仅作为原因证据，不能单独触发调价。"
        )
    result["data_limitations"] = list(dict.fromkeys(limitations))

    if products:
        issues, actions = diagnosis._diagnose(
            sales=result.get("sales") or {},
            market=result.get("market") or {},
            share=result.get("market_share") or {},
            browse=result.get("browse") or {},
            first=result.get("first_conversion") or {},
            second=result.get("second_conversion") or {},
            products=products,
            ad_context=result.get("promotion_state") or {},
            structure=result.get("room_structure") or {},
        )
        issues.sort(
            key=lambda item: (
                -int(item.get("priority") or 0),
                str(item.get("code") or ""),
            )
        )
        result["issues"] = issues
        result["primary_issue"] = issues[0] if issues else None
        result["secondary_issues"] = issues[1:3]
        result["action_candidates"] = actions[:1]
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s16_room_net_price_comparison_patch as target
    from runtime import s16_skill_delivery_patch as delivery

    target.VERSION = VERSION
    target.compare_product_net_price = compare_product_net_price
    target.enrich_dynamic_price_comparison = enrich_dynamic_price_comparison

    previous_contract = delivery.build_s16_response_contract
    if not getattr(previous_contract, "_S16_PRICE_REFERENCE_READINESS_V2", False):
        def build_s16_response_contract(
            result: Mapping[str, Any],
        ) -> dict[str, Any]:
            contract = dict(previous_contract(result))
            preserve = list(contract.get("must_preserve") or [])
            preserve.append(
                "普通全天房已取得活动后预计酒店到手价且对应房型P20、中位或P80存在时，必须输出价格比较结论"
            )
            forbidden = list(contract.get("forbidden") or [])
            forbidden.extend(
                [
                    "房型P20、中位、P80已经存在时，仅因sample_count字段为0或缺失而拒绝价格比较",
                    "把基准样本数字段未传递描述为仍待技术修复",
                ]
            )
            contract.update(
                {
                    "must_preserve": list(dict.fromkeys(preserve)),
                    "forbidden": list(dict.fromkeys(forbidden)),
                    "price_comparison_contract_version": VERSION,
                }
            )
            return contract

        build_s16_response_contract._S16_PRICE_REFERENCE_READINESS_V2 = True  # type: ignore[attr-defined]
        delivery.build_s16_response_contract = build_s16_response_contract
