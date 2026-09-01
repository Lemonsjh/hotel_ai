#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_REPORT_ROOT = Path("/var/lib/ota-marketing-diagnosis/reports")
RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}$")
PERIOD_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}$")
REPORT_FILENAMES = {"report.html", "report.json", "report.md"}


def _event(action: str, path: Path, generated_at: datetime | None = None) -> None:
    payload = {"action": action, "path": str(path)}
    if generated_at is not None:
        payload["generated_at"] = generated_at.isoformat(timespec="seconds")
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _safe_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    forbidden = {Path("/"), Path("/var"), Path("/var/lib"), Path("/tmp")}
    if root in forbidden or root.name not in {"reports", "s14-reports"}:
        raise ValueError(f"unsafe report root: {root}")
    return root


def _generated_at(run_dir: Path) -> datetime | None:
    if not RUN_ID_PATTERN.fullmatch(run_dir.name):
        return None
    try:
        return datetime.strptime(run_dir.name, "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def _candidate_run_dirs(root: Path):
    if not root.is_dir():
        return
    for hotel_dir in root.iterdir():
        if not hotel_dir.is_dir() or hotel_dir.is_symlink():
            continue
        for platform_dir in hotel_dir.iterdir():
            if not platform_dir.is_dir() or platform_dir.is_symlink():
                continue
            for period_dir in platform_dir.iterdir():
                if (
                    not period_dir.is_dir()
                    or period_dir.is_symlink()
                    or not PERIOD_PATTERN.fullmatch(period_dir.name)
                ):
                    continue
                for run_dir in period_dir.iterdir():
                    if not run_dir.is_dir() or run_dir.is_symlink():
                        continue
                    generated_at = _generated_at(run_dir)
                    if generated_at is None:
                        continue
                    yield run_dir, generated_at


def cleanup_reports(
    root_value: str | Path,
    retention_days: int,
    *,
    apply: bool = False,
    include_incomplete: bool = False,
    now: datetime | None = None,
) -> dict[str, int | str | bool]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    root = _safe_root(root_value)
    current_time = now or datetime.now()
    cutoff = current_time - timedelta(days=retention_days)
    matched = 0
    removed = 0
    removed_incomplete = 0
    skipped_incomplete = 0

    for run_dir, generated_at in _candidate_run_dirs(root):
        if generated_at >= cutoff:
            continue
        matched += 1
        artifacts = {path.name for path in run_dir.iterdir() if path.is_file()}
        incomplete = not artifacts.intersection(REPORT_FILENAMES)
        if incomplete and not include_incomplete:
            skipped_incomplete += 1
            _event("skip_incomplete", run_dir, generated_at)
            continue
        if apply:
            shutil.rmtree(run_dir)
            removed += 1
            if incomplete:
                removed_incomplete += 1
            _event("deleted_incomplete" if incomplete else "deleted", run_dir, generated_at)
            period_dir = run_dir.parent
            if period_dir.is_dir() and not any(period_dir.iterdir()):
                period_dir.rmdir()
        else:
            _event("would_delete", run_dir, generated_at)

    summary = {
        "root": str(root),
        "retention_days": retention_days,
        "apply": apply,
        "matched": matched,
        "removed": removed,
        "removed_incomplete": removed_incomplete,
        "skipped_incomplete": skipped_incomplete,
    }
    print(json.dumps({"summary": summary}, ensure_ascii=False), flush=True)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Delete generated S14 report runs older than the retention window.")
    parser.add_argument(
        "--root",
        default=os.environ.get("S14_REPORT_OUTPUT_DIR") or str(DEFAULT_REPORT_ROOT),
    )
    parser.add_argument("--retention-days", type=int, default=7)
    parser.add_argument("--apply", action="store_true", help="Delete matched report runs. Default is dry-run.")
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="Also delete structurally valid expired run directories without report artifacts.",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cleanup_reports(
        args.root,
        args.retention_days,
        apply=args.apply,
        include_incomplete=args.include_incomplete,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
