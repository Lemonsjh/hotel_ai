from __future__ import annotations

import datetime as dt
import json
import os
from contextlib import closing
from typing import Any, Mapping

from runtime.s16_dynamic_diagnosis import build_s16_dynamic_diagnosis

_INSTALLED = False
VERSION = "s15-s16-final-responsibility.v1"
BASELINE_PACKAGE_VERSION = "s15-baseline-package.v1"
CACHE_TTL_SECONDS = 86400

_BASELINE_PHRASES = (
    "查看基准线",
    "销售基准线",
    "完整基准数据包",
    "基准数据包",
    "历史正常值",
    "历史基准",
    "基准成熟度",
    "样本数量",
    "历史样本",
    "历史p20",
    "历史 p20",
    "历史中位",
    "历史p80",
    "历史 p80",
    "小时目标",
    "最终销售目标",
)
_DYNAMIC_PHRASES = (
    "今天经营怎么样",
    "今天经营好不好",
    "今日经营怎么样",
    "今天主要问题",
    "今天有什么问题",
    "为什么销售落后",
    "为什么销售慢",
    "为什么卖得慢",
    "销售落后原因",
    "进度落后原因",
    "大盘冷不冷",
    "大盘是否冷",
    "有没有丢份额",
    "是否丢份额",
    "市场份额是否下降",
    "浏览是否不足",
    "浏览哪里有问题",
    "一转是否弱",
    "二转是否弱",
    "转化哪里有问题",
    "今天是否需要调价",
    "今天要不要调价",
    "今天是否需要开推广",
    "今天要不要开推广",
    "今天是否需要关推广",
    "今天要不要关推广",
    "哪些房型需要处理",
    "哪些房型卖得慢",
)
_EXECUTION_PHRASES = (
    "dry-run",
    "执行预览",
    "调价预览",
    "确认执行",
    "立即执行",
    "同步房价",
    "创建任务",
    "提交审批",
)

_MATURITY_LABELS = {
    "trend_only": "历史很短，仅展示趋势",
    "weak": "样本较少，目前仅供趋势观察",
    "weak_reference": "样本较少，目前仅供趋势观察",
    "temporary": "已有初步参考，暂不作为自动动作依据",
    "stable": "样本较稳定，可用于正常判断",
    "strong": "历史充分，可支持较强判断",
    "unavailable": "暂无足够历史数据",
}
_STATUS_LABELS = {
    "severe_slow": "严重偏慢",
    "significant_slow": "明显偏慢",
    "slow": "偏慢",
    "normal": "正常",
    "fast": "偏快",
    "significant_fast": "明显偏快",
    "cold": "偏冷",
    "hot": "偏热",
    "weak": "偏弱",
    "significant_weak": "明显偏弱",
    "strong": "偏强",
    "sample_insufficient": "样本不足",
    "period_not_comparable": "当前与历史统计周期不同",
    "unavailable": "暂不可判断",
}
_ISSUE_LABELS = {
    "SALES_NORMAL": "当前整体销售进度正常",
    "SALES_FAST": "当前整体销售进度偏快",
    "MARKET_COLD": "主要受市场需求偏冷影响，本店份额暂未明显走弱",
    "MARKET_COLD_WITH_SHARE_LOSS": "市场需求偏冷，同时本店份额也在下降",
    "SHARE_LOSS": "市场仍有订单，但本店获得的订单份额下降",
    "TRAFFIC_WEAK": "当前主要问题是详情页浏览不足",
    "CLICK_CONVERSION_WEAK": "当前主要问题是列表入口吸引力不足",
    "SECOND_CONVERSION_WEAK_PRICE_HIGH": "进入详情页后的成交偏弱，且存在可比商品价格偏高证据",
    "SECOND_CONVERSION_WEAK_NON_PRICE": "进入详情页后的成交偏弱，但暂无可比商品价格偏高证据",
    "ROOM_TYPE_SLOW_ONLY": "存在具体房型结构性偏慢",
    "ROOM_TYPE_MIX_OFFSET": "偏快和偏慢房型相互抵消，全店平均掩盖了结构问题",
    "DATA_INSUFFICIENT": "当前事实不足，暂不能判断当日进度",
    "DATA_NOT_COMPARABLE": "关键数据统计周期或样本暂不可比",
    "SOURCE_CONFLICT": "不同数据来源存在冲突，暂不形成强结论",
}
_ACTION_LABELS = {
    "review_promotion_enable": "核查并考虑开启或恢复推广位",
    "review_promotion_stop": "核查并考虑关闭推广位",
    "optimize_entry_display": "优先优化主图、标题、标签、引流商品和列表入口",
    "review_product_price": "交由 S5 对具体 OTA 商品进行调价候选核验",
    "investigate_detail_conversion": "先排查套餐、取消规则、评价和详情页成交承接",
    "continue_observation": "继续观察，不立即执行价格或推广动作",
}


def _n(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any, digits: int = 1) -> str:
    number = _n(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _pct(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def _pp(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number:+.1f}个百分点"


def _money(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"¥{number:,.0f}"


def _axis_baseline(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "median": _n(
            source.get("baseline_median")
            if source.get("baseline_median") is not None
            else source.get("median")
        ),
        "p20": _n(
            source.get("baseline_p20")
            if source.get("baseline_p20") is not None
            else source.get("p20")
        ),
        "p25": _n(
            source.get("baseline_p25")
            if source.get("baseline_p25") is not None
            else source.get("p25")
        ),
        "p80": _n(
            source.get("baseline_p80")
            if source.get("baseline_p80") is not None
            else source.get("p80")
        ),
        "sample_count": int(source.get("sample_count") or 0),
        "maturity": source.get("baseline_confidence_level")
        or source.get("baseline_tier")
        or source.get("maturity"),
        "grain": source.get("grain") or "daily",
    }


def _build_baseline_package(payload: Mapping[str, Any]) -> dict[str, Any]:
    analysis = payload.get("operating_analysis") or {}
    reference = analysis.get("platform_reference") or {}
    reference_axes = reference.get("baselines") or {}
    market = analysis.get("market") or {}
    share = analysis.get("market_share") or {}
    second = analysis.get("second_conversion") or {}
    rooms = payload.get("room_types") or {}
    room_transaction_references: list[dict[str, Any]] = []
    for room_id, source in sorted(
        rooms.items(),
        key=lambda item: str(item[0]),
    ):
        room = source if isinstance(source, Mapping) else {}
        price = room.get("price_baseline") or {}
        room_transaction_references.append(
            {
                "room_type_id": room_id,
                "room_type_name": room.get("room_type_name") or room_id,
                "p20": _n(price.get("p20")),
                "median": _n(price.get("median")),
                "p80": _n(price.get("p80")),
                "sample_count": int(price.get("sample_count") or 0),
                "reference_type": "pms_room_type_actual_transaction",
                "ota_listing_price_comparison_allowed": False,
            }
        )
    return {
        "status": "ok" if payload.get("status") == "ok" else "partial",
        "version": BASELINE_PACKAGE_VERSION,
        "hotel_final_sales_target": (
            payload.get("hotel") or {}
        ).get("effective_target_room_nights"),
        "room_type_final_sales_targets": {
            str(room_id): {
                "room_type_name": (room or {}).get("room_type_name")
                or room_id,
                "target_room_nights": (room or {}).get(
                    "effective_target_room_nights"
                ),
                "baseline_health": (room or {}).get("baseline_health") or {},
            }
            for room_id, room in rooms.items()
        },
        "hotel_hourly_sales_baseline": (
            payload.get("hotel") or {}
        ).get("hourly_points")
        or [],
        "room_type_hourly_sales_baselines": {
            str(room_id): (room or {}).get("hourly_points") or []
            for room_id, room in rooms.items()
        },
        "market_orders_baseline": {
            "median": _n(market.get("baseline_estimated_market_orders")),
            "sample_count": int(market.get("sample_count") or 0),
            "maturity": market.get("baseline_confidence_level")
            or market.get("baseline_tier"),
            "estimated": True,
        },
        "market_share_baseline": {
            "median": _n(share.get("baseline_estimated_market_share")),
            "sample_count": int(share.get("sample_count") or 0),
            "maturity": share.get("baseline_confidence_level")
            or share.get("baseline_tier"),
            "estimated": True,
        },
        "platform_baselines": {
            "browse": _axis_baseline(
                reference_axes.get("browse_uv")
                or analysis.get("browse")
                or {}
            ),
            "first_conversion": _axis_baseline(
                reference_axes.get("first_conversion")
                or analysis.get("first_conversion")
                or {}
            ),
            "second_conversion": _axis_baseline(
                reference_axes.get("second_conversion")
                or analysis.get("second_conversion")
                or {}
            ),
        },
        "peer_second_conversion_reference": {
            "median": _n(
                (
                    second.get("rolling_30d_peer") or {}
                ).get("peer_second_conversion")
            ),
            "source": "rolling_peer_reference",
        },
        "room_type_transaction_references": room_transaction_references,
        "ota_product_price_baselines": [],
        "ota_product_price_history_status": "unavailable",
        "lead_price_baseline": _axis_baseline(
            reference_axes.get("lead_price_metric")
            or analysis.get("lead_price")
            or {}
        ),
        "selected_dates": payload.get("selected_dates")
        or reference.get("selected_dates")
        or [],
        "selected_sample_days": reference.get("selected_sample_days"),
        "history_day_count": reference.get("history_day_count")
        or reference.get("history_completed_day_count"),
        "sample_maturity": reference.get("baseline_confidence_level"),
        "selected_date_rule": reference.get("selected_tier"),
        "data_gaps": list(payload.get("data_gaps") or []),
        "unavailable_families": list(
            (payload.get("unavailable_baseline_families") or {}).keys()
        ),
        "generated_at": payload.get("as_of_datetime"),
        "target_date": payload.get("target_date")
        or payload.get("business_date"),
        "dynamic_current_facts_included": False,
        "dynamic_diagnosis_included": False,
        "actions_included": False,
    }


def _finalize_baseline(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["baseline_package"] = _build_baseline_package(result)
    result["baseline_package_version"] = BASELINE_PACKAGE_VERSION
    result["responsibility_contract_version"] = VERSION
    result["dynamic_analysis_included"] = False
    result.pop("operating_analysis", None)
    return result


def _valid_cached(payload: Mapping[str, Any] | None) -> bool:
    return bool(
        payload
        and payload.get("status") == "ok"
        and payload.get("baseline_package_version")
        == BASELINE_PACKAGE_VERSION
        and isinstance(payload.get("baseline_package"), Mapping)
    )


def _cached_baseline(
    db_path: str,
    hotel_id: str,
    business_date: str,
    *,
    max_age_seconds: int,
) -> dict[str, Any] | None:
    if max_age_seconds <= 0:
        return None
    from runtime.storage import connect, init_schema

    try:
        with closing(connect(db_path)) as conn:
            init_schema(conn)
            row = conn.execute(
                "SELECT payload_json, created_at FROM baselines "
                "WHERE hotel_id=? AND business_date=? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (hotel_id, business_date),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
        created = dt.datetime.fromisoformat(str(row["created_at"]))
        age = max((dt.datetime.now() - created).total_seconds(), 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if age > max_age_seconds or not _valid_cached(payload):
        return None
    payload["cache_status"] = "hit"
    payload["cache_age_seconds"] = int(age)
    return payload


def _latest_baseline(
    db_path: str,
    hotel_id: str,
    business_date: str,
) -> dict[str, Any] | None:
    return _cached_baseline(
        db_path,
        hotel_id,
        business_date,
        max_age_seconds=CACHE_TTL_SECONDS,
    )


def _maturity_text(value: Any) -> str:
    key = str(value or "").strip().lower()
    return _MATURITY_LABELS.get(
        key,
        "样本成熟度以确定性结果为准",
    )


def _baseline_message(payload: Mapping[str, Any]) -> str:
    if payload.get("status") != "ok":
        return "S15 销售基准线暂不可用：当前缺少建立历史基准所需的数据。"
    package = payload.get("baseline_package") or {}
    lines = [
        f"S15 销售基准线｜{payload.get('target_date') or payload.get('business_date') or '-'}",
        "本结果只展示历史基准、样本和可比性，不判断今天的经营原因，也不生成动作。",
        "",
        "一、最终销售目标",
        f"- 全店历史参考最终销售目标：{_num(package.get('hotel_final_sales_target'))}间。",
    ]
    for room_id, room in (
        package.get("room_type_final_sales_targets") or {}
    ).items():
        lines.append(
            f"- {room.get('room_type_name') or room_id}："
            f"{_num(room.get('target_room_nights'))}间。"
        )
    lines.extend(["", "二、全店小时销售基准"])
    points = package.get("hotel_hourly_sales_baseline") or []
    emitted = 0
    for point in points:
        hour = point.get("hour")
        if hour not in {9, 12, 14, 16, 18, 20, 22}:
            continue
        completion = point.get("target_completion") or {}
        capacity = point.get("capacity") or {}
        lines.append(
            f"- {int(hour):02d}:00：最终目标完成中位 "
            f"{_pct(completion.get('median'))}；容量消化中位 "
            f"{_pct(capacity.get('median'))}；样本 "
            f"{max(int(completion.get('sample_count') or 0), int(capacity.get('sample_count') or 0))}天。"
        )
        emitted += 1
    if emitted == 0:
        lines.append(
            "- 当前关键小时缺少真实历史样本，不使用默认曲线冒充真实基准。"
        )
    lines.extend(["", "三、平台历史基准"])
    market = package.get("market_orders_baseline") or {}
    share = package.get("market_share_baseline") or {}
    axes = package.get("platform_baselines") or {}
    lines.append(
        f"- 估算大盘订单历史中位：{_num(market.get('median'))}单；"
        f"样本 {market.get('sample_count') or 0}天。"
    )
    lines.append(
        f"- 本店估算市场份额历史中位：{_pct(share.get('median'))}；"
        f"样本 {share.get('sample_count') or 0}天。"
    )
    for key, label in (
        ("browse", "浏览"),
        ("first_conversion", "一转"),
        ("second_conversion", "二转"),
    ):
        axis = axes.get(key) or {}
        value = (
            _pct(axis.get("median"))
            if "conversion" in key
            else _num(axis.get("median"))
        )
        lines.append(
            f"- {label}历史中位：{value}；"
            f"样本 {axis.get('sample_count') or 0}天；"
            f"{_maturity_text(axis.get('maturity'))}。"
        )
    lines.extend(["", "四、价格参考"])
    references = package.get("room_type_transaction_references") or []
    if references:
        for item in references:
            lines.append(
                f"- {item.get('room_type_name') or item.get('room_type_id')}"
                f"房型实际成交参考：P20 {_money(item.get('p20'))}，"
                f"中位 {_money(item.get('median'))}，"
                f"P80 {_money(item.get('p80'))}。"
            )
    else:
        lines.append("- 当前缺少房型实际成交历史参考。")
    lines.append(
        "- PMS 房型实际成交价与 OTA 商品挂牌价口径不同，"
        "不直接据此判断 OTA 商品偏高或偏低。"
    )
    lines.append(
        "- 当前暂无经过验证的同一 OTA 商品连续历史价格；"
        "商品价格高低和调价资格不在 S15 中判断。"
    )
    selected = package.get("selected_dates") or []
    lines.extend(
        [
            "",
            "五、样本与边界",
            f"- 历史覆盖 {package.get('history_day_count') or 0}天，"
            f"本次选取 {len(selected)}个同类日期样本。",
            f"- {_maturity_text(package.get('sample_maturity'))}。",
            "- 当前酒店没有匹配到的数据不会进入基准，也不会在普通回复中显示其他酒店或无关渠道的工程状态。",
        ]
    )
    return "\n".join(lines)


def _status_text(value: Any) -> str:
    return _STATUS_LABELS.get(str(value or ""), "暂不可判断")


def _dynamic_message(report: Mapping[str, Any]) -> str:
    dynamic = report.get("dynamic_diagnosis") or {}
    if not dynamic:
        return "S16 进度偏差诊断暂不可用：当前结果缺少动态诊断数据。"
    sales = dynamic.get("sales") or {}
    structure = dynamic.get("room_structure") or {}
    primary = dynamic.get("primary_issue") or {}
    primary_text = _ISSUE_LABELS.get(
        str(primary.get("code") or ""),
        "当前证据未锁定单一主要原因",
    )
    action = next(iter(dynamic.get("action_candidates") or []), None)
    action_text = _ACTION_LABELS.get(
        str((action or {}).get("action_type") or ""),
        "当前不生成动作候选",
    )
    lines = [
        f"S16 进度偏差诊断｜{dynamic.get('target_date') or report.get('target_date') or '-'}",
        "",
        "一、当前结论",
        f"- 全店销售进度：{_status_text(sales.get('status'))}；"
        f"{primary_text}。",
        f"- 当前动作方向：{action_text}。",
        "",
        "二、销售进度",
        f"- 当前承诺已售 {_num(sales.get('committed_sold'))}/"
        f"{_num(sales.get('total_rooms'))}间；当前时点参考应售 "
        f"{_num(sales.get('current_expected_sold'))}间。",
        f"- 进度偏差 {_pp(sales.get('sales_progress_delta_pp'))}，"
        f"检查点相差 {_num(sales.get('checkpoint_room_gap'))}间，"
        f"距最终参考目标 {_num(sales.get('remaining_target_gap'))}间。",
    ]
    age = sales.get("checkpoint_gap_minutes")
    if age is not None:
        lines.append(f"- 当前事实批次距请求约 {int(age)}分钟。")
    lines.extend(["", "三、房型结构"])
    rooms = structure.get("room_type_results") or []
    focus = [
        row for row in rooms if str(row.get("sales_status")) != "normal"
    ]
    for room in focus[:8]:
        lines.append(
            f"- {room.get('room_type_name') or room.get('room_type_id')}："
            f"已售 {_num(room.get('committed_sold'))}/"
            f"{_num(room.get('total_rooms'))}间，当前应售 "
            f"{_num(room.get('current_expected_sold'))}间，相差 "
            f"{_num(room.get('checkpoint_room_gap'))}间，"
            f"{_status_text(room.get('sales_status'))}。"
        )
    if not focus:
        lines.append("- 当前未发现需要单独突出的房型进度异常。")
    lines.extend(["", "四、原因判断"])
    market = dynamic.get("market") or {}
    share = dynamic.get("market_share") or {}
    browse = dynamic.get("browse") or {}
    first = dynamic.get("first_conversion") or {}
    second = dynamic.get("second_conversion") or {}
    lines.append(
        f"- 大盘：{_status_text(market.get('status'))}；当前估算 "
        f"{_num(market.get('estimated_market_orders'))}单，历史中位 "
        f"{_num(market.get('baseline_median'))}单。"
    )
    lines.append(
        f"- 份额：{_status_text(share.get('status'))}；当前估算 "
        f"{_pct(share.get('current_estimated_market_share'))}，"
        f"历史中位 {_pct(share.get('baseline_median'))}。"
    )
    lines.append(
        f"- 浏览：{_status_text(browse.get('status'))}；当前 "
        f"{_num(browse.get('current'))}，历史中位 "
        f"{_num(browse.get('baseline_median'))}。"
    )
    lines.append(
        f"- 一转：{_status_text(first.get('status'))}；当前 "
        f"{_pct(first.get('current'))}，历史中位 "
        f"{_pct(first.get('baseline_median'))}。"
    )
    lines.append(
        f"- 二转：{_status_text(second.get('status'))}；当前 "
        f"{_pct(second.get('current'))}，历史中位 "
        f"{_pct(second.get('baseline_median'))}。"
    )
    products = dynamic.get("product_prices") or []
    if products:
        lines.append(
            "- 价格：当前商品价格已读取，但暂无同一商品可比历史，"
            "本次不判断偏高或偏低。"
        )
        for product in products[:5]:
            lines.append(
                f"  - {product.get('product_type')}｜"
                f"{product.get('ota_product_name') or product.get('ota_product_id') or '未命名商品'}："
                f"{_money(product.get('current_price'))}。"
            )
    else:
        lines.append("- 价格：当前没有可用的 OTA 商品价格事实。")
    lines.extend(["", "五、建议动作"])
    if action:
        lines.append(
            f"- {action_text}；对象：{action.get('target_scope') or '当前酒店'}；"
            f"观察期：{action.get('observe_minutes') or 0}分钟。"
        )
        lines.append(
            f"- {'需要人工确认' if action.get('requires_manual_confirmation') else '只需继续观察'}；"
            "S16 不直接执行动作。"
        )
    else:
        lines.append(
            "- 当前证据不足或不具备动作条件，暂不生成价格或推广候选。"
        )
    lines.extend(["", "六、数据限制"])
    limitations = dynamic.get("data_limitations") or []
    if limitations:
        lines.extend(f"- {item}" for item in limitations)
    else:
        lines.append("- 当前未发现阻断本次判断的主要数据限制。")
    lines.append(
        "- 具体调价候选和任务仍由 S5/S6 重新核验；"
        "推广执行仍由推广相关能力处理。"
    )
    return "\n".join(lines)


def _patch_builders() -> None:
    import runtime.sales_progress as sales_progress
    from runtime.decisions import baseline as baseline_decision
    from runtime.decisions import deviation as deviation_decision
    from runtime.sales_progress import (
        baseline_service,
        deviation_service,
        service,
    )

    previous_build = baseline_service.build_baseline
    if not getattr(previous_build, "_FINAL_RESPONSIBILITY_V1", False):

        def build_baseline(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return _finalize_baseline(previous_build(*args, **kwargs))

        build_baseline._FINAL_RESPONSIBILITY_V1 = True  # type: ignore[attr-defined]
        baseline_service.build_baseline = build_baseline
        service._build_baseline = build_baseline
        deviation_service.build_baseline = build_baseline
        baseline_decision.build_baseline = build_baseline

    previous_deviation = deviation_service.build_deviation
    if not getattr(
        previous_deviation,
        "_FINAL_RESPONSIBILITY_V1",
        False,
    ):

        def build_deviation(*args: Any, **kwargs: Any) -> dict[str, Any]:
            report = dict(previous_deviation(*args, **kwargs))
            repository = args[0] if args else kwargs.get("repository")
            baseline = kwargs.get("baseline") or {}
            hotel_id = str(
                kwargs.get("hotel_id") or report.get("hotel_id") or ""
            )
            target_date = str(
                kwargs.get("target_date") or report.get("target_date") or ""
            )[:10]
            as_of_datetime = str(
                kwargs.get("as_of_datetime")
                or report.get("as_of_datetime")
                or ""
            )
            if (
                repository is not None
                and baseline
                and hotel_id
                and target_date
                and as_of_datetime
            ):
                report["dynamic_diagnosis"] = build_s16_dynamic_diagnosis(
                    repository,
                    baseline=baseline,
                    progress_report=report,
                    hotel_id=hotel_id,
                    target_date=target_date,
                    as_of_datetime=as_of_datetime,
                )
                report["responsibility_contract_version"] = VERSION
            return report

        build_deviation._FINAL_RESPONSIBILITY_V1 = True  # type: ignore[attr-defined]
        deviation_service.build_deviation = build_deviation
        service._build_deviation = build_deviation
        sales_progress.build_deviation = build_deviation
        deviation_decision.build_deviation = build_deviation

    baseline_decision._cached_baseline = _cached_baseline
    deviation_decision._latest_baseline = _latest_baseline
    os.environ["HOTEL_OTA_S15_CACHE_TTL_SECONDS"] = str(
        CACHE_TTL_SECONDS
    )


def _patch_presentation() -> None:
    from runtime.decisions import baseline as baseline_decision
    from runtime.decisions import deviation as deviation_decision
    from runtime.sales_progress import presentation

    def attach_s15(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        text = _baseline_message(result)
        result.update(
            {
                "summary": text,
                "user_message": text,
                "business_view_version": "s15.zh-CN.baseline-package.v1",
                "analysis_scope": "baseline_package_only",
                "ai_analysis_allowed": False,
                "ai_rewrite_allowed": False,
                "delivery_mode": "authoritative_runtime_text",
                "must_send_text_verbatim": True,
            }
        )
        return result

    def attach_s16(report: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(report)
        text = _dynamic_message(result)
        result.update(
            {
                "summary": text,
                "user_message": text,
                "business_view_version": (
                    "s16.zh-CN.progress-deviation-diagnosis.v1"
                ),
                "analysis_scope": (
                    "progress_deviation_with_dynamic_causes"
                ),
                "ai_analysis_allowed": True,
                "ai_rewrite_allowed": False,
                "delivery_mode": "authoritative_runtime_text",
                "must_send_text_verbatim": True,
            }
        )
        return result

    presentation.build_s15_user_message = _baseline_message
    presentation.build_s16_user_message = _dynamic_message
    presentation.attach_s15_user_view = attach_s15
    presentation.attach_s16_user_view = attach_s16
    baseline_decision.attach_s15_user_view = attach_s15
    deviation_decision.attach_s16_user_view = attach_s16

    try:
        from runtime import s15_s16_complete_output_patch

        s15_s16_complete_output_patch.s15_message = _baseline_message
        s15_s16_complete_output_patch.s16_message = _dynamic_message
    except Exception:
        pass

    from runtime import s15_s16_runtime_patch

    def direct_delivery(
        result: dict[str, Any],
        role: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from runtime.safety.feishu_output import feishu_output_gate

        text = str(
            result.get("user_message")
            or result.get("summary")
            or "当前结果暂不可用。"
        )
        gate = feishu_output_gate(
            source="feishu",
            content_kind="text",
            message=text,
        )
        profile = result.get("output_profile") or (
            "owner_business"
            if role in {"admin", "owner"}
            else "operator_workbench"
        )
        warnings: list[str] = []
        if gate.get("status") != "ok":
            text = "您好，当前业务摘要不能通过飞书业务通道发送。"
            warnings.append(
                f"feishu_output_gate:{gate.get('blocked_reason')}"
            )
        rendered = {
            "status": "ok" if gate.get("status") == "ok" else "blocked",
            "output_profile": profile,
            "text": text,
            "visible_fields": ["user_message"],
            "hidden_fields": ["internal_algorithm_fields"],
            "message_send_attempted": False,
            "template": (
                "s15_baseline_package"
                if result.get("intent") == "sales_baseline_demo"
                else "s16_progress_deviation_diagnosis"
            ),
            "delivery_mode": "authoritative_runtime_text",
            "must_send_text_verbatim": True,
            "ai_rewrite_allowed": False,
        }
        send = {
            "text": text,
            "card": None,
            "send_allowed": gate.get("status") == "ok",
            "output_profile": profile,
            "warnings": warnings,
            "data_source_type": result.get("data_source_type"),
            "freshness_status": result.get("freshness_status"),
            "delivery_mode": "authoritative_runtime_text",
            "must_send_text_verbatim": True,
            "ai_rewrite_allowed": False,
            "ai_analysis_allowed": (
                result.get("intent") == "progress_deviation_demo"
            ),
        }
        return rendered, send

    s15_s16_runtime_patch._direct_delivery = direct_delivery


def _patch_router() -> None:
    from runtime import feishu_command_router as router

    previous = router._detect_intent
    if getattr(previous, "_FINAL_RESPONSIBILITY_V1", False):
        return

    def detect_intent(message: str) -> str:
        raw = str(message or "")
        lowered = raw.lower()
        if any(term in lowered or term in raw for term in _EXECUTION_PHRASES):
            return previous(message)
        weather_terms = (
            "天气", "气温", "降雨", "下雨", "晴天", "阴天", "多云", "台风", "风力",
        )
        if any(term in raw for term in weather_terms):
            return "market_context_demo"
        if any(term in lowered or term in raw for term in _BASELINE_PHRASES):
            return "sales_baseline_demo"
        if any(term in raw for term in _DYNAMIC_PHRASES):
            return "progress_deviation_demo"
        reason_terms = (
            "为什么",
            "原因",
            "怎么回事",
            "问题在哪",
            "哪里有问题",
        )
        today_terms = ("今天", "今日", "当前")
        operation_terms = (
            "经营",
            "销售",
            "进度",
            "房型",
            "大盘",
            "份额",
            "浏览",
            "一转",
            "二转",
            "推广",
            "调价",
        )
        if any(term in raw for term in reason_terms) and any(
            term in raw for term in operation_terms
        ):
            return "progress_deviation_demo"
        if any(term in raw for term in today_terms) and any(
            term in raw
            for term in (
                "怎么样",
                "好不好",
                "是否需要",
                "要不要",
                "需要处理",
            )
        ):
            return "progress_deviation_demo"
        return previous(message)

    detect_intent._FINAL_RESPONSIBILITY_V1 = True  # type: ignore[attr-defined]
    router._detect_intent = detect_intent


def _patch_s5_price_history_gate() -> None:
    # This rule is implemented in the core S5 algorithm so direct runtime,
    # Feishu and test imports cannot diverge due to patch installation order.
    return None


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _patch_builders()
    _patch_presentation()
    _patch_router()
    _patch_s5_price_history_gate()
