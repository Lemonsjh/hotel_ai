from __future__ import annotations

from typing import Any

from marketing_diagnosis.rule_catalog import CAP_RULES


SEVERITY_ZH = {"high": "高", "medium": "中", "low": "低", "高": "高", "中": "中", "低": "低"}


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
        return None if number != number else number
    except (TypeError, ValueError):
        return None


def _missing_count(data_quality: dict[str, Any]) -> int:
    return sum(len(v or []) for v in (data_quality.get("missing_fields") or {}).values())


def _cap_meta(cap_id: str) -> dict[str, Any]:
    for item in CAP_RULES:
        if item["cap_id"] == cap_id:
            return item
    return {"cap_id": cap_id, "name": cap_id, "cap_score": 100, "severity": "低", "description": ""}


def _trigger(cap_id: str, evidence: str) -> dict[str, Any]:
    item = dict(_cap_meta(cap_id))
    item["severity"] = SEVERITY_ZH.get(str(item.get("severity") or "low"), str(item.get("severity") or "低"))
    item["evidence"] = evidence
    return item


def evaluate_caps(result: dict[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") or {}
    op = metrics.get("operating") or {}
    funnel = metrics.get("ota_funnel") or {}
    promo = metrics.get("promotion") or {}
    rep = metrics.get("reputation") or {}
    data_quality = result.get("data_quality") or {}
    module_scores = result.get("module_scores") or []

    raw_score = _num(result.get("score_before_cap"))
    if raw_score is None:
        raw_score = _num(result.get("final_score")) or 0.0

    revpar = _num(op.get("revpar"))
    occ = _num(op.get("occupancy_rate"))
    conv = _num(funnel.get("payment_conversion_rate"))
    orders = _num(funnel.get("paid_orders"))
    review_count = _num(rep.get("review_count"))
    rating = _num(rep.get("rating_avg"))
    missing = _missing_count(data_quality)
    empty_sections = data_quality.get("empty_sections") or {}
    monthly = op.get("monthly_trend") or []

    triggered: list[dict[str, Any]] = []
    if revpar is not None and revpar < 80:
        triggered.append(_trigger("C01", f"RevPAR={revpar:.2f} < 80"))

    latest = monthly[-1] if monthly else {}
    if (_num(latest.get("revenue_mom")) is not None and (_num(latest.get("revenue_mom")) or 0) < -0.08) or (_num(latest.get("revpar_mom")) is not None and (_num(latest.get("revpar_mom")) or 0) < -0.08):
        triggered.append(_trigger("C02", f"最近月收入环比={latest.get('revenue_mom')}，RevPAR环比={latest.get('revpar_mom')}"))

    if conv is not None and conv < 0.04 and (orders or 0) < 10:
        triggered.append(_trigger("C03", f"支付转化率={conv:.4f}，支付订单={orders or 0}"))

    if promo.get("status") == "partial" and not promo.get("has_cost_roi_fields"):
        triggered.append(_trigger("C04", "已有活动覆盖，但推广花费/点击/订单金额/ROI字段未接入"))

    if missing >= 5 or len(empty_sections) >= 3:
        triggered.append(_trigger("C05", f"缺失字段数={missing}，空模块数={len(empty_sections)}"))

    high_foundation = False
    for item in module_scores:
        if item.get("module_id") in {"M06", "M07", "M08"} and (_num(item.get("rate")) or 0) >= 0.75:
            high_foundation = True
    if high_foundation and ((occ is not None and occ < 0.65) or (revpar is not None and revpar < 90) or ((orders or 0) < 10 and conv is not None and conv < 0.05)):
        triggered.append(_trigger("C06", f"基础项较高但经营指标弱：出租率={occ}，RevPAR={revpar}，订单={orders}，转化={conv}"))

    if rating is not None and rating >= 4.8 and review_count is not None and review_count < 10:
        triggered.append(_trigger("C07", f"评分={rating:.2f}，评价数={review_count:.0f}"))

    cap_score = min([_num(item.get("cap_score")) or 100 for item in triggered], default=100)
    capped_score = min(raw_score, cap_score)
    return {
        "score_before_cap": round(raw_score, 2),
        "cap_score": round(cap_score, 2),
        "final_score": round(capped_score, 2),
        "cap_applied": capped_score < raw_score,
        "cap_rules_triggered": triggered,
    }


def apply_score_caps(result: dict[str, Any]) -> dict[str, Any]:
    cap_result = evaluate_caps(result)
    updated = {**result, **cap_result}
    return updated
