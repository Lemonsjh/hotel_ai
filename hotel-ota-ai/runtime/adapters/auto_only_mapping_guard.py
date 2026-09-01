from __future__ import annotations

from typing import Any


AUTO_MAPPING_STATUS = "AUTO"
_INSTALLED = False


def _mapping_status(row: dict[str, Any]) -> str:
    return str(row.get("mapping_status") or "").strip().upper()


def is_auto_price_mapping(row: dict[str, Any]) -> bool:
    """Only AUTO is eligible for the S5/S6 price-write mapping gate."""

    return _mapping_status(row) == AUTO_MAPPING_STATUS


def auto_price_mapping_trust_basis(row: dict[str, Any]) -> str:
    return (
        "active_auto_mapping"
        if is_auto_price_mapping(row)
        else "mapping_status_not_auto"
    )


def auto_only_price_task_mapping_ready(
    row: dict[str, Any],
    *,
    disabled_platforms: set[str] | None = None,
) -> dict[str, Any]:
    from runtime.adapters import normalized_query as normalized

    platform = normalized.normalize_source_platform(
        normalized._value(row, "source_platform", "channel_source", "platform")
    )
    source_product_id = normalized._value(
        row,
        "source_product_id",
        "ota_product_id",
    )
    status = _mapping_status(row)
    active = normalized._truthy(
        normalized._value(row, "mapping_active", "is_active", "active")
    )
    resolution = str(
        normalized._value(row, "mapping_resolution_status") or ""
    ).strip().lower()

    raw_risks = row.get("mapping_risk_flags")
    if raw_risks in (None, ""):
        raw_risks = row.get("risk_flags")
    if isinstance(raw_risks, str):
        mapping_risks = {
            item.strip() for item in raw_risks.split(",") if item.strip()
        }
    elif isinstance(raw_risks, (list, tuple, set)):
        mapping_risks = {
            str(item).strip() for item in raw_risks if str(item).strip()
        }
    else:
        mapping_risks = set()

    disabled = disabled_platforms or normalized.DISABLED_PRICE_TASK_PLATFORMS
    blocking_mapping_risks = {
        "mapping_conflict",
        "mapping_candidate_name_match",
        "inferred_by_name",
        "tenant_scope_mismatch",
        "tenant_scope_unresolved",
    }
    risks: list[str] = []
    blocked_reason: str | None = None

    if status != AUTO_MAPPING_STATUS:
        risks.append("price_task_blocked")
        blocked_reason = "mapping_status_not_auto"
    elif resolution and resolution != "mapped":
        risks.append("price_task_blocked")
        blocked_reason = "mapping_not_exact"
    elif mapping_risks & blocking_mapping_risks:
        risks.append("price_task_blocked")
        blocked_reason = "mapping_not_exact"
    elif not active:
        risks.append("price_task_blocked")
        blocked_reason = "mapping_inactive"
    elif not normalized._value(row, "room_type_id", "pms_room_type_id"):
        risks.append("price_task_blocked")
        blocked_reason = "room_type_id_missing"
    elif not source_product_id:
        risks.append("price_task_blocked")
        blocked_reason = "source_product_id_missing"
    elif platform in disabled:
        risks.append("price_task_blocked")
        blocked_reason = "source_platform_disabled"
    elif platform == "ctrip" and not normalized._value(row, "product_cipher"):
        risks.append("price_task_blocked")
        blocked_reason = "ctrip_product_cipher_missing"

    return {
        "ready_for_price_task": blocked_reason is None,
        "blocked_reason": blocked_reason,
        "mapping_trust_basis": auto_price_mapping_trust_basis(row),
        "mapping_resolution_status": (
            "mapped"
            if blocked_reason is None
            else (
                "mapping_inactive"
                if blocked_reason == "mapping_inactive"
                else "mapping_pending"
            )
        ),
        "risk_flags": risks,
    }


def _auto_only_product_skip_reason(
    channel_source: str,
    product: dict[str, Any],
) -> str | None:
    from runtime.adapters import normalized_query as normalized

    if not (product.get("ota_product_id") or product.get("source_product_id")):
        return "ota_product_id_missing"
    gate = normalized.is_price_task_mapping_ready(
        {**product, "source_platform": channel_source}
    )
    if not gate.get("ready_for_price_task"):
        return str(
            gate.get("blocked_reason")
            or gate.get("mapping_resolution_status")
            or "mapping_pending"
        )
    if channel_source == "ctrip" and not product.get("product_cipher"):
        return "ctrip_product_cipher_missing"
    return None


def install_auto_only_mapping_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from runtime.adapters import normalized_query as normalized
    from runtime.adapters import zhiting_price_task_outbox as outbox

    normalized.is_trusted_price_mapping = is_auto_price_mapping
    normalized.price_task_mapping_trust_basis = auto_price_mapping_trust_basis
    normalized.is_price_task_mapping_ready = auto_only_price_task_mapping_ready

    # The outbox imported the gate by value. Refresh that binding and remove
    # the legacy fail-open path for products without mapping governance fields.
    outbox.is_price_task_mapping_ready = auto_only_price_task_mapping_ready
    outbox._product_skip_reason = _auto_only_product_skip_reason

    _INSTALLED = True
