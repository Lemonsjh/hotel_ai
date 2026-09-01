from __future__ import annotations

from runtime.s5_pipeline import install as _install_s5_pipeline


_install_s5_pipeline()

del _install_s5_pipeline

__all__ = [
    "run_context",
    "inventory",
    "demand_index",
    "conversion_funnel",
    "ota_health_score",
    "competitor_alert",
    "activity_decision",
    "roi_decision",
    "review_classifier",
    "data_gap_impact",
    "revenue_decision_engine",
]
