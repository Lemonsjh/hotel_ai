from __future__ import annotations

from typing import Any

_INSTALLED = False

# Optional enrichment/background sources are useful when present, but their
# absence must not be surfaced as a user-facing S17 data gap.
_OPTIONAL_PUBLIC_DATA_GAPS = frozenset(
    {
        "meituan_scan_order",
        "meituan_monthly_background",
        "provider_order_detail",
        "provider_profile_background",
        "room_mix_background",
    }
)

# Internal database and algorithm identifiers may remain in structured evidence,
# but they must never leak into the user-visible S17 narrative.
_PHRASE_REPLACEMENTS = (
    (
        "预订客源分类（guest_source，不是渠道）",
        "预订客源分类（仅表示客源类别，不代表预订渠道）",
    ),
    (
        "实际客源结构（RS01 customer_source）",
        "实际入住客源结构",
    ),
    (
        "实际入住客源结构（RS01）",
        "实际入住客源结构",
    ),
    (
        "实际入住实现（RS01）",
        "实际入住实现",
    ),
    (
        "到店 cohort（按 arrival_time）",
        "到店订单（按计划到店时间统计）",
    ),
    (
        "到店 cohort 入住时长结构",
        "到店订单入住时长结构",
    ),
    (
        "正式字段映射缺少 member_level/booking_product_tag",
        "渠道识别所需的数据映射尚未完成",
    ),
    (
        "canonical room_type_id 缺失",
        "统一房型编码缺失",
    ),
    (
        "canonical room_type_id",
        "统一房型编码",
    ),
    (
        "当前 contact 源值",
        "当前联系人来源值",
    ),
    (
        "是不同 population",
        "属于不同统计口径",
    ),
    (
        "不同 population",
        "不同统计口径",
    ),
)

_IDENTIFIER_REPLACEMENTS = (
    ("guest_source", "客源分类"),
    ("customer_source", "客源分类"),
    ("arrival_time", "计划到店时间"),
    ("member_level", "渠道识别信息"),
    ("booking_product_tag", "渠道产品标签"),
    ("room_type_id", "统一房型编码"),
    ("contact", "联系人信息"),
    ("population", "统计口径"),
)

_CHANNEL_LABELS = {
    "meituan": "美团",
    "ctrip": "携程",
    "fliggy": "飞猪",
    "unknown": "未知",
}
_PROVIDER_GUEST_LABELS = {
    "provider_new": "平台标记新客",
    "provider_returning": "平台标记老客",
    "unknown": "未知",
}
_SOURCE_STATUS_LABELS = {
    "booking": "PMS 预订",
    "realized": "PMS 实际入住",
    "extension": "PMS 续住",
    "real_guest_frequency_realized": "住客频次住宿事实",
    "real_guest_frequency_contact_corroboration": "住客频次联系人辅助",
}
_STATUS_LABELS = {
    "ok": "可用",
    "available_for_cross_check": "可用于交叉核查",
    "unavailable": "不可用",
    "schema_drift": "字段异常",
    "metric_conflict": "指标冲突",
}


def _without_optional_data_gaps(payload: dict[str, Any]) -> dict[str, Any]:
    gaps = payload.get("data_gaps")
    if not isinstance(gaps, (list, tuple)):
        return payload
    public_gaps = [item for item in gaps if str(item) not in _OPTIONAL_PUBLIC_DATA_GAPS]
    if len(public_gaps) == len(gaps):
        return payload
    public_payload = dict(payload)
    public_payload["data_gaps"] = public_gaps
    return public_payload


def _display_number(value: Any, *, decimals: int = 2) -> str:
    if value is None:
        return "不可用"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def _display_percent(value: Any) -> str:
    if value is None:
        return "不可用"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _population(payload: dict[str, Any], key: str) -> dict[str, Any]:
    populations = payload.get("populations")
    if not isinstance(populations, dict):
        return {}
    value = populations.get(key)
    return value if isinstance(value, dict) else {}


def _booking_matrix_section(payload: dict[str, Any]) -> str | None:
    booking = _population(payload, "pms_booking_created")
    matrix = booking.get("booking_matrix")
    if not isinstance(matrix, list) or not matrix:
        return None

    rows: list[str] = []
    for cell in matrix:
        if not isinstance(cell, dict):
            continue
        room_name = str(cell.get("room_type_name") or "房型名称未映射").strip()
        channel = _CHANNEL_LABELS.get(
            str(cell.get("booking_channel") or "unknown"),
            str(cell.get("booking_channel") or "未知"),
        )
        source = str(cell.get("guest_source_class") or "未知")
        created = _display_number(cell.get("created_order_count"))
        rooms = _display_number(cell.get("booked_rooms"))
        active = _display_number(cell.get("active_order_count"))
        active_rooms = _display_number(cell.get("active_booked_rooms"))
        rows.append(
            f"- {channel} / {source} / {room_name}："
            f"{created} 单、{rooms} 间预订房；当前非取消 {active} 单、{active_rooms} 间预订房"
        )
    if not rows:
        return None
    return "预订渠道 × 客源 × 房型矩阵：\n" + "\n".join(rows)


def _contact_proxy_section(payload: dict[str, Any]) -> str | None:
    booking = _population(payload, "pms_booking_created")
    proxy = booking.get("contact_proxy")
    if not isinstance(proxy, dict) or proxy.get("status") != "ok":
        return None

    return (
        "联系人新旧与复购代理（预订联系人，不代表实际入住人）："
        f"可计算非取消联系人 {_display_number(proxy.get('eligible_contact_keys'))} 个，"
        f"其中重复预订联系人 {_display_number(proxy.get('repeat_contact_keys'))} 个"
        f"（{_display_percent(proxy.get('repeat_booking_contact_share_proxy'))}）；"
        f"窗口联系人曾在更早历史出现占比 {_display_percent(proxy.get('contact_seen_before_share_proxy'))}；"
        f"重复预订订单代理占比 {_display_percent(proxy.get('repeat_booking_order_share_proxy'))}；"
        f"已入住状态重复联系人代理占比 {_display_percent(proxy.get('repeat_stayed_contact_share_proxy'))}。"
    )


def _suppressed_count(population: dict[str, Any], *, include_contact_proxy: bool = False) -> int:
    total = 0
    for key, value in population.items():
        if not str(key).startswith("suppressed_") or not str(key).endswith("_cell_count"):
            continue
        try:
            total += max(int(value or 0), 0)
        except (TypeError, ValueError):
            continue
    if include_contact_proxy:
        proxy = population.get("contact_proxy")
        if isinstance(proxy, dict):
            try:
                total += max(int(proxy.get("suppressed_contact_frequency_cell_count") or 0), 0)
            except (TypeError, ValueError):
                pass
    return total


def _quality_section(payload: dict[str, Any]) -> str:
    booking = _population(payload, "pms_booking_created")
    arrival = _population(payload, "pms_arrival_cohort")
    realized = _population(payload, "realized_stay")
    frequency = _population(payload, "real_guest_frequency")
    extension = _population(payload, "extension_reconciliation")

    source_status = payload.get("source_status")
    source_parts: list[str] = []
    if isinstance(source_status, dict):
        for key, label in _SOURCE_STATUS_LABELS.items():
            item = source_status.get(key)
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "unknown")
            source_parts.append(f"{label}{_STATUS_LABELS.get(status, status)}")

    unmapped_parts: list[str] = []
    for label, population in (
        ("预订", booking),
        ("计划到店", arrival),
        ("实际入住", realized),
        ("续住", extension),
    ):
        value = population.get("unmapped_count")
        if value is None:
            continue
        try:
            has_unmapped = float(value) > 0
        except (TypeError, ValueError):
            has_unmapped = True
        if has_unmapped:
            unmapped_parts.append(f"{label} {_display_number(value)}")

    operational_suppressed = (
        _suppressed_count(booking)
        + _suppressed_count(arrival)
        + _suppressed_count(realized)
        + _suppressed_count(frequency)
        + _suppressed_count(extension)
    )
    contact_suppressed = 0
    proxy = booking.get("contact_proxy")
    if isinstance(proxy, dict):
        try:
            contact_suppressed = max(
                int(proxy.get("suppressed_contact_frequency_cell_count") or 0), 0
            )
        except (TypeError, ValueError):
            contact_suppressed = 0

    lines = [
        "口径与质量：",
        f"- 统计窗口：{payload.get('window_start') or '未知'} 至 {payload.get('window_end') or '未知'}；数据截至 {payload.get('as_of_datetime') or '未知'}",
        "- 粒度/单位：预订按订单最新版统计（单、间预订房）；计划到店排除取消单（单、间预订房、间夜）；实际入住按已实现住宿去重（间夜、元、ADR）；住客频次按酒店内标准化姓名与已实现住宿订单聚合（位、次）；续住按有效续住记录统计（条、小时）",
        f"- 核心来源状态：{'、'.join(source_parts) if source_parts else '未提供来源状态'}",
    ]
    if unmapped_parts:
        lines.append(f"- 统一房型未映射：{'、'.join(unmapped_parts)}")
    lines.append(
        f"- 聚合展示：酒店级经营聚合隐藏 {operational_suppressed} 格；联系人代理隐藏 {contact_suppressed} 格。酒店级经营聚合不按个人小样本阈值隐藏，联系人/平台画像仍执行隐私抑制"
    )
    return "\n".join(lines)


def _profile_background_lines(title: str, population: dict[str, Any]) -> list[str]:
    if population.get("status") != "ok":
        return []
    cells = population.get("cells")
    if not isinstance(cells, list) or not cells:
        return []
    rows = [f"{title}："]
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        dimension = str(cell.get("dimension_code") or "维度")
        bucket = str(cell.get("bucket_label") or "未标记")
        rows.append(
            f"- {dimension} / {bucket}：平台比例值 {_display_number(cell.get('rate'))}"
        )
    return rows if len(rows) > 1 else []


def _optional_background_section(payload: dict[str, Any]) -> str | None:
    rows: list[str] = []

    scan = _population(payload, "meituan_scan_order")
    scan_cells = scan.get("cells")
    if isinstance(scan_cells, list) and scan_cells:
        parts: list[str] = []
        for cell in scan_cells:
            if not isinstance(cell, dict):
                continue
            bucket = _PROVIDER_GUEST_LABELS.get(
                str(cell.get("bucket") or "unknown"),
                str(cell.get("bucket") or "未知"),
            )
            parts.append(f"{bucket} {_display_number(cell.get('order_count'))} 单")
        if parts:
            rows.append(
                "美团扫码客源背景："
                f"共 {_display_number(scan.get('total_orders'))} 单；"
                + "、".join(parts)
                + "。该标签来自平台背景，不等于 PMS 实际住客复购。"
            )

    provider_orders = _population(payload, "provider_order_detail")
    provider_cells = provider_orders.get("cells")
    if isinstance(provider_cells, list) and provider_cells:
        rows.append("第三方订单背景（仅交叉核查，不与 PMS 口径相加）：")
        for cell in provider_cells:
            if not isinstance(cell, dict):
                continue
            platform = _CHANNEL_LABELS.get(
                str(cell.get("platform_scope") or "unknown"),
                str(cell.get("platform_scope") or "未知"),
            )
            rows.append(
                f"- {platform}：{_display_number(cell.get('order_count'))} 单、"
                f"{_display_number(cell.get('room_count'))} 间预订房、"
                f"{_display_number(cell.get('room_nights'))} 间夜"
            )

    rows.extend(
        _profile_background_lines(
            "美团月度画像背景（达到隐私阈值的聚合）",
            _population(payload, "meituan_monthly_background"),
        )
    )
    rows.extend(
        _profile_background_lines(
            "第三方画像背景（达到隐私阈值的聚合）",
            _population(payload, "provider_profile_background"),
        )
    )

    for key, label in (("meituan_loss", "美团"), ("ctrip_loss", "携程")):
        loss = _population(payload, key)
        if loss.get("status") != "ok":
            continue
        rows.append(
            f"{label}订单流失代理背景："
            f"{loss.get('period_start') or '-'} 至 {loss.get('period_end') or '-'}，"
            f"流失订单 {_display_number(loss.get('provider_loss_orders'))} 单，"
            f"流失间夜 {_display_number(loss.get('provider_loss_room_nights'))}，"
            f"流失金额 {_display_number(loss.get('provider_loss_amount'))} 元。"
        )

    room_mix = _population(payload, "room_mix_background")
    if room_mix.get("status") == "available_for_cross_check":
        rows.append(
            "房型结构交叉核查背景："
            f"{_display_number(room_mix.get('row_count'))} 条聚合记录可用。"
        )

    if not rows:
        return None
    return "平台增强背景（可用时展示，均不与 PMS 核心口径相加）：\n" + "\n".join(rows)


def _append_before_boundary(text: str, sections: list[str]) -> str:
    clean_sections = [section for section in sections if section and section not in text]
    if not clean_sections:
        return text
    lines = text.splitlines()
    boundary_index = next(
        (index for index, line in enumerate(lines) if line.startswith("边界：")),
        len(lines),
    )
    insertion: list[str] = []
    for section in clean_sections:
        if insertion:
            insertion.append("")
        insertion.extend(section.splitlines())
    lines[boundary_index:boundary_index] = insertion
    return "\n".join(lines)


def enrich_s17_public_summary(text: Any, payload: dict[str, Any]) -> str:
    """Add S17 contract-required public sections using already-computed aggregates."""
    base = str(text or "")
    sections: list[str] = []
    if "预订渠道 × 客源 × 房型矩阵：" not in base:
        matrix = _booking_matrix_section(payload)
        if matrix:
            sections.append(matrix)
    if "联系人新旧与复购代理（预订联系人，不代表实际入住人）：" not in base:
        contact = _contact_proxy_section(payload)
        if contact:
            sections.append(contact)
    optional = _optional_background_section(payload)
    if optional and "平台增强背景（可用时展示，均不与 PMS 核心口径相加）：" not in base:
        sections.append(optional)
    if "口径与质量：" not in base:
        sections.append(_quality_section(payload))
    return _append_before_boundary(base, sections)


def sanitize_s17_public_text(text: Any) -> str:
    """Convert internal S17 identifiers into business-facing Chinese labels."""
    public_text = str(text or "")
    for raw, replacement in _PHRASE_REPLACEMENTS:
        public_text = public_text.replace(raw, replacement)
    for raw, replacement in _IDENTIFIER_REPLACEMENTS:
        public_text = public_text.replace(raw, replacement)
    return public_text


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.decisions import customer

    # The business-rule convergence must become the inner deterministic renderer.
    # This file is the final public presentation layer so its additions are also
    # sanitized and cannot be re-hidden by an older wrapper.
    from runtime.s17_business_rules_patch import install as _install_business_rules_patch

    _install_business_rules_patch()

    previous = customer.render_s17_summary
    if getattr(previous, "_s17_public_text_patch", False):
        return

    def render_s17_summary(payload: dict[str, Any]) -> str:
        safe_payload = _without_optional_data_gaps(payload)
        text = previous(safe_payload)
        text = enrich_s17_public_summary(text, safe_payload)
        return sanitize_s17_public_text(text)

    render_s17_summary._s17_public_text_patch = True  # type: ignore[attr-defined]
    customer.render_s17_summary = render_s17_summary