"""Install the S5 pricing pipeline in one explicit, deterministic order."""

from __future__ import annotations


_INSTALLED = False


def install() -> None:
    """Apply S5 enrichments once, from source filtering through presentation."""

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.s5_activity_query_parallel_patch import install as activity_query_parallel
    from runtime.s5_evidence_contract_patch import install as evidence
    from runtime.s5_limited_preview_patch import install as limited_preview
    from runtime.s5_market_heat_contract_patch import install as market_heat
    from runtime.s5_no_price_guard_patch import install as no_price_bounds
    from runtime.s5_product_net_revenue_patch import install as net_revenue
    from runtime.s5_product_type_filter_patch import install as product_type
    from runtime.s5_room_inventory_filter_patch import install as inventory
    from runtime.s5_strong_pricing_rules_patch import install as strong_rules
    from runtime.s5_time_evidence_policy_patch import install as time_evidence

    product_type()
    inventory()
    strong_rules()
    limited_preview()
    evidence()
    time_evidence()
    net_revenue()
    activity_query_parallel()
    market_heat()
    no_price_bounds()
