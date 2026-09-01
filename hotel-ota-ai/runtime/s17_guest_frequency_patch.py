from __future__ import annotations

import argparse
import contextvars
import datetime as dt
import re
from typing import Any, Callable

from runtime.algorithms.guest_frequency import aggregate_real_guest_frequency


_INSTALLED = False
_GUEST_NAME_CONTEXT: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "s17_guest_name_lookup", default=None
)
_BULK_GUEST_FREQUENCY_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "s17_bulk_guest_frequency", default=False
)
_BULK_GUEST_FREQUENCY_MIN_VISITS_CONTEXT: contextvars.ContextVar[int] = contextvars.ContextVar(
    "s17_bulk_guest_frequency_min_visits", default=1
)
_GUEST_NAME_CHARS = r"[\u3400-\u9fffA-Za-z·•・.]{1,32}?"
_VISIT_COUNT_PATTERN = r"(?P<count>\d+|[一二三四五六七八九十])"
_VISIT_COUNT_VALUES = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_GUEST_LOOKUP_PATTERNS = (
    re.compile(rf"(?:查询|查看|统计)?\s*(?:客户|住客)\s*[：:]?\s*(?P<name>{_GUEST_NAME_CHARS})\s*(?:的)?\s*(?:到店几次|到店次数|到店频率|消费频率)"),
    re.compile(rf"(?:查询|查看|统计)\s*(?P<name>{_GUEST_NAME_CHARS})\s*(?:的)?\s*(?:到店几次|到店次数|到店频率|消费频率)"),
    re.compile(rf"(?P<name>{_GUEST_NAME_CHARS})\s*(?:的)?\s*(?:到店几次|到店次数|到店频率|消费频率)"),
)
_BULK_GUEST_FREQUENCY_PATTERNS = (
    re.compile(r"(?:按|按照)\s*(?:客户|住客)?姓名.{0,20}(?:统计|查看|查询|展示|列出).{0,20}(?:到店次数|到店几次|到店频率|消费频率)"),
    re.compile(r"(?:批量|全部|所有).{0,8}(?:统计|查看|查询|展示|列出).{0,12}(?:客户|住客).{0,12}(?:到店次数|到店几次|到店频率|消费频率)"),
    re.compile(r"(?:统计|查看|查询|展示|列出).{0,8}(?:全部|所有|批量).{0,12}(?:客户|住客).{0,12}(?:到店次数|到店几次|到店频率|消费频率)"),
    re.compile(r"(?:客户|住客)(?:的)?姓名.{0,8}(?:和|及|与|、).{0,8}(?:到店次数|到店频率|消费频率)"),
    re.compile(r"(?:每个|每位|各个|各位|各|所有)(?:客户|客人|住客).{0,12}(?:到店次数|到店的次数|到店几次|到店频率|消费频率)"),
    re.compile(r"(?:客户|客人|住客).{0,8}(?:分别|各自).{0,8}(?:来了几次|到店几次|到店次数|到店频率|消费频率)"),
    re.compile(r"(?:客户|客人|住客)(?:的)?到店次数明细"),
)
_HIGH_FREQUENCY_GUEST_PATTERNS = (
    re.compile(
        r"(?:高频(?:到店)?(?:的)?(?:客户|客人|住客)|"
        r"(?:经常到店|经常来|常来)(?:的)?(?:客户|客人|住客)|常客|"
        r"(?:客户|客人|住客).{0,6}高频到店)"
        r".{0,16}(?:有哪些|是谁|哪些人|名字|姓名|名单|展示|列出)?"
    ),
)
_REPEAT_GUEST_FREQUENCY_PATTERNS = (
    re.compile(r"(?:客户|客人|住客)?到店次数分析"),
    re.compile(
        r"(?:回头客|复购(?:客户|客人|住客)|"
        r"重复到店(?:的)?(?:客户|客人|住客)|重复入住(?:的)?(?:客户|客人|住客)|"
        r"再次到店(?:的)?(?:客户|客人|住客)|来过不止一次(?:的)?(?:客户|客人|住客))"
        r".{0,12}(?:名字|姓名|名单)?"
    ),
)
_EXPLICIT_GUEST_FREQUENCY_CONTEXT = re.compile(
    r"(?:客户|客人|住客|到店|入住|来过|名字|姓名|名单|哪些人|有哪些|谁)"
)
_EXPLICIT_GUEST_FREQUENCY_PATTERNS = (
    (re.compile(rf"(?:至少|不少于)\s*{_VISIT_COUNT_PATTERN}\s*次"), 0),
    (re.compile(rf"{_VISIT_COUNT_PATTERN}\s*次(?:及)?以上"), 0),
    (re.compile(rf"(?:超过|多于)\s*{_VISIT_COUNT_PATTERN}\s*次"), 1),
)


def _visit_count_value(value: Any) -> int | None:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    return _VISIT_COUNT_VALUES.get(text)


def _explicit_guest_frequency_min_visits(text: str) -> int | None:
    if not _EXPLICIT_GUEST_FREQUENCY_CONTEXT.search(text):
        return None
    for pattern, increment in _EXPLICIT_GUEST_FREQUENCY_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        count = _visit_count_value(match.group("count"))
        if count is not None:
            return max(count + increment, 1)
    return None


def _bulk_guest_frequency_min_visits(message: Any) -> int | None:
    text = str(message or "").strip()
    if not text:
        return None
    explicit_minimum = _explicit_guest_frequency_min_visits(text)
    if explicit_minimum is not None:
        return explicit_minimum
    if any(pattern.search(text) for pattern in _HIGH_FREQUENCY_GUEST_PATTERNS):
        return 3
    if any(pattern.search(text) for pattern in _REPEAT_GUEST_FREQUENCY_PATTERNS):
        return 2
    if any(pattern.search(text) for pattern in _BULK_GUEST_FREQUENCY_PATTERNS):
        return 1
    return None


def _is_bulk_guest_frequency_request(message: Any) -> bool:
    return _bulk_guest_frequency_min_visits(message) is not None


def _extract_guest_name_lookup(message: Any) -> str | None:
    if _is_bulk_guest_frequency_request(message):
        return None
    text = str(message or "")
    for pattern in _GUEST_LOOKUP_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        name = str(match.group("name") or "").strip(" ：:，,。.!！?？")
        if name and name not in {"客户", "住客", "查询", "查看", "统计", "到店"}:
            return name
    return None


def _message_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if args:
        return str(args[0] or "")
    return str(kwargs.get("message") or "")


def _guest_selector(value: Any) -> str | None:
    text = str(value or "").strip()
    prefix = "guest_name:"
    return text[len(prefix) :].strip() if text.startswith(prefix) else None


def _parse_iso(value: Any, fallback: dt.datetime) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _date_only(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else (text or "未知")


def _bulk_guest_frequency_summary(payload: dict[str, Any], minimum_visits: int) -> str | None:
    populations = payload.get("populations") if isinstance(payload.get("populations"), dict) else {}
    frequency = populations.get("real_guest_frequency") if isinstance(populations.get("real_guest_frequency"), dict) else {}
    if frequency.get("status") != "ok":
        return None

    minimum = max(int(minimum_visits or 1), 1)
    roster = [
        row
        for row in (frequency.get("guest_name_visit_counts") or [])
        if isinstance(row, dict) and int(row.get("visit_count") or 0) >= minimum
    ]
    roster.sort(
        key=lambda row: (
            -int(row.get("visit_count") or 0),
            str(row.get("guest_name") or ""),
        )
    )

    window_start = _date_only(payload.get("window_start"))
    window_end = _date_only(payload.get("window_end"))
    lines = [f"S17 客户到店次数（{window_start} 至 {window_end}）"]

    if minimum >= 3:
        label = f"到店 {minimum} 次及以上的高频客户"
    elif minimum >= 2:
        label = f"到店 {minimum} 次及以上客户"
    else:
        label = "客户到店次数"

    if roster:
        if minimum >= 2:
            lines.append(f"{label}共 {len(roster)} 位：")
        else:
            lines.append(f"窗口内共识别 {len(roster)} 个有效客户姓名：")
        lines.extend(_guest_name_visit_counts_text(roster).splitlines())
    else:
        lines.append(f"{label}：当前统计窗口内没有符合条件的客户。")

    lines.extend(
        [
            "",
            "口径：按酒店内标准化姓名和已实现住宿订单统计；同名客户可能存在同名异人。",
        ]
    )
    return "\n".join(lines)


def _install_repository_patch(repository: Any) -> None:
    original: Callable[..., dict[str, Any]] = repository.query_mysql_s17
    if getattr(original, "_s17_guest_frequency_patch", False):
        return

    def query_mysql_s17(conn: Any, args: Any, profile: dict[str, Any]) -> dict[str, Any]:
        lookup_name = _guest_selector(getattr(args, "contact_lookup_value", None))
        bulk_requested = _BULK_GUEST_FREQUENCY_CONTEXT.get()
        original_args = args
        if lookup_name:
            original_args = argparse.Namespace(**vars(args))
            original_args.contact_lookup_value = None
        payload = original(conn, original_args, profile)
        if payload.get("status") == "blocked":
            return payload

        now = dt.datetime.now()
        as_of = _parse_iso(payload.get("as_of_datetime"), now)
        window_end = _parse_iso(payload.get("window_end"), as_of)
        window_start = _parse_iso(payload.get("window_start"), window_end - dt.timedelta(days=30))

        realized_fields = (
            "hotel_id",
            "source_platform",
            "order_id",
            "room_no",
            "guest_name",
            "charge_subject",
            "business_date",
            "checkin_time",
            "checkout_time",
            "room_nights",
            "room_fee",
            "snapshot_time",
        )
        booking_fields = (
            "hotel_id",
            "source_platform",
            "order_id",
            "contact",
            "snapshot_time",
        )
        realized_rows, realized_meta = repository._mapped_rows(
            conn,
            profile,
            repository.CORE_TABLES["realized"],
            args.hotel_id,
            as_of=as_of,
            fields=realized_fields,
        )
        booking_rows, booking_meta = repository._mapped_rows(
            conn,
            profile,
            repository.CORE_TABLES["booking"],
            args.hotel_id,
            as_of=as_of,
            fields=booking_fields,
        )

        realized_columns = (
            ((profile.get("columns") or {}).get(repository.CORE_TABLES["realized"]) or {})
            if isinstance(profile, dict)
            else {}
        )
        if not realized_columns.get("guest_name"):
            frequency = {
                "population_id": "real_guest_frequency",
                "status": "unavailable",
                "reason": "guest_name_field_mapping_missing",
                "primary_identity_key": "guest_name",
                "identity_scope": "hotel_id+normalized_guest_name",
                "contact_role": "auxiliary_corroboration_only_not_primary_key",
                "exact_lookup": None,
                "guest_name_visit_counts": [],
                "bulk_guest_name_list_included": False,
                "raw_contact_included": False,
                "direct_action_allowed": False,
            }
        elif realized_meta.get("status") != "ok":
            frequency = {
                "population_id": "real_guest_frequency",
                "status": "unavailable",
                "reason": realized_meta.get("reason") or "realized_guest_source_unavailable",
                "primary_identity_key": "guest_name",
                "identity_scope": "hotel_id+normalized_guest_name",
                "contact_role": "auxiliary_corroboration_only_not_primary_key",
                "exact_lookup": None,
                "guest_name_visit_counts": [],
                "bulk_guest_name_list_included": False,
                "raw_contact_included": False,
                "direct_action_allowed": False,
            }
        else:
            import os

            frequency = aggregate_real_guest_frequency(
                realized_rows,
                booking_rows if booking_meta.get("status") == "ok" else [],
                hotel_id=str(args.hotel_id),
                window_start=window_start,
                window_end=window_end,
                as_of=as_of,
                contact_hmac_secret=os.environ.get("HOTEL_OTA_S17_CONTACT_HMAC_SECRET"),
                guest_name_lookup=lookup_name,
            )
            if not bulk_requested:
                frequency["guest_name_visit_counts"] = []
                frequency["bulk_guest_name_list_included"] = False

        minimum = int(
            (payload.get("privacy_policy") or {}).get("minimum_cohort_size") or 5
        )
        maximum = int(
            (payload.get("privacy_policy") or {}).get("max_output_cells") or 100
        )
        cells, suppressed = repository.suppress_cells(
            frequency.get("frequency_distribution") or [],
            count_field="value",
            minimum_cohort_size=minimum,
            max_output_cells=maximum,
        )
        frequency["frequency_distribution"] = cells
        frequency["suppressed_frequency_distribution_cell_count"] = suppressed

        populations = payload.setdefault("populations", {})
        populations["real_guest_frequency"] = frequency
        source_status = payload.setdefault("source_status", {})
        source_status["real_guest_frequency_realized"] = realized_meta
        source_status["real_guest_frequency_contact_corroboration"] = booking_meta

        privacy_policy = payload.setdefault("privacy_policy", {})
        privacy_policy["policy_version"] = "s17-privacy.v3"
        privacy_policy["exact_guest_name_lookup_allowed"] = True
        privacy_policy["guest_name_primary_key_scope"] = "exact_hotel_id"
        privacy_policy["bulk_named_roster_allowed"] = True
        privacy_policy["phone_primary_key_allowed"] = False

        gaps = list(payload.get("data_gaps") or [])
        if frequency.get("status") == "unavailable" and frequency.get("reason"):
            reason = str(frequency["reason"])
            if reason not in gaps:
                gaps.append(reason)
        payload["data_gaps"] = gaps
        payload["raw_guest_name_roster_included"] = bool(
            bulk_requested and frequency.get("guest_name_visit_counts")
        )
        payload["exact_guest_name_lookup_included"] = bool(lookup_name)
        payload["raw_contact_included"] = False
        payload["contact_fingerprint_included"] = False
        return payload

    query_mysql_s17._s17_guest_frequency_patch = True  # type: ignore[attr-defined]
    repository.query_mysql_s17 = query_mysql_s17


def _frequency_distribution_text(cells: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for cell in cells:
        name = str(cell.get("name") or "未知")
        value = cell.get("value")
        parts.append(f"{name} {int(value or 0)} 位")
    return "、".join(parts)


def _guest_name_visit_counts_text(rows: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {str(row.get('guest_name') or '姓名缺失')}：{int(row.get('visit_count') or 0)} 次"
        for row in rows
    )


def _install_customer_patch(customer: Any) -> None:
    previous_render = customer.render_s17_summary
    if not getattr(previous_render, "_s17_guest_frequency_patch", False):
        def render_s17_summary(payload: dict[str, Any]) -> str:
            text = previous_render(payload)
            populations = payload.get("populations") if isinstance(payload.get("populations"), dict) else {}
            frequency = populations.get("real_guest_frequency") if isinstance(populations.get("real_guest_frequency"), dict) else {}
            if frequency.get("status") != "ok":
                return text
            line = (
                "真实住客到店频率（受控画像，姓名为主键）："
                f"窗口内可识别 {int(frequency.get('unique_guest_name_count') or 0)} 位；"
            )
            distribution = _frequency_distribution_text(frequency.get("frequency_distribution") or [])
            line += distribution + "。" if distribution else "频率等级分布因小群体保护未展示。"
            if _BULK_GUEST_FREQUENCY_CONTEXT.get():
                minimum_visits = max(_BULK_GUEST_FREQUENCY_MIN_VISITS_CONTEXT.get(), 1)
                roster = [
                    row
                    for row in (frequency.get("guest_name_visit_counts") or [])
                    if isinstance(row, dict) and int(row.get("visit_count") or 0) >= minimum_visits
                ]
                roster.sort(
                    key=lambda row: (
                        -int(row.get("visit_count") or 0),
                        str(row.get("guest_name") or ""),
                    )
                )
                if roster:
                    if minimum_visits >= 2:
                        line += f"\n窗口内到店 {minimum_visits} 次及以上客户（{len(roster)} 位）：\n"
                    else:
                        line += "\n客户姓名与到店次数：\n"
                    line += _guest_name_visit_counts_text(roster)
                elif minimum_visits >= 2:
                    line += f"\n窗口内没有到店 {minimum_visits} 次及以上的客户姓名。"
                else:
                    line += "\n客户姓名与到店次数：当前统计窗口内没有可识别的已实现到店记录。"
            lines = text.splitlines()
            boundary_index = next(
                (index for index, value in enumerate(lines) if value.startswith("边界：")),
                len(lines),
            )
            lines.insert(boundary_index, line)
            return "\n".join(lines)

        render_s17_summary._s17_guest_frequency_patch = True  # type: ignore[attr-defined]
        customer.render_s17_summary = render_s17_summary

    original_customer_analysis = customer.customer_analysis
    if getattr(original_customer_analysis, "_s17_guest_frequency_patch", False):
        return

    def customer_analysis(args: Any) -> None:
        guest_name = getattr(args, "guest_name_lookup", None) or _GUEST_NAME_CONTEXT.get()
        if not guest_name:
            return original_customer_analysis(args)

        if not customer.database_source_enabled():
            customer.emit(
                customer.standard_envelope(
                    status="data_gap",
                    skill_id="S17",
                    summary="真实住客到店频率统计需要只读 PMS 数据库；当前数据库来源未启用。",
                    evidence={"blocked_reason": "database_source_disabled", "direct_action_allowed": False},
                    recommendations=["请启用 S17 只读数据库来源并确认当前酒店映射。"],
                    risk_level="medium",
                )
            )
            return

        result = customer.database_template_result(
            "customer_order_analysis",
            args.hotel_id,
            period_start=getattr(args, "period_start", None),
            period_end=getattr(args, "period_end", None),
            as_of_time=getattr(args, "as_of_time", None),
            minimum_cohort_size=getattr(args, "minimum_cohort_size", None),
            max_output_cells=getattr(args, "max_output_cells", None),
            contact_lookup_value=f"guest_name:{guest_name}",
        )
        if result.get("status") != "ok":
            customer.emit(
                customer.standard_envelope(
                    status="data_gap",
                    skill_id="S17",
                    summary="真实住客到店频率统计无法读取受控 PMS 聚合。",
                    evidence={
                        "database_result_status": result.get("status"),
                        "reason": result.get("reason"),
                        "direct_action_allowed": False,
                    },
                    recommendations=["请检查 RS01 姓名字段、JD01 联系方式映射和只读数据库配置。"],
                    risk_level="medium",
                )
            )
            return

        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        populations = payload.get("populations") if isinstance(payload.get("populations"), dict) else {}
        frequency = populations.get("real_guest_frequency") if isinstance(populations.get("real_guest_frequency"), dict) else {}
        lookup = frequency.get("exact_lookup") if isinstance(frequency.get("exact_lookup"), dict) else None

        if frequency.get("status") == "unavailable" and frequency.get("reason") == "guest_name_field_mapping_missing":
            status = "data_gap"
            summary = "真实住客到店频率暂不可用：RS01 的住客姓名字段尚未完成正式映射。"
        elif lookup is None:
            status = "data_gap"
            summary = "真实住客到店频率暂不可用：当前姓名无法形成受控查询键。"
        else:
            status = "ok"
            count = int(lookup.get("visit_count") or 0)
            level = str(lookup.get("frequency_level") or "未观察到到店")
            display_name = str(lookup.get("guest_name") or guest_name)
            if count:
                summary = (
                    f"住客“{display_name}”在当前统计窗口内已实现到店 {count} 次，"
                    f"消费频率等级：{level}。"
                )
                if lookup.get("first_arrival_date") or lookup.get("last_arrival_date"):
                    summary += (
                        f"首次可见到店：{lookup.get('first_arrival_date') or '不可用'}；"
                        f"最近可见到店：{lookup.get('last_arrival_date') or '不可用'}。"
                    )
            else:
                summary = f"住客“{display_name}”在当前统计窗口内未观察到已实现到店记录，消费频率等级：{level}。"
            if lookup.get("contact_corroboration") == "multiple_contacts_same_name":
                summary += " 同一姓名关联到多个受控联系方式指纹；仍按姓名主键合并计数，但存在同名异人风险，建议人工核查。"

        evidence = {
            "real_guest_frequency_lookup": lookup,
            "history_window": {
                "start": payload.get("window_start"),
                "end": payload.get("window_end"),
            },
            "primary_identity_key": "guest_name",
            "identity_scope": "exact_hotel_id",
            "contact_role": "auxiliary_corroboration_only_not_primary_key",
            "raw_contact_included": False,
            "bulk_guest_name_list_included": False,
            "direct_action_allowed": False,
        }
        customer.emit(
            customer.standard_envelope(
                status=status,
                skill_id="S17",
                summary=summary,
                evidence=evidence,
                recommendations=["该结果仅用于受控到店频率核查，不得据此自动创建营销、联系、调价或其他执行动作。"],
                actions=[],
                risk_level="medium" if lookup and lookup.get("identity_status") == "needs_check" else "low",
            )
        )

    customer_analysis._s17_guest_frequency_patch = True  # type: ignore[attr-defined]
    customer.customer_analysis = customer_analysis


def _install_route_patch(router: Any, s17_route: Any) -> None:
    original_is_s17 = s17_route._is_s17_message
    if not getattr(original_is_s17, "_s17_guest_frequency_patch", False):
        def is_s17_message(message: Any) -> bool:
            return (
                _is_bulk_guest_frequency_request(message)
                or bool(_extract_guest_name_lookup(message))
                or original_is_s17(message)
            )

        is_s17_message._s17_guest_frequency_patch = True  # type: ignore[attr-defined]
        s17_route._is_s17_message = is_s17_message

    original_safe = router.safe_route_feishu_command
    if getattr(original_safe, "_s17_guest_frequency_patch", False):
        return

    def safe_route_feishu_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
        message = _message_from_call(args, kwargs)
        minimum_visits = _bulk_guest_frequency_min_visits(message)
        bulk_requested = minimum_visits is not None
        guest_name = _extract_guest_name_lookup(message)
        if not guest_name and not bulk_requested:
            return original_safe(*args, **kwargs)

        requested_render = bool(kwargs.get("render", True))
        requested_compact = bool(kwargs.get("compact", False))
        route_kwargs = dict(kwargs)
        if bulk_requested:
            route_kwargs["render"] = False
            route_kwargs["compact"] = False

        guest_token = _GUEST_NAME_CONTEXT.set(guest_name)
        bulk_token = _BULK_GUEST_FREQUENCY_CONTEXT.set(bulk_requested)
        minimum_token = _BULK_GUEST_FREQUENCY_MIN_VISITS_CONTEXT.set(minimum_visits or 1)
        try:
            result = original_safe(*args, **route_kwargs)
        finally:
            _BULK_GUEST_FREQUENCY_MIN_VISITS_CONTEXT.reset(minimum_token)
            _BULK_GUEST_FREQUENCY_CONTEXT.reset(bulk_token)
            _GUEST_NAME_CONTEXT.reset(guest_token)

        if not bulk_requested or not isinstance(result, dict) or result.get("status") != "ok":
            return result

        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
        focused_summary = _bulk_guest_frequency_summary(evidence, minimum_visits or 1)
        if not focused_summary:
            return result

        focused_result = dict(result)
        focused_result["summary"] = focused_summary
        focused_result["presentation_scope"] = "guest_frequency"
        focused_result.pop("rendered", None)
        focused_result.pop("send_payload", None)
        role = str(
            focused_result.get("personal_role")
            or focused_result.get("auth_role")
            or kwargs.get("role")
            or "guest"
        )
        return s17_route._finish_result(
            router,
            focused_result,
            render=requested_render,
            compact=requested_compact,
            role=role,
        )

    safe_route_feishu_command._s17_guest_frequency_patch = True  # type: ignore[attr-defined]
    router.safe_route_feishu_command = safe_route_feishu_command


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router
    from runtime.adapters import s17_repository as repository
    from runtime.decisions import customer
    from runtime import s17_feishu_route_patch as s17_route

    _install_repository_patch(repository)
    _install_customer_patch(customer)
    _install_route_patch(router, s17_route)


__all__ = ["install"]
