from __future__ import annotations

from importlib import import_module


def test_feishu_runtime_uses_final_ctrip_flow_rule_pipeline():
    """Feishu reports must use the same final scoring entry as direct reports."""

    runtime = import_module("skills.s14-operation-diagnosis.runtime")
    flow_rules = import_module("marketing_diagnosis.ctrip_flow_rules")

    assert runtime.process is flow_rules.process


def test_feishu_runtime_uses_final_ctrip_database_loader():
    """Feishu must load every Ctrip section used by the direct report path."""

    runtime = import_module("skills.s14-operation-diagnosis.runtime")
    ctrip_flow = import_module("marketing_diagnosis.ctrip_flow")

    assert runtime.load_mysql_dsn_dataset is ctrip_flow.load_mysql_dsn_dataset


def test_feishu_runtime_passes_requested_hotel_context_to_final_rules(monkeypatch, tmp_path):
    runtime = import_module("skills.s14-operation-diagnosis.runtime")
    captured = {}

    monkeypatch.setenv("S14_DB_DSN", "mysql://test.invalid/database")
    monkeypatch.setattr(runtime, "load_mysql_dsn_dataset", lambda *args, **kwargs: {})
    monkeypatch.setattr(runtime, "normalize_dataset", lambda raw: {"sections": {}})

    def fake_process(normalized):
        captured.update(normalized)
        return {"visual_diagnosis": {"items": []}}

    monkeypatch.setattr(runtime, "process", fake_process)
    monkeypatch.setattr(
        runtime,
        "write_reports",
        lambda result, report_dir: {
            "report_html": str(report_dir / "report.html"),
            "report_json": str(report_dir / "report.json"),
            "report_markdown": str(report_dir / "report.md"),
        },
    )

    runtime.S14OperationDiagnosis().execute(
        {
            "data_source_mode": "database",
            "hotel_id": "zhiting",
            "hotel_name": "贵阳智町·栖筑优品酒店(紫林庵站妇幼保健院店)",
            "period_start": "2026-06-24",
            "period_end": "2026-07-23",
            "output_root": str(tmp_path),
        }
    )

    assert captured["hotel_id"] == "zhiting"
    assert captured["hotel_name"] == "贵阳智町·栖筑优品酒店(紫林庵站妇幼保健院店)"
    assert captured["platform"] == "multi"


def test_feishu_runtime_keeps_strict_competition_rank_formula():
    flow_rules = import_module("marketing_diagnosis.ctrip_flow_rank_rules")

    # 5th of 20 => 1 - (5 - 1) / 20 = 80%, which receives 100%.
    assert flow_rules._rank_level(1 - (5 - 1) / 20) == 1.0
    # 9th of 20 => 60%, which receives 80%.
    assert flow_rules._rank_level(1 - (9 - 1) / 20) == 0.8
    # 13th of 20 => 40%, which receives 60%.
    assert flow_rules._rank_level(1 - (13 - 1) / 20) == 0.6
    # 14th of 20 => 35%, which receives 0%.
    assert flow_rules._rank_level(1 - (14 - 1) / 20) == 0.0
