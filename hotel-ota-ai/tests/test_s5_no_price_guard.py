from __future__ import annotations

from runtime.s5_no_price_guard_patch import (
    SINGLE_CHANGE_HARD_CAP,
    _decision_ref_without_guard,
    _no_price_guard_policy,
    _product_evidence_without_guard,
    _render_without_guard,
    scrub_candidate_guard_references,
    scrub_s5_result_guard_references,
)
import runtime.s5_no_price_guard_patch as no_guard


def test_neutral_resolver_has_no_configured_price_bounds() -> None:
    policy = _no_price_guard_policy()

    assert policy["source"] == "s5_no_price_guard"
    assert policy["floor_price"] is None
    assert policy["ceiling_price"] is None
    assert policy["max_increase_pct"] == SINGLE_CHANGE_HARD_CAP
    assert policy["max_decrease_pct"] == SINGLE_CHANGE_HARD_CAP


def test_product_evidence_replaces_guard_with_algorithm_cap(
    monkeypatch,
) -> None:
    def original(*args, **kwargs):
        return {
            "product_sellable": True,
            "mapping_valid": True,
            "guard_valid": False,
            "configured_price_floor": 500,
            "configured_price_ceiling": 428,
            "effective_price_floor": 500,
            "effective_price_ceiling": 428,
            "price_ratio_vs_avg": 1.5,
            "price_high": True,
            "same_ota_product_history_available": False,
            "estimated_activity_net_price": 196.42,
            "raise_net_revenue_ceiling": 200.00,
        }

    monkeypatch.setattr(no_guard, "_ORIGINAL_PRODUCT_EVIDENCE", original)
    evidence = _product_evidence_without_guard(
        {
            "current_price": 525,
            "price_guard_source": "active_price_guard_policy",
        },
        {},
        {},
        {},
        {"single_change_hard_cap": 0.10},
    )

    assert evidence["configured_price_floor"] is None
    assert evidence["configured_price_ceiling"] is None
    assert evidence["effective_price_floor"] == 0.0
    assert evidence["effective_price_ceiling"] == 577.5
    assert evidence["guard_valid"] is True
    assert evidence["product_healthy"] is True
    assert evidence["raise_price_has_headroom"] is True
    assert evidence["price_guard_applied"] is False
    assert evidence["pricing_bound_source"] == (
        "algorithm_single_change_hard_cap_only"
    )


def test_algorithm_cap_cannot_exceed_ten_percent(monkeypatch) -> None:
    monkeypatch.setattr(
        no_guard,
        "_ORIGINAL_PRODUCT_EVIDENCE",
        lambda *args, **kwargs: {
            "product_sellable": True,
            "mapping_valid": True,
            "same_ota_product_history_available": True,
        },
    )
    evidence = _product_evidence_without_guard(
        {"current_price": 100},
        {},
        {},
        {},
        {"single_change_hard_cap": 0.30},
    )

    assert evidence["effective_price_ceiling"] == 110.0
    assert evidence["algorithm_single_change_hard_cap"] == 0.10


def test_scrub_removes_guard_fields_blockers_and_quality_flags() -> None:
    result = scrub_s5_result_guard_references(
        {
            "price_guard_statuses": [{"source": "active"}],
            "quality_flags": ["default_guard_preview_only", "other"],
            "candidates": [
                {
                    "current_price": 525,
                    "price_guard_source": "active_price_guard_policy",
                    "configured_floor_price": 285,
                    "configured_ceiling_price": 428,
                    "floor_price": 285,
                    "ceiling_price": 428,
                    "guard_valid": False,
                    "eligibility": "preview_only_default_guard",
                    "blocked_reason": (
                        "active_price_guard_policy_required_before_s6"
                    ),
                    "limited_preview_blockers": [
                        "price_guard_invalid",
                        "no_raise_price_headroom",
                        "market_not_cold_evidence_missing",
                    ],
                    "reason_codes": [
                        "mapping_and_guard_valid",
                        "market_not_cold",
                    ],
                    "quality_flags": [
                        "default_guard_preview_only",
                        "exact_product_competitor_price_unavailable",
                    ],
                }
            ],
        }
    )

    assert "price_guard_statuses" not in result
    assert result["quality_flags"] == ["other"]
    candidate = result["candidates"][0]
    assert "price_guard_source" not in candidate
    assert "configured_floor_price" not in candidate
    assert "configured_ceiling_price" not in candidate
    assert "floor_price" not in candidate
    assert "ceiling_price" not in candidate
    assert candidate["eligibility"] == (
        "preview_only_strong_rule_not_satisfied"
    )
    assert candidate["blocked_reason"] == (
        "strong_pricing_rule_not_satisfied"
    )
    assert candidate["limited_preview_blockers"] == [
        "market_not_cold_evidence_missing"
    ]
    assert candidate["reason_codes"] == ["market_not_cold"]
    assert candidate["quality_flags"] == [
        "exact_product_competitor_price_unavailable"
    ]


def test_decision_ref_contains_no_guard_or_floor_ceiling_fields() -> None:
    candidate = {
        "room_type_id": "r1",
        "channel": "meituan",
        "ota_product_id": "p1",
        "current_price": 500,
        "candidate_price": 525,
        "execution_price": 525,
        "price_guard_policy_id": "guard-1",
        "floor_price": 300,
        "ceiling_price": 500,
    }
    _decision_ref_without_guard(
        candidate,
        result={
            "hotel_id": "h1",
            "target_stay_date": "2026-08-06",
            "freshness_status": "fresh",
        },
    )

    decision = candidate["decision_ref"]
    assert decision["single_change_hard_cap"] == SINGLE_CHANGE_HARD_CAP
    assert not any("guard" in key for key in decision)
    assert "floor_price" not in decision
    assert "ceiling_price" not in decision


def test_renderer_removes_guard_line_and_guard_wording() -> None:
    seen: dict[str, object] = {}

    def previous(cleaned: dict[str, object]) -> str:
        seen.update(cleaned)
        return "\n".join(
            [
                "S5 收益候选（真实数据只读）",
                "- 护栏：default_policy，配置底/顶价 ¥-/¥-。",
                "- 预计酒店收入不会替代商品原卖价参与调价写入、价格护栏或审批。",
            ]
        )

    text = _render_without_guard(
        previous,
        {
            "price_guard_statuses": [],
            "candidates": [
                {
                    "price_guard_source": "default_policy",
                    "quality_flags": ["default_guard_preview_only"],
                }
            ],
        },
    )

    assert "护栏" not in text
    assert "参与调价写入或审批" in text
    assert "price_guard_statuses" not in seen
    assert "price_guard_source" not in seen["candidates"][0]


def test_scrub_candidate_is_idempotent() -> None:
    candidate = {
        "price_guard_source": "default_policy",
        "quality_flags": ["default_guard_preview_only", "other"],
    }

    once = scrub_candidate_guard_references(candidate)
    twice = scrub_candidate_guard_references(once)

    assert once == twice
