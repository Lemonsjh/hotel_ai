from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from runtime.s13.contracts import RequestContext
from runtime.s13.repository import S13ControlRepository
from runtime.s13.service import S13Service
from runtime.s13.source import MemoryReviewSourceRepository, MySQLReviewSourceRepository, SourceDataGap
from runtime.s13.task_outbox import (
    MySQLReviewTaskOutbox,
    SQLiteReviewTaskOutbox,
    TaskDataGap,
    UnavailableReviewTaskOutbox,
)


S13_COMMANDS = {
    "review-reply-list",
    "review-reply-draft",
    "review-reply-preview",
    "review-reply-confirm",
    "review-reply-reject",
    "review-reply-cancel",
    "review-reply-status",
    "review-reply-retry",
}


def _add_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hotel-id", required=True)
    parser.add_argument("--principal-role", required=True, choices=["admin", "owner", "operator", "frontdesk", "viewer"])
    parser.add_argument("--principal-ref", required=True)
    parser.add_argument("--as-of", dest="as_of_datetime", required=True)


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-fixture")
    parser.add_argument("--source-dsn")
    parser.add_argument("--task-sqlite")
    parser.add_argument("--task-dsn")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hotel-ota-s13")
    parser.add_argument("--db", default=os.environ.get("HOTEL_OTA_DB", "data/runtime.sqlite"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("review-reply-list")
    _add_context_args(p)
    _add_source_args(p)
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("review-reply-draft")
    _add_context_args(p)
    _add_source_args(p)
    p.add_argument("--review-ref", required=True)

    p = sub.add_parser("review-reply-preview")
    _add_context_args(p)
    _add_source_args(p)
    p.add_argument("--review-ref", required=True)
    p.add_argument("--reply-file", required=True)

    for command in ("review-reply-confirm", "review-reply-reject", "review-reply-cancel", "review-reply-retry"):
        p = sub.add_parser(command)
        _add_context_args(p)
        _add_source_args(p)
        p.add_argument("--request-id", required=True)

    p = sub.add_parser("review-reply-status")
    _add_context_args(p)
    _add_source_args(p)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--request-id")
    group.add_argument("--review-ref")
    return parser


def _source_repository(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    if args.source_fixture:
        return MemoryReviewSourceRepository.from_json_file(args.source_fixture)
    return MySQLReviewSourceRepository.from_env(args.source_dsn, hotel_id=args.hotel_id)


def _task_outbox(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    if args.task_sqlite:
        return SQLiteReviewTaskOutbox(args.task_sqlite)
    try:
        return MySQLReviewTaskOutbox.from_env(args.task_dsn, hotel_id=args.hotel_id)
    except TaskDataGap as exc:
        return UnavailableReviewTaskOutbox(str(exc))


def _context(args: argparse.Namespace) -> RequestContext:
    return RequestContext.from_mapping(
        {
            "hotel_id": args.hotel_id,
            "principal_role": args.principal_role,
            "principal_ref": args.principal_ref,
            "as_of_datetime": args.as_of_datetime,
        }
    )


def run_s13_cli(argv: list[str], *, default_db: str | None = None) -> dict[str, Any]:
    parser = build_parser()
    args = parser.parse_args(argv)
    if default_db and "--db" not in argv:
        args.db = default_db
    source_optional = args.command in {
        "review-reply-reject",
        "review-reply-cancel",
        "review-reply-status",
    }
    try:
        source = _source_repository(args)
    except SourceDataGap as exc:
        if source_optional:
            source = MemoryReviewSourceRepository([])
        else:
            return {
                "status": "data_gap",
                "action": args.command.removeprefix("review-reply-").replace("-", "_"),
                "blocked_reason": str(exc),
                "data_gaps": [str(exc)],
                "copy_only": False,
                "risk_flags": [],
            }
    service = S13Service(
        control_repository=S13ControlRepository(args.db),
        source_repository=source,
        task_outbox=_task_outbox(args),
    )
    context = _context(args)
    if args.command == "review-reply-list":
        return service.list_pending(context, limit=args.limit)
    if args.command == "review-reply-draft":
        return service.generate_draft(context, review_ref=args.review_ref)
    if args.command == "review-reply-preview":
        content = Path(args.reply_file).read_text(encoding="utf-8")
        return service.generate_draft(context, review_ref=args.review_ref, human_reply_content=content)
    if args.command == "review-reply-confirm":
        return service.confirm(context, request_id=args.request_id)
    if args.command == "review-reply-reject":
        return service.reject_or_cancel(context, request_id=args.request_id, action="reject")
    if args.command == "review-reply-cancel":
        return service.reject_or_cancel(context, request_id=args.request_id, action="cancel")
    if args.command == "review-reply-retry":
        return service.retry(context, request_id=args.request_id)
    if args.command == "review-reply-status":
        return service.query_status(context, request_id=args.request_id, review_ref=args.review_ref)
    raise AssertionError("unreachable_s13_command")


def main(argv: list[str] | None = None) -> int:
    result = run_s13_cli(list(sys.argv[1:] if argv is None else argv))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") in {"ok", "partial", "blocked", "data_gap", "active_conflict", "already_handled", "write_failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
