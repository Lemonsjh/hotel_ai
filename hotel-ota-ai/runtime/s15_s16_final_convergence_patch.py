from __future__ import annotations

import datetime as dt
import re
from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

_INSTALLED = False
VERSION = "s15-s16-final-convergence.v1"
MATURITY_POLICY_VERSION = "s15-hour-grid-recovery.v2"
RECENT_SAMPLE_WINDOW = 6
RECOVERY_THRESHOLD = 0.60
BUSINESS_HOURS = tuple(range(9, 24))
_MATURITY_ORDER = {"unavailable": -1, "trend_only": 0, "weak": 1, "temporary": 2, "stable": 3, "strong": 4}


def _n(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> str:
    number = _n(value)
    if number is None:
        return "—"
    return str(int(round(number))) if abs(number - round(number)) < 1e-9 else f"{number:.1f}"


def _pct(value: Any, digits: int = 1) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.{digits}f}%"


def business_followup_contract() -> dict[str, Any]:
    return {
        "mode": "business_followup_only",
        "rules": [
            "只解释酒店经营结果、数据口径和可执行结论。",
            "普通飞书对话不得输出代码文件名、函数名、补丁安装顺序、提交号、内部字段名或调试链路。",
            "不得向用户提出修改代码、检查仓库或查看采集器配置；结果异常时只说明需要重新生成或交由技术人员排查。",
        ],
        "contract_version": VERSION,
    }


def _full_history_maturity(health: Mapping[str, Any]) -> str:
    maturity = str(health.get("object_maturity") or "trend_only")
    if health.get("maturity_source") != "recent_6_samples" or not health.get("recent_sample_recovered"):
        return maturity
    ratio = _n(health.get("collector_coverage_ratio")) or 0.0
    return "trend_only" if ratio < 0.40 else "weak" if ratio < 0.75 else "temporary"


def layered_collector_health(
    previous: Callable[[Sequence[Mapping[str, Any]]], Mapping[str, Any]],
    points: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    health = dict(previous(points))
    full_maturity = _full_history_maturity(health)
    day_count = max((int(point.get("recent_sample_day_count") or 0) for point in points), default=0)
    full_exact = sum(int(point.get("recent_exact_sample_count") or 0) for point in points)
    business_exact = sum(
        int(point.get("recent_exact_sample_count") or 0)
        for point in points
        if int(point.get("hour") or 0) in BUSINESS_HOURS
    )
    full_expected = day_count * 24
    business_expected = day_count * len(BUSINESS_HOURS)
    full_ratio = full_exact / full_expected if full_expected else 0.0
    business_ratio = business_exact / business_expected if business_expected else 0.0
    recoverable = _MATURITY_ORDER.get(full_maturity, 0) < _MATURITY_ORDER["temporary"] and day_count == RECENT_SAMPLE_WINDOW
    full_recovered = bool(recoverable and full_ratio >= RECOVERY_THRESHOLD)
    business_recovered = bool(recoverable and not full_recovered and business_ratio >= RECOVERY_THRESHOLD)
    source = "recent_6_samples" if full_recovered else "recent_6_business_hours" if business_recovered else "full_history"
    health.update(
        {
            "maturity_policy_version": MATURITY_POLICY_VERSION,
            "full_history_object_maturity": full_maturity,
            "recent_sample_day_count": day_count,
            "recent_exact_sample_cell_count": full_exact,
            "recent_expected_sample_cell_count": full_expected,
            "recent_sample_coverage_ratio": full_ratio,
            "recent_sample_recovery_threshold": RECOVERY_THRESHOLD,
            "recent_full_day_recovered": full_recovered,
            "business_hour_slots": list(BUSINESS_HOURS),
            "recent_business_exact_sample_cell_count": business_exact,
            "recent_business_expected_sample_cell_count": business_expected,
            "recent_business_sample_coverage_ratio": business_ratio,
            "recent_business_sample_recovered": business_recovered,
            "recent_sample_recovered": full_recovered or business_recovered,
            "maturity_source": source,
            "object_maturity": "temporary" if full_recovered or business_recovered else full_maturity,
        }
    )
    return health


def _point_map(points: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for point in points:
        try:
            result[int(point.get("hour"))] = point
        except (TypeError, ValueError):
            pass
    return result


def _current_hour(payload: Mapping[str, Any]) -> int | None:
    try:
        return dt.datetime.fromisoformat(str(payload.get("as_of_datetime") or "").replace("Z", "+00:00")).hour
    except ValueError:
        return None


def _room_hourly_block(payload: Mapping[str, Any]) -> str:
    hours = {9, 12, 14, 16, 18, 20, 22}
    current = _current_hour(payload)
    if current is not None:
        hours.add(current)
    lines = ["二、全部房型小时销售进度（优先保留）", "- 格式：容量线/最终完成线/精确小时样本；fallback 单独标注。"]
    rooms = payload.get("room_types") or {}
    if not rooms:
        return "\n".join(lines + ["- 当前没有可展示的房型小时基准。"])
    for room_id, raw_room in sorted(rooms.items(), key=lambda item: str(item[0])):
        room = raw_room if isinstance(raw_room, Mapping) else {}
        points = _point_map(room.get("hourly_points") or [])
        cells: list[str] = []
        for hour in sorted(hours):
            point = points.get(hour) or {}
            capacity = point.get("capacity") or {}
            completion = point.get("target_completion") or {}
            total = max(int(capacity.get("sample_count") or 0), int(completion.get("sample_count") or 0))
            exact = int(point.get("exact_sample_count") or 0)
            fallback = int(point.get("fallback_sample_count") or 0)
            if total <= 0 or ("exact_sample_count" in point and exact <= 0):
                cells.append(f"{hour:02d}缺口" + (f"(回{fallback})" if fallback else ""))
                continue
            sample = f"精{exact}" if "exact_sample_count" in point else f"样{total}"
            cells.append(f"{hour:02d} 容{_pct(capacity.get('median'), 0)}/完{_pct(completion.get('median'), 0)}/{sample}" + (f"+回{fallback}" if fallback else ""))
        lines.append(f"- {room.get('room_type_name') or room_id}：" + "｜".join(cells))
    return "\n".join(lines)


def _clarify_hotel_samples(text: str, payload: Mapping[str, Any]) -> str:
    points = _point_map(((payload.get("hotel") or {}).get("hourly_points") or []))
    output: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^- (\d{2}):00：", line)
        point = points.get(int(match.group(1))) if match else None
        if not point or "exact_sample_count" not in point:
            output.append(line)
            continue
        capacity = point.get("capacity") or {}
        completion = point.get("target_completion") or {}
        total = max(int(capacity.get("sample_count") or 0), int(completion.get("sample_count") or 0))
        exact = int(point.get("exact_sample_count") or 0)
        fallback = int(point.get("fallback_sample_count") or 0)
        detail = f"；统计样本 {total}天，其中精确小时 {exact}天" + (f"、fallback {fallback}天" if fallback else "") + "。"
        output.append(line.replace(f"；样本 {total}天。", detail))
    return "\n".join(output)


def enhance_s15_message(previous: Callable[[Mapping[str, Any]], str], payload: Mapping[str, Any]) -> str:
    text = previous(payload)
    if payload.get("status") != "ok" or "全部房型小时销售进度（优先保留）" in text:
        return text
    text = text.replace("\n\n五、样本与边界", "\n\n六、样本与边界")
    text = text.replace("\n\n四、价格参考", "\n\n五、价格参考")
    text = text.replace("\n\n三、平台历史基准", "\n\n四、平台历史基准")
    marker = "\n\n二、全店小时销售基准"
    block = _room_hourly_block(payload)
    text = text.replace(marker, "\n\n" + block + "\n\n三、全店小时销售基准", 1) if marker in text else block + "\n\n" + text
    text = _clarify_hotel_samples(text, payload)
    health = ((payload.get("hotel") or {}).get("baseline_health") or {})
    if health:
        source = {"full_history": "完整历史样本", "recent_6_samples": "最近6样本全日", "recent_6_business_hours": "最近6样本营业时段"}.get(str(health.get("maturity_source")), str(health.get("maturity_source") or "完整历史样本"))
        text += (
            "\n- 小时网格成熟度：完整历史覆盖 "
            f"{_pct(health.get('collector_coverage_ratio'))}；最近6样本全日覆盖 {_pct(health.get('recent_sample_coverage_ratio'))}；"
            f"最近6样本营业时段覆盖 {_pct(health.get('recent_business_sample_coverage_ratio'))}；"
            f"最终 {health.get('object_maturity') or '—'}，采用{source}。"
        )
    return text


_REPLACEMENTS = (
    ("本店今日美团订单代理", "本店今日美团支付订单"),
    ("本店当日美团订单代理", "本店当日美团支付订单"),
    ("本店美团订单代理值", "本店美团支付订单"),
    ("本店订单代理值", "本店美团支付订单"),
    ("本店订单代理", "本店美团支付订单"),
    ("本店代理", "本店美团支付订单"),
    ("PMS 订单明细中的美团订单代理值", "美团平台小时支付订单"),
    ("JD01美团订单代理", "美团平台小时支付订单"),
    ("JD01 订单代理", "美团平台小时支付订单"),
    ("PMS订单代理", "美团平台小时支付订单"),
    ("PMS 订单代理", "美团平台小时支付订单"),
    ("订单代理口径", "美团小时采集口径"),
    ("代理数据营业日", "平台数据营业日"),
)


def normalize_s16_text(text: str) -> str:
    result = str(text or "")
    for old, new in _REPLACEMENTS:
        result = result.replace(old, new)
    return result


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _sanitize(item) for key, item in value.items() if key not in {"own_orders_proxy", "own_order_proxy_source"}}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(item) for item in value)
    return normalize_s16_text(value) if isinstance(value, str) else value


def sanitize_s16_result(result: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = _sanitize(deepcopy(dict(result)))
    dynamic = cleaned.get("dynamic_diagnosis") or {}
    proxy = dynamic.get("meituan_market_proxy") or {}
    if isinstance(proxy, Mapping) and str(proxy.get("own_order_source") or "").endswith("FLOW_PAY_ORDER_CNT"):
        dynamic = dict(dynamic)
        dynamic["meituan_market_proxy"] = {**dict(proxy), "own_order_label": "本店美团支付订单", "pms_or_jd01_fallback_used": False}
        cleaned["dynamic_diagnosis"] = dynamic
    return cleaned


def add_s16_platform_order_line(text: str, report: Mapping[str, Any]) -> str:
    proxy = ((report.get("dynamic_diagnosis") or {}).get("meituan_market_proxy") or {})
    if proxy.get("status") != "available" or _n(proxy.get("own_orders")) is None or _n(proxy.get("peer_average_orders")) is None:
        return text
    line = f"- 美团平台小时口径：本店支付订单 {_num(proxy.get('own_orders'))}单；同行平均 {_num(proxy.get('peer_average_orders'))}单/店"
    if proxy.get("peer_hotel_count") not in (None, ""):
        line += f"；同行酒店 {proxy.get('peer_hotel_count')}家"
    if proxy.get("own_order_snapshot_time"):
        line += f"；本店采集时间 {proxy.get('own_order_snapshot_time')}"
    if proxy.get("hourly_collection_may_lag"):
        line += "；小时数据可能存在约1小时采集延迟"
    line += "。"
    marker = "\n\n四、原因判断"
    return text.replace(marker, marker + "\n" + line, 1) if marker in text and line not in text else text


def cache_payload_has_policy(payload: Mapping[str, Any] | None) -> bool:
    health = ((payload or {}).get("hotel") or {}).get("baseline_health") or {}
    return health.get("maturity_policy_version") == MATURITY_POLICY_VERSION


def _patch_maturity() -> None:
    from runtime import s15_s16_spec_alignment_patch as alignment
    from runtime import s15_s16_spec_followup_patch as followup

    previous = followup.collector_health
    if getattr(previous, "_S15_THREE_LAYER_MATURITY_V2", False):
        return

    def collector_health(points: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return layered_collector_health(previous, points)

    collector_health._S15_THREE_LAYER_MATURITY_V2 = True  # type: ignore[attr-defined]
    followup.collector_health = collector_health
    alignment.collector_health = collector_health


def _patch_cache() -> None:
    from runtime import s15_s16_responsibility_patch as responsibility

    previous = responsibility._valid_cached
    if getattr(previous, "_S15_MATURITY_CACHE_V2", False):
        return

    def valid_cached(payload: Mapping[str, Any] | None) -> bool:
        return bool(previous(payload) and cache_payload_has_policy(payload))

    valid_cached._S15_MATURITY_CACHE_V2 = True  # type: ignore[attr-defined]
    responsibility._valid_cached = valid_cached


def _patch_presentations() -> None:
    from runtime import s15_s16_complete_output_patch as complete
    from runtime import s15_s16_responsibility_patch as responsibility
    from runtime.sales_progress import presentation

    previous_s15 = responsibility._baseline_message
    if not getattr(previous_s15, "_S15_FINAL_CONVERGENCE_V1", False):
        def s15_message(payload: Mapping[str, Any]) -> str:
            return enhance_s15_message(previous_s15, payload)
        s15_message._S15_FINAL_CONVERGENCE_V1 = True  # type: ignore[attr-defined]
        responsibility._baseline_message = presentation.build_s15_user_message = complete.s15_message = s15_message

    previous_s16 = responsibility._dynamic_message
    if not getattr(previous_s16, "_S16_FINAL_CONVERGENCE_V1", False):
        def s16_message(report: Mapping[str, Any]) -> str:
            cleaned = sanitize_s16_result(report)
            return add_s16_platform_order_line(normalize_s16_text(previous_s16(cleaned)), cleaned)
        s16_message._S16_FINAL_CONVERGENCE_V1 = True  # type: ignore[attr-defined]
        responsibility._dynamic_message = presentation.build_s16_user_message = complete.s16_message = s16_message


def _patch_contract_and_delivery() -> None:
    from runtime import s15_s16_runtime_patch
    from runtime import s16_skill_delivery_patch as delivery

    previous_contract = delivery.build_s16_response_contract
    if not getattr(previous_contract, "_S16_FINAL_CONVERGENCE_V1", False):
        def build_s16_response_contract(result: Mapping[str, Any]) -> dict[str, Any]:
            contract = dict(previous_contract(sanitize_s16_result(result)))
            preserve = list(contract.get("must_preserve") or []) + ["本店订单必须称为美团支付订单，来源为FLOW_PAY_ORDER_CNT", "同行平均、酒店数和排名来自PAY_ORDER_CNT"]
            forbidden = list(contract.get("forbidden") or []) + ["输出代码文件名、函数名、补丁名、提交号、安装顺序或调试链路", "解释为JD01、PMS关键词匹配或订单代理值", "询问用户是否需要修改代码"]
            contract.update({"must_preserve": list(dict.fromkeys(preserve)), "forbidden": list(dict.fromkeys(forbidden)), "contract_version": VERSION})
            return contract
        build_s16_response_contract._S16_FINAL_CONVERGENCE_V1 = True  # type: ignore[attr-defined]
        delivery.build_s16_response_contract = build_s16_response_contract

    previous_delivery = s15_s16_runtime_patch._direct_delivery
    if getattr(previous_delivery, "_S15_S16_FINAL_CONVERGENCE_V1", False):
        return

    def direct_delivery(result: dict[str, Any], role: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        intent = str(result.get("intent") or "")
        prepared = sanitize_s16_result(result) if intent == "progress_deviation_demo" else dict(result)
        rendered, send = previous_delivery(prepared, role)
        rendered, send = dict(rendered), dict(send)
        followup_contract = business_followup_contract()
        if intent == "sales_baseline_demo":
            contract = {
                "mode": "authoritative_s15_business_explanation",
                "facts_are_authoritative": True,
                "must_preserve_room_type_hourly_lines": True,
                "must_preserve_maturity_layers": True,
                "forbidden": ["输出代码文件名、函数名、补丁名、提交号、安装顺序或调试链路", "把fallback计入精确覆盖率", "询问用户是否需要修改代码或检查采集器源码"],
                "contract_version": VERSION,
            }
            send.update({
                "assistant_response_contract": contract,
                "assistant_followup_contract": followup_contract,
                "authoritative_fallback_text": send.get("text"),
            })
        if intent == "progress_deviation_demo":
            for target in (rendered, send):
                if target.get("text") is not None:
                    target["text"] = normalize_s16_text(str(target.get("text") or ""))
            if send.get("authoritative_fallback_text") is not None:
                send["authoritative_fallback_text"] = normalize_s16_text(str(send["authoritative_fallback_text"]))
            send["assistant_followup_contract"] = followup_contract
        rendered["assistant_response_contract_version"] = VERSION
        return rendered, send

    direct_delivery._S15_S16_FINAL_CONVERGENCE_V1 = True  # type: ignore[attr-defined]
    s15_s16_runtime_patch._direct_delivery = direct_delivery


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _patch_maturity()
    _patch_cache()
    _patch_presentations()
    _patch_contract_and_delivery()
