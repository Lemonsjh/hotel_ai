from __future__ import annotations

from typing import Any, Mapping

_INSTALLED = False
VERSION = "meituan-activity-net-price-output.v2"


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


def _pct(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def render_product_activity_net_line(product: Mapping[str, Any]) -> str:
    name = (
        product.get("ota_product_name")
        or product.get("ota_product_id")
        or "未命名商品"
    )
    activities = product.get("applied_activities") or []
    factor_text = " × ".join(
        f"{float(item.get('discount_factor')):.2f}"
        for item in activities
        if _n(item.get("discount_factor")) is not None
    )
    if not factor_text:
        factor_text = "1.00"
    return (
        f"  - {product.get('product_type') or '美团商品'}｜{name}："
        f"美团底价 {_money(product.get('raw_price'))}；"
        f"扣佣金率 {_pct(product.get('commission_rate'))} 后底价 "
        f"{_money(product.get('commission_net_base_price'))}；"
        f"匹配 {int(product.get('matched_activity_count') or 0)} 个活动，"
        f"系数 {factor_text} 连续相乘；"
        f"活动后预计酒店收入 "
        f"{_money(product.get('estimated_activity_net_price'))}；"
        "不含用户券。"
    )


def append_remaining_products(
    text: str,
    report: Mapping[str, Any],
) -> str:
    dynamic = report.get("dynamic_diagnosis") or {}
    products = list(dynamic.get("product_prices") or [])
    if len(products) <= 5:
        return text
    lines = ["", "  其余美团商品："]
    lines.extend(render_product_activity_net_line(item) for item in products[5:])
    block = "\n".join(lines)
    marker = "\n\n五、建议动作"
    if marker in text:
        return text.replace(marker, block + marker, 1)
    return text + "\n" + block


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import (
        s15_s16_complete_output_patch,
        s15_s16_responsibility_patch,
    )
    from runtime.sales_progress import presentation

    previous = s15_s16_responsibility_patch._dynamic_message
    if getattr(previous, "_MEITUAN_ACTIVITY_NET_PRICE_OUTPUT_V2", False):
        return

    def render(report: Mapping[str, Any]) -> str:
        return append_remaining_products(previous(report), report)

    render._MEITUAN_ACTIVITY_NET_PRICE_OUTPUT_V2 = True  # type: ignore[attr-defined]
    s15_s16_responsibility_patch._dynamic_message = render
    presentation.build_s16_user_message = render
    s15_s16_complete_output_patch.s16_message = render
