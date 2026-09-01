from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from scripts.cleanup_reports import cleanup_reports


def make_run(root: Path, run_id: str, *, complete: bool = True) -> Path:
    run_dir = root / "puyue" / "multi" / "2026-07-01_2026-07-30" / run_id
    run_dir.mkdir(parents=True)
    if complete:
        (run_dir / "report.html").write_text("report", encoding="utf-8")
    return run_dir


def test_dry_run_reports_old_directory_without_deleting(tmp_path, capsys):
    root = tmp_path / "reports"
    old = make_run(root, "20260710-010000")

    summary = cleanup_reports(root, 7, now=datetime(2026, 7, 23, 2), apply=False)

    assert old.is_dir()
    assert summary["matched"] == 1
    assert summary["removed"] == 0
    assert '"action": "would_delete"' in capsys.readouterr().out


def test_apply_deletes_only_runs_older_than_seven_days(tmp_path):
    root = tmp_path / "reports"
    old = make_run(root, "20260715-010000")
    boundary = make_run(root, "20260716-020000")
    recent = make_run(root, "20260722-010000")

    summary = cleanup_reports(root, 7, now=datetime(2026, 7, 23, 2), apply=True)

    assert not old.exists()
    assert boundary.is_dir()
    assert recent.is_dir()
    assert summary["removed"] == 1


def test_incomplete_and_unrecognized_directories_are_not_deleted(tmp_path):
    root = tmp_path / "reports"
    incomplete = make_run(root, "20260710-010000", complete=False)
    unrecognized = root / "puyue" / "multi" / "not-a-period" / "20260710-010000"
    unrecognized.mkdir(parents=True)
    (unrecognized / "report.html").write_text("report", encoding="utf-8")

    summary = cleanup_reports(root, 7, now=datetime(2026, 7, 23, 2), apply=True)

    assert incomplete.is_dir()
    assert unrecognized.is_dir()
    assert summary["skipped_incomplete"] == 1


def test_include_incomplete_deletes_only_structurally_valid_expired_run(tmp_path):
    root = tmp_path / "reports"
    incomplete = make_run(root, "20260710-010000", complete=False)
    unrecognized = root / "puyue" / "multi" / "not-a-period" / "20260710-010000"
    unrecognized.mkdir(parents=True)

    summary = cleanup_reports(
        root,
        7,
        now=datetime(2026, 7, 23, 2),
        apply=True,
        include_incomplete=True,
    )

    assert not incomplete.exists()
    assert unrecognized.is_dir()
    assert summary["removed"] == 1
    assert summary["removed_incomplete"] == 1


@pytest.mark.parametrize("unsafe", ["/", "/var", "/var/lib", "/tmp"])
def test_broad_roots_are_rejected(unsafe):
    with pytest.raises(ValueError, match="unsafe report root"):
        cleanup_reports(unsafe, 7)


def test_retention_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        cleanup_reports(tmp_path / "reports", 0)
