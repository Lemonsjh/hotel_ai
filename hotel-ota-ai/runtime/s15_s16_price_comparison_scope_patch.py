from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Sequence

_INSTALLED = False
VERSION = "s15-s16-price-comparison-scope.v1"
BASELINE_PACKAGE_VERSION = "s15-baseline-package.v3"
MIN_SELECTED_PRICE_DAYS = 3
MIN_SELECTED_ROOM_NIGHTS = 3.0
DATE_FACTOR_MIN = 0.90
DATE_FACTOR_MAX = 1.20
P80_TOLERANCE_RATIO = 1.08
P80_TOLERANCE_AMOUNT = 10.0


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


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _hotel_weighted_price(
    baselines: Mapping[str, Mapping[str, Any]],
) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for baseline in baselines.values():
        average = _n(baseline.get("weighted_avg"))
        nights = _n(baseline.get("weighted_room_nights"))
        if average is None or nights in (None, 0):
            continue
        numerator += average * nights
        denominator += nights
    return numerator / denominator if denominator > 0 else None


def _selected_date_counts(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    dates: dict[str, set[str]] = {}
    for row in rows:
        room_id = str(row.get("room_type_id") or "").strip()
        business_date = _date(row.get("business_date"))
        if room_id and business_date:
            dates.setdefault(room_id, set()).add(business_date)
    return {room_id: len(values) for room_id, values in dates.items()}


def _adjust_baseline(
    baseline: Mapping[str, Any],
    factor: float,
) -> dict[str, Any]:
    result = dict(baseline)
    for key in ("weighted_avg", "p20", "median", "p80", "min", "max"):
        value = _n(result.get(key))
        if value is not None:
            result[key] = value * factor
    return result


def choose_room_price_baselines(
    *,
    full_baselines: Mapping[str, Mapping[str, Any]],
    selected_baselines: Mapping[str, Mapping[str, Any]],
    selected_date_counts: Mapping[str, int],
) -> dict[str, dict[str, Any]]:
    selected_hotel_price = _hotel_weighted_price(selected_baselines)
    full_hotel_price = _hotel_weighted_price(full_baselines)
    raw_factor = (
        selected_hotel_price / full_hotel_price
        if selected_hotel_price is not None
        and full_hotel_price not in (None, 0)
        else 1.0
    )
    date_factor = _clamp(raw_factor, DATE_FACTOR_MIN, DATE_FACTOR_MAX)

    room_ids = set(map(str, full_baselines.keys())) | set(
        map(str, selected_baselines.keys())
    )
    result: dict[str, dict[str, Any]] = {}
    for room_id in sorted(room_ids):
        selected = dict(selected_baselines.get(room_id) or {})
        full = dict(full_baselines.get(room_id) or {})
        selected_days = int(selected_date_counts.get(room_id) or 0)
        selected_nights = _n(selected.get("weighted_room_nights")) or 0.0
        selected_ready = (
            selected_days >= MIN_SELECTED_PRICE_DAYS
            and selected_nights >= MIN_SELECTED_ROOM_NIGHTS
            and any(
                _n(selected.get(key)) is not None
                for key in ("p20", "median", "p80")
            )
        )
        if selected_ready:
            chosen = selected
            chosen.update(
                {
                    "reference_basis": "selected_similar_dates",
                    "selected_price_date_count": selected_days,
                    "date_adjustment_factor": 1.0,
                    "date_adjustment_applied": False,
                    "full_history_source_row_count": int(
                        full.get("source_row_count") or 0
                    ),
                }
            )
        elif full:
            chosen = _adjust_baseline(full, date_factor)
            chosen.update(
                {
                    "reference_basis": "full_history_with_date_adr_fallback",
                    "selected_price_date_count": selected_days,
                    "selected_price_room_nights": selected_nights,
                    "date_adjustment_factor": date_factor,
                    "date_adjustment_raw_factor": raw_factor,
                    "date_adjustment_applied": abs(date_factor - 1.0) > 1e-9,
                    "full_history_source_row_count": int(
                        full.get("source_row_count") or 0
                    ),
                }
            )
        elif selected:
            chosen = selected
            chosen.update(
                {
                    "reference_basis": "selected_similar_dates_low_sample",
                    "selected_price_date_count": selected_days,
                    "date_adjustment_factor": 1.0,
                    "date_adjustment_applied": False,
                }
            )
        else:
            chosen = {
                "status": "unavailable",
                "reference_basis": "unavailable",
            }
        chosen["sample_count"] = int(
            chosen.get("sample_count")
            or chosen.get("source_row_count")
            or selected_days
            or 0
        )
        result[room_id] = chosen
    return result


def _update_reference(
    source: Mapping[str, Any],
    price: Mapping[str, Any],
) -> dict[str, Any]:
    reference = dict(source)
    reference.update(
        {
            "p20": _n(price.get("p20")),
            "median": _n(price.get("median")),
            "p80": _n(price.get("p80")),
            "sample_count": int(price.get("sample_count") or 0),
            "source_row_count": int(price.get("source_row_count") or 0),
            "weighted_room_nights": _n(price.get("weighted_room_nights")),
            "reference_basis": price.get("reference_basis"),
            "selected_price_date_count": int(
                price.get("selected_price_date_count") or 0
            ),
            "date_adjustment_factor": _n(
                price.get("date_adjustment_factor")
            ),
            "date_adjustment_applied": bool(
                price.get("date_adjustment_applied")
            ),
            "comparison_ready": any(
                _n(price.get(key)) is not None
                for key in ("p20", "median", "p80")
            ),
        }
    )
    return reference


def apply_selected_date_price_baseline(
    payload: Mapping[str, Any],
    repository: Any,
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    from runtime.sales_progress.core import stable_hash
    from runtime.sales_progress.metrics import build_price_baselines

    del target_date  # The target day is represented by the selected-date set.
    result = dict(payload)
    if result.get("status") != "ok":
        return result
    selected_dates = {
        _date(value)
        for value in result.get("selected_dates") or []
        if _date(value)
    }
    rooms = {
        str(room_id): dict(room if isinstance(room, Mapping) else {})
        for room_id, room in (result.get("room_types") or {}).items()
    }
    full_baselines = {
        room_id: dict(room.get("price_baseline") or {})
        for room_id, room in rooms.items()
        if isinstance(room.get("price_baseline"), Mapping)
    }
    selected_rows: list[dict[str, Any]] = []
    if selected_dates:
        try:
            selected_rows = [
                dict(row)
                for row in repository.room_revenue(
                    hotel_id,
                    min(selected_dates),
                    max(selected_dates),
                    as_of_datetime,
                )
                if _date(row.get("business_date")) in selected_dates
            ]
        except Exception:
            selected_rows = []
    selected_baselines = build_price_baselines(selected_rows)
    chosen = choose_room_price_baselines(
        full_baselines=full_baselines,
        selected_baselines=selected_baselines,
        selected_date_counts=_selected_date_counts(selected_rows),
    )
    for room_id, room in rooms.items():
        room["price_baseline"] = chosen.get(
            room_id,
            {
                "status": "unavailable",
                "reference_basis": "unavailable",
            },
        )
    result["room_types"] = rooms

    package = dict(result.get("baseline_package") or {})
    references: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in package.get("room_type_transaction_references") or []:
        reference = dict(source)
        room_id = str(reference.get("room_type_id") or "").strip()
        if room_id:
            seen.add(room_id)
            references.append(
                _update_reference(reference, chosen.get(room_id) or {})
            )
    for room_id, price in chosen.items():
        if room_id in seen:
            continue
        room = rooms.get(room_id) or {}
        references.append(
            _update_reference(
                {
                    "room_type_id": room_id,
                    "room_type_name": room.get("room_type_name") or room_id,
                    "reference_type": "pms_room_type_actual_transaction",
                },
                price,
            )
        )
    package.update(
        {
            "room_type_transaction_references": references,
            "version": BASELINE_PACKAGE_VERSION,
            "price_reference_policy_version": VERSION,
            "price_reference_selected_dates_first": True,
            "price_reference_channel_factor_applied": False,
        }
    )
    result["baseline_package"] = package
    result["baseline_package_version"] = BASELINE_PACKAGE_VERSION
    result["price_reference_policy_version"] = VERSION
    result["baseline_revision"] = stable_hash(
        {
            key: value
            for key, value in result.items()
            if key != "baseline_revision"
        }
    )
    return result


def baseline_builder_wrapper(
    previous: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = previous(*args, **kwargs)
        repository = args[0] if args else kwargs.get("repository")
        hotel_id = str(
            kwargs.get("hotel_id") or result.get("hotel_id") or ""
        )
        target_date = str(
            kwargs.get("target_date") or result.get("target_date") or ""
        )[:10]
        as_of_datetime = str(
            kwargs.get("as_of_datetime")
            or result.get("as_of_datetime")
            or ""
        )
        if (
            repository is None
            or not hotel_id
            or not target_date
            or not as_of_datetime
        ):
            return result
        return apply_selected_date_price_baseline(
            result,
            repository,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of_datetime,
        )

    build._S15_S16_PRICE_SCOPE_V1 = True  # type: ignore[attr-defined]
    return build


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
        result["comparison_reason"] = "non_full_day_product_excluded"
        return result

    from runtime.s5_product_net_revenue_patch import MEMBER_EXPECTED_FACTOR

    estimate = _n(result.get("estimated_activity_net_price"))
    if estimate is not None:
        estimate *= float(MEMBER_EXPECTED_FACTOR)
        result["estimated_activity_net_price"] = estimate
    ref = dict(reference or {})
    p20 = _n(ref.get("p20"))
    median = _n(ref.get("median"))
    p80 = _n(ref.get("p80"))
    result.update(
        {
            "baseline_p20": p20,
            "baseline_median": median,
            "baseline_p80": p80,
            "baseline_sample_count": int(ref.get("sample_count") or 0),
            "baseline_source_row_count": int(
                ref.get("source_row_count") or 0
            ),
            "baseline_weighted_room_nights": _n(
                ref.get("weighted_room_nights")
            ),
            "reference_room_type_id": ref.get("room_type_id"),
            "reference_room_type_name": ref.get("room_type_name"),
            "reference_basis": ref.get("reference_basis"),
            "selected_price_date_count": int(
                ref.get("selected_price_date_count") or 0
            ),
            "date_adjustment_factor": _n(
                ref.get("date_adjustment_factor")
            ),
            "date_adjustment_applied": bool(
                ref.get("date_adjustment_applied")
            ),
        }
    )
    if estimate is None:
        result["comparison_reason"] = "commission_or_net_price_unavailable"
        return result
    if all(value is None for value in (p20, median, p80)):
        result["comparison_reason"] = (
            "room_type_transaction_reference_unavailable"
        )
        return result

    status = "normal"
    if p80 is not None:
        upper = max(
            p80 * P80_TOLERANCE_RATIO,
            p80 + P80_TOLERANCE_AMOUNT,
        )
        result["baseline_upper_tolerance"] = upper
        result["price_gap_vs_p80"] = estimate - p80
        result["price_ratio_vs_p80"] = estimate / p80 if p80 else None
        if estimate > upper:
            status = "high"
        elif estimate > p80:
            status = "near_upper"
        elif p20 is not None and estimate < p20:
            status = "low"
    elif median not in (None, 0):
        ratio = estimate / float(median)
        result["reference_ratio_vs_pms_transaction"] = ratio
        status = "high" if ratio > P80_TOLERANCE_RATIO else "normal"
    elif p20 is not None and estimate < p20:
        status = "low"

    result.update(
        {
            "comparison_allowed": True,
            "price_status": status,
            "price_cause_candidate": status == "high",
            "comparison_reason": (
                "estimated_net_vs_tolerant_room_transaction_range"
            ),
            "comparison_note": (
                "只比较AUTO映射普通全天房；P80上方使用8%或10元容差；"
                "不使用渠道修正系数；活动仍按全部匹配结果连乘，随后统一乘会员预期系数0.85"
            ),
        }
    )
    return result


def _reference_basis_text(product: Mapping[str, Any]) -> str:
    basis = str(product.get("reference_basis") or "")
    days = int(product.get("selected_price_date_count") or 0)
    factor = _n(product.get("date_adjustment_factor"))
    if basis == "selected_similar_dates":
        return f"同类日期{days}天"
    if basis == "full_history_with_date_adr_fallback":
        return (
            f"完整历史按日期结构系数{factor:.2f}修正"
            if factor is not None
            else "完整历史日期结构回退"
        )
    if basis == "selected_similar_dates_low_sample":
        return f"同类日期低样本{days}天"
    return "房型历史成交"


def render_price_comparison_block(report: Mapping[str, Any]) -> str:
    products = [
        dict(product)
        for product in (
            (report.get("dynamic_diagnosis") or {}).get(
                "product_prices"
            )
            or []
        )
        if isinstance(product, Mapping)
        and str(product.get("product_type") or "") == "普通全天房"
    ]
    if not products:
        return "- 价格比较：当前没有可用的美团普通全天房商品。"

    products.sort(
        key=lambda item: (
            str(item.get("ota_product_name") or ""),
            str(item.get("ota_product_id") or ""),
        )
    )
    labels = {
        "high": "高于历史参考区间",
        "near_upper": "接近历史上沿",
        "normal": "处于历史参考区间",
        "low": "低于历史参考区间",
        "unavailable": "暂不可比较",
    }
    lines = [
        "- 价格比较：仅列出当前美团 AUTO 映射的普通全天房实际商品；钟点房和超级团购已排除。",
        "- 口径：按商品底价、佣金、全部匹配活动连乘及预期会员折扣系数 0.85 估算酒店到手收入；以下均为预估到手价，不是实际结算金额；不使用渠道净价修正系数。",
    ]
    for product in products:
        name = (
            product.get("ota_product_name")
            or product.get("ota_product_id")
            or "未命名商品"
        )
        mapped_room = (
            product.get("reference_room_type_name")
            or product.get("room_type_name")
            or product.get("room_type_id")
            or "未命名房型"
        )
        prefix = (
            f"  - 商品《{name}》（对应房型：{mapped_room}）：预估到手价 "
            f"{_money(product.get('estimated_activity_net_price'))}"
        )
        if product.get("comparison_allowed"):
            status = labels.get(
                str(product.get("price_status") or ""),
                "暂不可比较",
            )
            lines.append(
                prefix
                + "；"
                + _reference_basis_text(product)
                + " P20/中位/P80="
                + f"{_money(product.get('baseline_p20'))}/"
                + f"{_money(product.get('baseline_median'))}/"
                + f"{_money(product.get('baseline_p80'))}；{status}。"
            )
        else:
            lines.append(
                prefix + "；缺少预估到手价或房型成交参考，暂不可比较。"
            )
    lines.append(
        "- 注：预估到手价已包含预期会员折扣系数 0.85，不含用户券，也不等同于最终实际结算金额；"
        "接近历史上沿不算价格偏高；价格高低不能单独触发调价，仍需结合销售进度和二转核验。"
    )
    return "\n".join(lines)


def replace_s16_price_block(text: str, report: Mapping[str, Any]) -> str:
    starts = [text.find("- 价格："), text.find("- 价格比较：")]
    starts = [value for value in starts if value >= 0]
    if not starts:
        return text
    start = min(starts)
    end = text.find("\n\n五、建议动作", start)
    block = render_price_comparison_block(report)
    return text[:start] + block + (text[end:] if end >= 0 else "")


def _s15_price_lines(payload: Mapping[str, Any]) -> list[str]:
    package = payload.get("baseline_package") or {}
    references = package.get("room_type_transaction_references") or []
    lines: list[str] = []
    for item in references:
        basis = str(item.get("reference_basis") or "")
        days = int(item.get("selected_price_date_count") or 0)
        factor = _n(item.get("date_adjustment_factor"))
        if basis == "selected_similar_dates":
            source = f"同类日期{days}天"
        elif basis == "full_history_with_date_adr_fallback":
            source = (
                f"同类日期房型样本不足，完整历史按日期结构系数{factor:.2f}修正"
                if factor is not None
                else "同类日期房型样本不足，使用完整历史回退"
            )
        else:
            source = f"历史样本{days}天" if days else "历史样本"
        lines.append(
            f"- {item.get('room_type_name') or item.get('room_type_id')}房型实际成交参考："
            f"P20 {_money(item.get('p20'))}，中位 {_money(item.get('median'))}，"
            f"P80 {_money(item.get('p80'))}；口径：{source}。"
        )
    if not lines:
        lines.append("- 当前缺少房型实际成交历史参考。")
    lines.extend(
        [
            "- 计算口径：PMS 房型日成交价，按成交间夜加权计算 P20、中位和 P80。",
            "- S15 只提供房型历史成交参考，不判断当前美团商品高低；S16 再按实际商品逐一比较。",
        ]
    )
    return lines


def replace_s15_price_block(text: str, payload: Mapping[str, Any]) -> str:
    pattern = re.compile(r"\n([四五六七八九十]+)、价格参考\n")
    match = pattern.search(text)
    if not match:
        return text
    start = match.end()
    next_heading = re.search(
        r"\n[四五六七八九十]+、样本与边界\n",
        text[start:],
    )
    if not next_heading:
        return text
    end = start + next_heading.start()
    return text[:start] + "\n".join(_s15_price_lines(payload)) + text[end:]


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import runtime.sales_progress as sales_progress
    from runtime import (
        s15_s16_complete_output_patch as complete,
        s15_s16_responsibility_patch as responsibility,
        s16_price_reference_readiness_patch as readiness,
        s16_room_net_price_comparison_patch as comparison,
        s16_skill_delivery_patch as delivery,
    )
    from runtime.decisions import baseline as baseline_decision
    from runtime.sales_progress import (
        baseline_service,
        deviation_service,
        presentation,
        service,
    )

    responsibility.BASELINE_PACKAGE_VERSION = BASELINE_PACKAGE_VERSION
    previous_build = baseline_service.build_baseline
    if not getattr(previous_build, "_S15_S16_PRICE_SCOPE_V1", False):
        wrapped_build = baseline_builder_wrapper(previous_build)
        baseline_service.build_baseline = wrapped_build
        service._build_baseline = wrapped_build
        deviation_service.build_baseline = wrapped_build
        baseline_decision.build_baseline = wrapped_build
        sales_progress.build_baseline = wrapped_build

    readiness.compare_product_net_price = compare_product_net_price
    comparison.compare_product_net_price = compare_product_net_price

    previous_s15 = responsibility._baseline_message
    if not getattr(previous_s15, "_S15_PRICE_SCOPE_OUTPUT_V1", False):

        def s15_message(payload: Mapping[str, Any]) -> str:
            return replace_s15_price_block(previous_s15(payload), payload)

        s15_message._S15_PRICE_SCOPE_OUTPUT_V1 = True  # type: ignore[attr-defined]
        responsibility._baseline_message = s15_message
        presentation.build_s15_user_message = s15_message
        complete.s15_message = s15_message

    previous_s16 = responsibility._dynamic_message
    if not getattr(previous_s16, "_S16_PRICE_SCOPE_OUTPUT_V1", False):

        def s16_message(report: Mapping[str, Any]) -> str:
            return replace_s16_price_block(previous_s16(report), report)

        s16_message._S16_PRICE_SCOPE_OUTPUT_V1 = True  # type: ignore[attr-defined]
        responsibility._dynamic_message = s16_message
        presentation.build_s16_user_message = s16_message
        complete.s16_message = s16_message

    previous_contract = delivery.build_s16_response_contract
    if not getattr(previous_contract, "_S15_S16_PRICE_SCOPE_V1", False):

        def build_s16_response_contract(
            result: Mapping[str, Any],
        ) -> dict[str, Any]:
            contract = dict(previous_contract(result))
            preserve = list(contract.get("must_preserve") or [])
            preserve.extend(
                [
                    "价格比较逐条展示meituan_ota_goods_price_mapping中的实际ota_product_name",
                    "只比较AUTO映射普通全天房，钟点房和超级团购不进入价格比较列表",
                    "活动继续按全部匹配结果连乘，并在活动后统一乘预期会员折扣系数0.85；不使用渠道净价修正系数",
                    "P80上方8%或10元以内标记为接近历史上沿，不作为价格偏高证据",
                    "价格比较中的到手价必须明确标注为包含预期会员折扣系数的预估到手价，不得表述为实际到账或最终结算金额",
                ]
            )
            forbidden = list(contract.get("forbidden") or [])
            forbidden.extend(
                [
                    "把标准房型名称冒充为美团实际商品名称",
                    "在价格比较列表中混入钟点房或超级团购",
                    "添加渠道净价修正系数或改变现有活动连乘逻辑",
                    "估算到手价仅略高于P80容差时判为价格偏高",
                    "在价格比较用户可见正文展示挂牌价、商品底价、扣佣前价格或扣佣后中间价",
                    "把预估到手价表述为实际到手价、实际到账价或最终结算金额",
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

        build_s16_response_contract._S15_S16_PRICE_SCOPE_V1 = True  # type: ignore[attr-defined]
        delivery.build_s16_response_contract = build_s16_response_contract
