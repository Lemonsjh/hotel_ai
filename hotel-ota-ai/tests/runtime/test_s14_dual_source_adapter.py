from __future__ import annotations

import unittest

from runtime.adapters.s14_source_guard import guard_s14_direct_database_source
from runtime.s14_operation_diagnosis import (
    REQUIRED_CAPABILITY_IDS,
    diagnose_s14_excel_file,
    diagnose_s14_mysql_template_result,
    diagnose_s14_request,
)
from runtime.s14_bundle_builder import render_s14_feishu_text
from runtime.skill_orchestrator import run_skill_with_dependencies


CONTRACT_REVISION = "diagnosis-contract.v1"
POLICY_REVISION = "diagnosis-default.v1"


def capability_result(
    capability_id: str,
    *,
    status: str = "ok",
    hotel_id: str = "puyue",
    target_date: str = "2026-08-03",
    contract_revision: str = CONTRACT_REVISION,
    policy_revision: str = POLICY_REVISION,
    effective_window: object | None = None,
    deterministic_payload: dict | None = None,
    captured_at: str = "2026-08-03T14:00:00+08:00",
) -> dict:
    return {
        "capability_id": capability_id,
        "result_id": f"{capability_id.lower()}-result-1",
        "result_version": 1,
        "status": status,
        "organization_id": "org-puyue",
        "hotel_id": hotel_id,
        "target_business_date": target_date,
        "as_of_datetime": "2026-08-03T14:00:00+08:00",
        "effective_window": effective_window
        if effective_window is not None
        else {"type": "current", "start": target_date, "end": target_date},
        "captured_at": captured_at,
        "source_grain": ["hotel"],
        "source_units": {},
        "deterministic_payload": deterministic_payload or {},
        "evidence_refs": [f"sha256:{capability_id.lower()}-evidence"],
        "quality_flags": [],
        "contract_revision": contract_revision,
        "policy_revision": policy_revision,
    }


def request_bundle(results: list[dict], *, handoffs: list[dict] | None = None) -> dict:
    return {
        "organization_id": "org-puyue",
        "hotel_id": "puyue",
        "target_business_date": "2026-08-03",
        "as_of_datetime": "2026-08-03T14:30:00+08:00",
        "contract_revision": CONTRACT_REVISION,
        "policy_revision": POLICY_REVISION,
        "capability_results": results,
        "handoffs": handoffs or [],
    }


class TestS14CapabilityResultComposition(unittest.TestCase):
    def test_feishu_summary_deduplicates_root_cause_and_explains_scope(self) -> None:
        result = {
            "status": "conflict",
            "target_business_date": "2026-08-04",
            "as_of_datetime": "2026-08-04T20:23:23+08:00",
            "coverage_score": 1.0,
            "observed_health_score": 70.2,
            "top_items": [
                {"severity": "medium", "issue_code": "capability_status:S9:data_gap", "occurrence_count": 2},
                {"severity": "medium", "issue_code": "capability_status:S15:data_gap"},
                {"severity": "medium", "issue_code": "capability_status:S16:data_gap"},
                {"severity": "medium", "issue_code": "axis_source_conflict:sales_progress:baseline"},
            ],
            "data_limitations": ["capability_status:S9:data_gap"],
            "capability_collection_summary": {"ok_count": 6, "degraded_count": 4, "saved_count": 10, "generated_count": 0},
        }
        text = render_s14_feishu_text(result)

        self.assertIn("能力结果覆盖率：100%", text)
        self.assertIn("观测健康分：70.2", text)
        self.assertIn("S9 流量/转化数据缺失（合并 2 个同源问题）", text)
        self.assertIn("S15 销售基准线数据不足", text)
        self.assertIn("S16 当日销售进度暂不可判断", text)
        self.assertIn("销售进度基线来源不一致", text)
        self.assertIn("对后续决策的影响：", text)

    def test_complete_request_uses_only_versioned_results(self) -> None:
        results = [capability_result(capability_id) for capability_id in REQUIRED_CAPABILITY_IDS]
        output = diagnose_s14_request(request_bundle(results))

        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["source_policy"], "versioned_capability_results_only")
        self.assertFalse(output["direct_business_table_read_allowed"])
        self.assertFalse(output["excel_source_allowed"])
        self.assertEqual(output["capability_result_count"], 10)
        self.assertEqual(output["coverage_score"], 1.0)
        self.assertEqual(output["observed_health_score"], 100.0)
        self.assertEqual(len(output["modules"]), 8)
        self.assertEqual(len(output["decision_axes"]), 7)
        self.assertFalse(output["write_performed"])
        self.assertFalse(output["direct_execution_allowed"])
        self.assertFalse(output["live_allowed"])

    def test_missing_s10_degrades_only_related_module(self) -> None:
        results = [
            capability_result(capability_id)
            for capability_id in REQUIRED_CAPABILITY_IDS
            if capability_id != "S10"
        ]
        output = diagnose_s14_request(request_bundle(results))

        missing = [
            item
            for item in output["items"]
            if item["issue_code"] == "missing_input:S10"
        ]
        self.assertEqual({item["module_id"] for item in missing}, {"promotion_roi"})
        self.assertEqual(output["status"], "partial")
        promotion = next(
            module
            for module in output["modules"]
            if module["module_id"] == "promotion_roi"
        )
        self.assertTrue(promotion["observed"])
        self.assertEqual(output["coverage_score"], 1.0)

    def test_missing_s15_blocks_s16_item_without_relabeling_it(self) -> None:
        s16_payload = {
            "diagnostic_items": [
                {
                    "module_id": "operating_revenue",
                    "issue_code": "target_progress_lag",
                    "issue_type": "anomaly",
                    "severity": "high",
                    "status": "open",
                    "confidence": 0.9,
                    "impact": {
                        "metric": "target_progress_delta_pp",
                        "value": -18,
                        "unit": "pp",
                    },
                    "evidence_refs": ["sha256:s16-progress"],
                    "forbidden_conclusions": [
                        "do_not_attribute_to_price_or_traffic"
                    ],
                }
            ]
        }
        results = [
            capability_result(
                capability_id,
                deterministic_payload=s16_payload if capability_id == "S16" else None,
            )
            for capability_id in REQUIRED_CAPABILITY_IDS
            if capability_id != "S15"
        ]
        output = diagnose_s14_request(request_bundle(results))

        missing_s15 = next(
            item
            for item in output["items"]
            if item["issue_code"] == "missing_input:S15"
        )
        s16_item = next(
            item
            for item in output["items"]
            if item["issue_code"] == "target_progress_lag"
        )
        self.assertEqual(s16_item["blocked_by"], missing_s15["item_id"])
        self.assertEqual(s16_item["issue_code"], "target_progress_lag")
        self.assertIn(
            "do_not_attribute_to_price_or_traffic",
            s16_item["forbidden_conclusions"],
        )

    def test_different_natural_windows_are_allowed(self) -> None:
        windows = {
            "S2": {"type": "current_snapshot"},
            "S9": {"type": "rolling_30d"},
            "S10": {"type": "rolling_30d_effect"},
            "S12": {"type": "review_window"},
            "S15": {"type": "materialization"},
            "S16": {"type": "as_of_progress"},
        }
        results = [
            capability_result(
                capability_id,
                effective_window=windows.get(
                    capability_id, {"type": f"{capability_id.lower()}_window"}
                ),
            )
            for capability_id in REQUIRED_CAPABILITY_IDS
        ]
        output = diagnose_s14_request(request_bundle(results))

        self.assertEqual(output["status"], "ok")
        self.assertFalse(
            any(
                "snapshot" in item["issue_code"]
                and item["issue_type"] == "conflict"
                for item in output["items"]
            )
        )

    def test_other_hotel_result_is_rejected_not_used(self) -> None:
        results = [capability_result(capability_id) for capability_id in REQUIRED_CAPABILITY_IDS]
        results[0] = capability_result("S2", hotel_id="zhiting")
        output = diagnose_s14_request(request_bundle(results))

        self.assertEqual(output["status"], "conflict")
        issue = next(
            item
            for item in output["items"]
            if item["issue_code"].startswith("capability_alignment:S2:")
        )
        self.assertIn("hotel_mismatch", issue["conflicts"][0])
        self.assertEqual(output["capability_result_count"], 9)
        operating = next(
            module
            for module in output["modules"]
            if module["module_id"] == "operating_revenue"
        )
        price_inventory = next(
            module
            for module in output["modules"]
            if module["module_id"] == "price_inventory"
        )
        self.assertTrue(operating["observed"])
        self.assertTrue(price_inventory["observed"])

    def test_incompatible_contract_revision_is_rejected(self) -> None:
        results = [capability_result(capability_id) for capability_id in REQUIRED_CAPABILITY_IDS]
        results[4] = capability_result("S9", contract_revision="legacy-v27")
        output = diagnose_s14_request(request_bundle(results))

        issue = next(
            item
            for item in output["items"]
            if item["issue_code"].startswith("capability_alignment:S9:")
        )
        self.assertIn("contract_revision_incompatible", issue["conflicts"][0])
        self.assertEqual(output["status"], "conflict")

    def test_s14_does_not_compute_missing_axis_delta(self) -> None:
        s9_payload = {
            "decision_axes": {
                "browse_users": {
                    "actual": 1200,
                    "baseline": 1350,
                    "unit": "user",
                    "effective_window": "rolling_30d",
                }
            }
        }
        results = [
            capability_result(
                capability_id,
                deterministic_payload=s9_payload if capability_id == "S9" else None,
            )
            for capability_id in REQUIRED_CAPABILITY_IDS
        ]
        output = diagnose_s14_request(request_bundle(results))

        browse = next(
            axis for axis in output["decision_axes"] if axis["axis_id"] == "browse_users"
        )
        self.assertEqual(browse["actual"], 1200)
        self.assertEqual(browse["baseline"], 1350)
        self.assertIsNone(browse["delta"])
        self.assertIsNone(browse["gap"])

    def test_only_existing_exact_handoff_is_exposed(self) -> None:
        valid = {
            "capability_id": "S6",
            "handoff_ref": "result-ref:s6-1",
            "hotel_id": "puyue",
            "scope": {
                "room_type_id": "py03",
                "channel": "ctrip",
                "product_id": "p-1",
            },
            "target_business_date": "2026-08-03",
            "candidate_hash": "sha256:candidate",
            "display_text": "查看已有价格候选",
        }
        invalid = {
            **valid,
            "handoff_ref": "result-ref:s6-wrong-hotel",
            "hotel_id": "zhiting",
        }
        results = [capability_result(capability_id) for capability_id in REQUIRED_CAPABILITY_IDS]
        output = diagnose_s14_request(request_bundle(results, handoffs=[valid, invalid]))

        self.assertEqual(
            [handoff["handoff_ref"] for handoff in output["handoffs"]],
            ["result-ref:s6-1"],
        )
        self.assertTrue(
            any(
                item["issue_code"] == "invalid_handoff:S6"
                for item in output["items"]
            )
        )
        self.assertFalse(output["handoffs"][0]["direct_execution_allowed"])

    def test_legacy_excel_and_mysql_main_paths_fail_closed(self) -> None:
        excel = diagnose_s14_excel_file("/tmp/legacy.xlsx", hotel_id="puyue")
        mysql = diagnose_s14_mysql_template_result(
            {"status": "ok", "payload": {"occupancy": 0.8}},
            hotel_id="puyue",
        )
        for result in (excel, mysql):
            self.assertEqual(result["status"], "data_gap")
            self.assertEqual(
                result["blocked_reason"],
                "s14_direct_source_removed_use_versioned_capability_results",
            )
            self.assertFalse(result["direct_business_table_read_allowed"])
            self.assertFalse(result["business_result_generated"])

    def test_operation_diagnosis_database_template_is_blocked_before_query(self) -> None:
        calls: list[str] = []

        def original(template: str, hotel_id: str, **kwargs) -> dict:
            del hotel_id, kwargs
            calls.append(template)
            return {"status": "ok"}

        guarded = guard_s14_direct_database_source(original)
        blocked = guarded("operation_diagnosis", "puyue")
        normal = guarded("daily_metrics", "puyue")

        self.assertEqual(blocked["status"], "data_gap")
        self.assertEqual(
            blocked["blocked_reason"],
            "s14_direct_source_removed_use_versioned_capability_results",
        )
        self.assertEqual(calls, ["daily_metrics"])
        self.assertEqual(normal["status"], "ok")

    def test_s14_orchestrator_collects_all_dependencies(self) -> None:
        calls: list[str] = []

        def runner(skill: str, hotel_id: str, context: dict) -> dict:
            del hotel_id
            calls.append(skill)
            if skill == "S4_MARKET_CONTEXT":
                return {"status": "data_gap", "reason": "weather_missing"}
            if skill == "S14_OPERATION_DIAGNOSIS":
                return {
                    "status": "partial",
                    "dependency_result_count": len(
                        context.get("dependency_results") or {}
                    ),
                }
            return {"status": "ok"}

        output = run_skill_with_dependencies(
            target_skill="S14_OPERATION_DIAGNOSIS",
            hotel_id="puyue",
            runner=runner,
        )

        self.assertEqual(output["dependency_collection_policy"], "collect_all_and_degrade_modules")
        self.assertEqual(len(output["dependency_runs"]), 10)
        self.assertIn("S17_CUSTOMER_ORDER_ANALYSIS", calls)
        self.assertEqual(output["final_result"]["dependency_result_count"], 10)


if __name__ == "__main__":
    unittest.main()
