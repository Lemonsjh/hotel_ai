from __future__ import annotations

from typing import Any, Mapping

_INSTALLED = False
VERSION = "s16-room-net-price-comparison.v1"
KNOWLEDGE_FILE = (
    "skills/hotel-ota/s16-progress-deviation/"
    "S16_ROOM_NET_PRICE_COMPARISON_RULES.md"
)
_STATUS_LABELS = {
    "high": "高于房型历史成交区间",
    "normal": "处于房型历史成交区间",
    "low": "低于房型历史成交区间",
    "unavailable": "暂不可比较",
}


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"¥{number:,.0f}"


def _pct(value: Any, digits: int = 1) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.{digits}f}%"


def _room_references(baseline: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    package = baseline.get("baseline_package") or {}
    refs: dict[str, dict[str, Any]] = {}
    for source in package.get("room_type_transaction_references") or []:
        if not isinstance(source, Mapping):
            continue
        room_id = str(source.get("room_type_id") or "").strip()
        if room_id:
            refs[room_id] = dict(source)
    return refs


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
    room_id = str(result.get("room_type_id") or "").strip()
    ref = dict(reference or {})
    p20 = _n(ref.get("p20"))
    median = _n(ref.get("median"))
    p80 = _n(ref.get("p80"))
    sample_count = int(ref.get("sample_count") or 0)
    result.update(
        {
            "baseline_p20": p20,
            "baseline_median": median,
            "baseline_p80": p80,
            "baseline_sample_count": sample_count,
            "history_status": (
                "room_type_transaction_available"
                if sample_count > 0
                else "unavailable"
            ),
        }
    )
    if estimate is None:
        result["comparison_reason"] = "commission_or_net_price_unavailable"
        return result
    if (
        not room_id
        or sample_count <= 0
        or all(value is None for value in (p20, median, p80))
    ):
        result["comparison_reason"] = "room_type_transaction_reference_unavailable"
        return result

    status = "normal"
    if p80 is not None and estimate > p80:
        status = "high"
    elif p20 is not None and estimate < p20:
        status = "low"
    elif p20 is None or p80 is None:
        if median in (None, 0):
            result["comparison_reason"] = "room_type_transaction_reference_unavailable"
            return result
        ratio = estimate / float(median)
        status = "high" if ratio >= 1.08 else "low" if ratio <= 0.95 else "normal"
        result["reference_ratio_vs_pms_transaction"] = ratio

    result.update(
        {
            "comparison_allowed": True,
            "price_status": status,
            "price_cause_candidate": status == "high",
            "comparison_reason": "estimated_net_vs_room_type_transaction_range",
            "comparison_note": (
                "房型级预计酒店到手价对历史实际成交价，不要求同一商品历史"
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
    refs = _room_references(baseline)
    products = [
        compare_product_net_price(
            product,
            refs.get(str(product.get("room_type_id") or "")),
        )
        for product in result.get("product_prices") or []
        if isinstance(product, Mapping)
    ]
    result["product_prices"] = products
    result["price_comparison_version"] = VERSION
    result["price_comparison_rule"] = (
        "raw_price_then_commission_then_compound_activities_"
        "vs_room_type_transaction_p20_median_p80"
    )

    limitations = [
        str(item)
        for item in result.get("data_limitations") or []
        if "同一商品" not in str(item) and "可比历史价格" not in str(item)
    ]
    if any(
        product.get("product_type") == "普通全天房"
        and not product.get("comparison_allowed")
        for product in products
    ):
        limitations.append(
            "部分普通全天房缺少佣金、活动后预计酒店到手价或房型历史成交基准，未作价格定性。"
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


def render_price_comparison_block(report: Mapping[str, Any]) -> str:
    products = list(
        ((report.get("dynamic_diagnosis") or {}).get("product_prices") or [])
    )
    if not products:
        return "- 价格：当前没有可用的 OTA 商品价格事实。"

    lines = [
        "- 价格比较：普通全天房按“商品底价 → 扣除佣金 → 活动连续叠加”估算酒店到手价，再与对应房型历史实际成交价比较。"
    ]
    for product in products:
        name = (
            product.get("ota_product_name")
            or product.get("ota_product_id")
            or "未命名商品"
        )
        product_type = product.get("product_type") or "美团商品"
        prefix = (
            f"  - {product_type}｜{name}：挂牌 "
            f"{_money(product.get('raw_price') or product.get('current_price'))} → "
            f"扣佣后 {_money(product.get('commission_net_base_price'))} → "
            f"活动后预计酒店到手 {_money(product.get('estimated_activity_net_price'))}"
            f"（佣金 {_pct(product.get('commission_rate'))}，叠加 "
            f"{int(product.get('matched_activity_count') or 0)} 个活动）"
        )
        if product.get("comparison_allowed"):
            status = _STATUS_LABELS.get(
                str(product.get("price_status") or "unavailable"),
                "暂不可比较",
            )
            lines.append(
                prefix
                + "；房型历史成交 P20/中位/P80="
                + f"{_money(product.get('baseline_p20'))}/"
                + f"{_money(product.get('baseline_median'))}/"
                + f"{_money(product.get('baseline_p80'))}；{status}。"
            )
        elif product_type != "普通全天房":
            lines.append(prefix + "；非普通全天房，仅展示，不与全天房历史成交比较。")
        else:
            lines.append(prefix + "；缺少完整净价或房型成交基准，暂不可比较。")
    lines.append(
        "- 注：预计酒店到手价不含用户券；价格高低不能单独触发调价，仍需结合销售进度和二转核验。"
    )
    return "\n".join(lines)


def replace_price_block(text: str, report: Mapping[str, Any]) -> str:
    positions = [text.find("- 价格："), text.find("- 价格比较：")]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return text
    start = min(positions)
    end = text.find("\n\n五、建议动作", start)
    block = render_price_comparison_block(report)
    return text[:start] + block + (text[end:] if end >= 0 else "")


def _patch_dynamic_builder() -> None:
    from runtime import s15_s16_responsibility_patch as responsibility
    from runtime import s16_dynamic_diagnosis as diagnosis

    previous = diagnosis.build_s16_dynamic_diagnosis
    if getattr(previous, "_NET_PRICE_ROOM_REFERENCE_V1", False):
        return

    def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        dynamic = previous(*args, **kwargs)
        return enrich_dynamic_price_comparison(
            dynamic,
            kwargs.get("baseline") or {},
        )

    build._NET_PRICE_ROOM_REFERENCE_V1 = True  # type: ignore[attr-defined]
    responsibility.build_s16_dynamic_diagnosis = build
    diagnosis.build_s16_dynamic_diagnosis = build


def _patch_presentation() -> None:
    from runtime import s15_s16_complete_output_patch as complete
    from runtime import s15_s16_responsibility_patch as responsibility
    from runtime.sales_progress import presentation

    previous = responsibility._dynamic_message
    if getattr(previous, "_NET_PRICE_ROOM_REFERENCE_OUTPUT_V1", False):
        return

    def s16_message(report: Mapping[str, Any]) -> str:
        return replace_price_block(previous(report), report)

    s16_message._NET_PRICE_ROOM_REFERENCE_OUTPUT_V1 = True  # type: ignore[attr-defined]
    responsibility._dynamic_message = s16_message
    presentation.build_s16_user_message = s16_message
    complete.s16_message = s16_message


def _patch_delivery_contract() -> None:
    from runtime import s15_s16_responsibility_patch as responsibility
    from runtime import s16_skill_delivery_patch as delivery

    if KNOWLEDGE_FILE not in delivery.KNOWLEDGE_FILES:
        delivery.KNOWLEDGE_FILES.insert(0, KNOWLEDGE_FILE)
    responsibility._ISSUE_LABELS["SECOND_CONVERSION_WEAK_PRICE_HIGH"] = (
        "进入详情页后的成交偏弱，且普通全天房预计酒店到手价高于对应房型历史成交区间"
    )

    previous = delivery.build_s16_response_contract
    if getattr(previous, "_NET_PRICE_ROOM_REFERENCE_CONTRACT_V1", False):
        return

    def build_s16_response_contract(result: Mapping[str, Any]) -> dict[str, Any]:
        contract = dict(previous(result))
        preserve = [
            item
            for item in contract.get("must_preserve") or []
            if "同一商品可比历史" not in str(item)
        ]
        preserve.extend(
            [
                "普通全天房按商品底价、佣金和全部有效活动连续相乘后的预计酒店到手价",
                "预计酒店到手价与对应房型PMS历史成交P20、中位、P80的比较结论",
                "超级团购和钟点房只展示，不与普通全天房历史成交区间比较",
                "价格高低不能单独触发调价，仍须满足销售偏慢和二转偏弱等门禁",
            ]
        )
        forbidden = [
            item
            for item in contract.get("forbidden") or []
            if "没有同一OTA商品历史" not in str(item)
        ]
        forbidden.extend(
            [
                "因缺少同一商品连续历史而拒绝比较已算出的普通全天房预计酒店到手价",
                "把超级团购或钟点房与普通全天房PMS历史成交区间直接比较",
                "把预计酒店到手价称为最终结算价或包含用户券的用户实付价",
            ]
        )
        contract.update(
            {
                "knowledge_file": KNOWLEDGE_FILE,
                "knowledge_files": list(delivery.KNOWLEDGE_FILES),
                "knowledge_precedence": list(delivery.KNOWLEDGE_FILES),
                "must_preserve": list(dict.fromkeys(preserve)),
                "forbidden": list(dict.fromkeys(forbidden)),
                "price_comparison_contract_version": VERSION,
            }
        )
        return contract

    build_s16_response_contract._NET_PRICE_ROOM_REFERENCE_CONTRACT_V1 = True  # type: ignore[attr-defined]
    delivery.build_s16_response_contract = build_s16_response_contract


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _patch_dynamic_builder()
    _patch_presentation()
    _patch_delivery_contract()
