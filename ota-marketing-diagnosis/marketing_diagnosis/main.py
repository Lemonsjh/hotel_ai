from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from marketing_diagnosis.latest import (
    load_database_dataset,
    load_excel_package,
    load_mysql_dsn_dataset,
    normalize_dataset,
    process,
    write_reports,
)
from marketing_diagnosis.runtime_env import load_local_s14_env

load_local_s14_env()

DEFAULT_REPORT_ROOT = Path("/var/lib/ota-marketing-diagnosis/reports")


def _safe_segment(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-._") or fallback


def _report_dir(output_root: str, hotel_id: str, platform: str, period_start: str, period_end: str) -> Path:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    period = f"{_safe_segment(period_start, 'start')}_{_safe_segment(period_end, 'end')}"
    return Path(output_root) / _safe_segment(hotel_id, "hotel") / _safe_segment(platform, "multi") / period / run_id


def _period(args) -> tuple[str, str]:
    end = args.period_end or str(datetime.now().date())
    start = args.period_start or str(datetime.now().date() - timedelta(days=29))
    return start, end


def _run(raw_dataset, args):
    normalized = normalize_dataset(raw_dataset)
    normalized["hotel_name"] = args.hotel_name
    normalized["hotel_id"] = args.hotel_id
    normalized["platform"] = args.platform
    result = process(normalized)
    period_start, period_end = _period(args)
    report_dir = _report_dir(args.output, args.hotel_id, args.platform, period_start, period_end)
    enriched = {
        **result,
        "run_id": report_dir.name,
        "hotel_id": args.hotel_id,
        "hotel_name": args.hotel_name,
        "platform": args.platform,
        "period_start": period_start,
        "period_end": period_end,
        "report_dir": str(report_dir),
    }
    paths = write_reports(enriched, report_dir)
    return {**enriched, **paths}


def command_excel(args):
    raw_dataset, meta = load_excel_package(
        args.excel,
        period_start=args.period_start or None,
        period_end=args.period_end or None,
    )
    if meta.get("hotel_id"):
        args.hotel_id = meta["hotel_id"]
    if meta.get("hotel_name"):
        args.hotel_name = meta["hotel_name"]
    if meta.get("platform"):
        args.platform = meta["platform"]
    if not args.period_start and meta.get("period_start"):
        args.period_start = meta["period_start"]
    if not args.period_end and meta.get("period_end"):
        args.period_end = meta["period_end"]
    print(json.dumps(_run(raw_dataset, args), ensure_ascii=False, indent=2, default=str))


def command_config(args):
    raw_dataset = load_database_dataset(args.config)
    print(json.dumps(_run(raw_dataset, args), ensure_ascii=False, indent=2, default=str))


def command_db(args):
    source = args.dsn or os.environ.get(args.dsn_env)
    if not source:
        raise SystemExit(f"missing database source: pass --dsn or set {args.dsn_env}")
    period_start, period_end = _period(args)
    raw_dataset = load_mysql_dsn_dataset(
        source,
        limit=args.limit,
        hotel_id=args.hotel_id,
        ctrip_hotel_id=args.ctrip_hotel_id,
        platform=args.platform,
        period_start=period_start,
        period_end=period_end,
    )
    print(json.dumps(_run(raw_dataset, args), ensure_ascii=False, indent=2, default=str))


def _add_common_args(parser):
    parser.add_argument("--output", default=os.environ.get("S14_REPORT_OUTPUT_DIR") or str(DEFAULT_REPORT_ROOT), help="Report root directory. Each run writes to hotel/platform/period/run_id under this root.")
    parser.add_argument("--hotel-id", default="puyue")
    parser.add_argument("--ctrip-hotel-id", default=os.environ.get("S14_CTRIP_HOTEL_ID") or None)
    parser.add_argument("--hotel-name", default="璞悦")
    parser.add_argument("--platform", default="multi")
    parser.add_argument("--period-start", default="")
    parser.add_argument("--period-end", default="")


def build_parser():
    parser = argparse.ArgumentParser(description="Independent OTA marketing report tool")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("diagnose-excel")
    p.add_argument("--excel", required=True)
    _add_common_args(p)
    p.set_defaults(func=command_excel)
    p = sub.add_parser("diagnose-config")
    p.add_argument("--config", required=True)
    _add_common_args(p)
    p.set_defaults(func=command_config)
    p = sub.add_parser("diagnose-db")
    p.add_argument("--dsn", required=False)
    p.add_argument("--dsn-env", default="S14_DB_DSN")
    p.add_argument("--limit", type=int, default=5000)
    _add_common_args(p)
    p.set_defaults(func=command_db)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
