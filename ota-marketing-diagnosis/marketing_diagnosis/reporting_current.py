"""Stable report entry point for the consolidated runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from marketing_diagnosis import ctrip_reputation_report as _ctrip_reputation_report
from marketing_diagnosis import ctrip_flow_scoring_note as _ctrip_flow_scoring_note
from marketing_diagnosis import ctrip_psi_table_compact as _ctrip_psi_table_compact
from marketing_diagnosis import ctrip_rights_center_compact as _ctrip_rights_center_compact
from marketing_diagnosis.channel_score_totals import patch_channel_score_totals
from marketing_diagnosis.ctrip_manual_listing import patch_html
from marketing_diagnosis.meituan_exposure_monthly import patch_report_html
from marketing_diagnosis.reporting_runtime_v52 import (
    build_ctrip_html as _build_ctrip_html,
    build_dual_channel_html as _build_dual_channel_html,
    build_html as _build_html,
    build_markdown,
    build_meituan_html,
    write_reports as _write_reports,
)


def build_ctrip_html(result: dict[str, Any]) -> str:
    return patch_report_html(patch_html(patch_channel_score_totals(_build_ctrip_html(result), result), result))


def build_dual_channel_html(result: dict[str, Any]) -> str:
    return patch_report_html(patch_html(patch_channel_score_totals(_build_dual_channel_html(result), result), result))


def build_html(result: dict[str, Any]) -> str:
    return patch_report_html(patch_html(patch_channel_score_totals(_build_html(result), result), result))


def write_reports(result: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    paths = _write_reports(result, output_dir)
    report_path = Path(paths["report_html"])
    report_path.write_text(build_html(result), encoding="utf-8")
    return paths


__all__ = [
    "build_ctrip_html",
    "build_dual_channel_html",
    "build_html",
    "build_markdown",
    "build_meituan_html",
    "write_reports",
]
