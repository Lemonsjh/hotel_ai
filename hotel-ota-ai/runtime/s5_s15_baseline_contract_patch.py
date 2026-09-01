from __future__ import annotations

from typing import Any, Mapping

_INSTALLED = False
VERSION = "s5-s15-baseline-contract.v2"
_LOW_MATURITY = {"trend_only", "weak"}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _payload(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    nested = result.get("baseline")
    return dict(nested) if isinstance(nested, Mapping) else dict(result)


def inspect_s15_evidence(
    baseline_result: Mapping[str, Any] | None,
    *,
    target_stay_date: str,
) -> dict[str, Any]:
    payload = _payload(baseline_result)
    status_ok = bool(
        isinstance(baseline_result, Mapping)
        and baseline_result.get("status") == "ok"
    )
    baseline_date = str(
        payload.get("business_date")
        or payload.get("data_business_date")
        or payload.get("target_date")
        or ""
    )[:10]
    hotel = payload.get("hotel") or {}
    target_room_nights = _first_number(
        payload.get("target_room_nights"),
        payload.get("daily_target_room_nights"),
        hotel.get("effective_target_room_nights"),
    )
    policy = payload.get("hourly_curve_policy") or {}
    health = hotel.get("baseline_health") or {}
    maturity = str(health.get("object_maturity") or "unavailable")
    confidences = [
        _number(hotel.get("capacity_series_confidence")),
        _number(hotel.get("target_series_confidence")),
    ]
    known_confidences = [value for value in confidences if value is not None]
    minimum_confidence = min(known_confidences) if known_confidences else None
    final_target_available = bool(
        status_ok
        and baseline_date == str(target_stay_date)[:10]
        and target_room_nights is not None
    )
    hourly_contract_available = bool(
        final_target_available
        and policy.get("s16_deviation_allowed") is not False
    )
    hourly_evidence_qualified = bool(
        hourly_contract_available
        and maturity not in _LOW_MATURITY
        and (minimum_confidence is None or minimum_confidence >= 0.60)
    )
    warning_code = None
    warning_text = None
    if final_target_available and hourly_contract_available and not hourly_evidence_qualified:
        if maturity in _LOW_MATURITY:
            warning_code = f"s15_hourly_evidence_maturity_{maturity}"
        else:
            warning_code = "s15_hourly_evidence_confidence_low"
        warning_text = (
            "已取得 S15 最终销售参考，但历史分时采集覆盖较少，"
            "当前节点偏差仅作趋势参考。"
        )
    return {
        "payload": payload,
        "final_target_available": final_target_available,
        "target_room_nights": target_room_nights,
        "hourly_contract_available": hourly_contract_available,
        "hourly_evidence_maturity": maturity,
        "hourly_evidence_min_confidence": minimum_confidence,
        "hourly_evidence_qualified": hourly_evidence_qualified,
        "warning_code": warning_code,
        "warning_text": warning_text,
    }


def _clean_false_missing_flags(flags: Any) -> list[str]:
    return [
        str(flag)
        for flag in (flags or [])
        if str(flag) != "missing_s15_sales_baseline"
        and not str(flag).startswith("source_missing:s15:s15_baseline_maturity_")
        and str(flag) != "source_missing:s15:s15_baseline_confidence_low"
    ]


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.algorithms import s5_real_candidates as s5_module

    previous_s15_baseline = s5_module._s15_baseline
    if not getattr(previous_s15_baseline, "_S5_S15_CONTRACT_V2", False):

        def s15_baseline(
            baseline_result: dict[str, Any] | None,
            *,
            target_stay_date: str,
        ) -> tuple[dict[str, Any], bool, str | None]:
            payload, available, reason = previous_s15_baseline(
                baseline_result,
                target_stay_date=target_stay_date,
            )
            evidence = inspect_s15_evidence(
                baseline_result,
                target_stay_date=target_stay_date,
            )
            if (
                not available
                and evidence["final_target_available"]
                and evidence["hourly_contract_available"]
                and reason
                in {
                    "s15_baseline_maturity_trend_only",
                    "s15_baseline_maturity_weak",
                    "s15_baseline_confidence_low",
                }
            ):
                return payload, True, None
            return payload, available, reason

        s15_baseline._S5_S15_CONTRACT_V2 = True  # type: ignore[attr-defined]
        s5_module._s15_baseline = s15_baseline

    previous_build = s5_module.build_s5_real_candidates
    if not getattr(previous_build, "_S5_S15_CONTRACT_V2", False):

        def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = dict(previous_build(*args, **kwargs))
            target_stay_date = str(
                kwargs.get("target_stay_date")
                or result.get("target_stay_date")
                or ""
            )[:10]
            evidence = inspect_s15_evidence(
                kwargs.get("s15_result"),
                target_stay_date=target_stay_date,
            )
            result.update(
                {
                    "s15_baseline_available": evidence[
                        "final_target_available"
                    ],
                    "s15_final_target_available": evidence[
                        "final_target_available"
                    ],
                    "s15_final_target_room_nights": evidence[
                        "target_room_nights"
                    ],
                    "s15_hourly_evidence_maturity": evidence[
                        "hourly_evidence_maturity"
                    ],
                    "s15_hourly_evidence_qualified": evidence[
                        "hourly_evidence_qualified"
                    ],
                    "s15_quality_warning": evidence["warning_text"],
                    "s15_evidence_summary": evidence["warning_text"],
                    "s15_contract_version": VERSION,
                }
            )
            if evidence["final_target_available"]:
                result["s15_status"] = "ok"
                result["s15_blocked_reason"] = None
                result["quality_flags"] = _clean_false_missing_flags(
                    result.get("quality_flags")
                )
                for candidate in result.get("candidates") or []:
                    candidate["quality_flags"] = _clean_false_missing_flags(
                        candidate.get("quality_flags")
                    )
                    candidate["s15_final_target_available"] = True
                    candidate["s15_hourly_evidence_maturity"] = evidence[
                        "hourly_evidence_maturity"
                    ]
                    candidate["s15_hourly_evidence_qualified"] = evidence[
                        "hourly_evidence_qualified"
                    ]
                    candidate["s15_hourly_evidence_note"] = evidence[
                        "warning_text"
                    ]
                    if evidence["warning_text"]:
                        candidate["candidate_strength"] = "partial"
            return result

        build_s5_real_candidates._S5_S15_CONTRACT_V2 = True  # type: ignore[attr-defined]
        s5_module.build_s5_real_candidates = build_s5_real_candidates

        try:
            from runtime import feishu_command_router

            feishu_command_router.build_s5_real_candidates = (
                build_s5_real_candidates
            )
        except Exception:
            pass

    from runtime.algorithms import s5_real_reply as reply_module

    previous_render = reply_module.render_s5_real_reply
    if not getattr(previous_render, "_S5_S15_CONTRACT_V2", False):

        def render_s5_real_reply(result: dict[str, Any]) -> str:
            text = previous_render(result)
            warning = str(result.get("s15_quality_warning") or "").strip()
            if not warning:
                return text
            lines = text.splitlines()
            insert_at = next(
                (
                    index + 1
                    for index, value in enumerate(lines)
                    if value.strip() == "边界"
                ),
                len(lines),
            )
            lines.insert(insert_at, f"- 证据说明：S15 {warning}")
            return "\n".join(lines)

        render_s5_real_reply._S5_S15_CONTRACT_V2 = True  # type: ignore[attr-defined]
        reply_module.render_s5_real_reply = render_s5_real_reply

        try:
            from runtime import feishu_output_renderer

            feishu_output_renderer.render_s5_real_reply = render_s5_real_reply
        except Exception:
            pass
