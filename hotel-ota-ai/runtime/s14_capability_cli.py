from __future__ import annotations

import argparse
import json
from typing import Any

from runtime.s14_operation_diagnosis import (
    S14RequestError,
    diagnose_s14_request,
    load_s14_request,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run S14 from aligned versioned capability results only."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--request-file",
        help="UTF-8 JSON request bundle conforming to S14 input_schema.json.",
    )
    source.add_argument(
        "--request-json",
        help="Inline JSON request bundle conforming to S14 input_schema.json.",
    )
    parser.add_argument(
        "--assert-hotel-id",
        help="Optional server-resolved exact hotel guard. Mismatch returns data_gap.",
    )
    parser.add_argument("--pretty", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    try:
        request = load_s14_request(
            request_json=args.request_json,
            request_file=args.request_file,
        )
    except S14RequestError as exc:
        return {
            "status": "data_gap",
            "skill_id": "S14",
            "reason": str(exc),
            "source_policy": "versioned_capability_results_only",
            "direct_business_table_read_allowed": False,
            "excel_source_allowed": False,
            "write_performed": False,
            "direct_execution_allowed": False,
            "live_allowed": False,
            "business_result_generated": False,
        }
    if args.assert_hotel_id and str(request.get("hotel_id")) != str(args.assert_hotel_id):
        return {
            "status": "data_gap",
            "skill_id": "S14",
            "reason": "server_resolved_hotel_mismatch",
            "requested_hotel_id": request.get("hotel_id"),
            "asserted_hotel_id": args.assert_hotel_id,
            "source_policy": "versioned_capability_results_only",
            "direct_business_table_read_allowed": False,
            "excel_source_allowed": False,
            "write_performed": False,
            "direct_execution_allowed": False,
            "live_allowed": False,
            "business_result_generated": False,
        }
    return diagnose_s14_request(request)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            sort_keys=bool(args.pretty),
        )
    )
    return 0 if result.get("status") in {"ok", "partial", "conflict", "data_gap"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
