from __future__ import annotations

import argparse
import hashlib
import json
import os
from typing import Any

from runtime.common import emit, now_local, parse_json_input, redacted_request
from runtime.storage import log_api


def canonical_sign_string(params: dict[str, Any], app_key: str) -> str:
    items = []
    for key in sorted(k for k in params.keys() if k != "Sign"):
        items.append(f"{key}={params[key]}")
    return "&".join(items) + app_key


def sign_request(params: dict[str, Any], app_key: str, sign_type: str) -> str:
    raw = canonical_sign_string(params, app_key)
    algo = sign_type.upper()
    if algo == "MD5":
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
    if algo == "SHA256":
        return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    raise ValueError(f"unsupported SignType: {sign_type}")


def build_beyondh_request(method: str, biz_content: dict[str, Any]) -> dict[str, Any]:
    channel_key = os.environ.get("BEYONDH_CHANNEL_KEY", "")
    app_key = os.environ.get("BEYONDH_APP_KEY", "")
    sign_type = os.environ.get("BEYONDH_SIGN_TYPE", "MD5").upper()
    params: dict[str, Any] = {
        "ChannelKey": channel_key,
        "Method": method,
        "BizContent": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        "SignType": sign_type,
        "Format": "json",
        "Charset": "utf-8",
        "Version": "1.0",
        "Timestamp": now_local(),
    }
    if channel_key and app_key:
        params["Sign"] = sign_request(params, app_key, sign_type)
    else:
        params["Sign"] = "MISSING_CHANNEL_KEY_OR_APP_KEY"
    return params


def beyondh_call(args: argparse.Namespace) -> None:
    biz = parse_json_input(args.biz_content, getattr(args, "biz_content_b64", None))
    request_body = build_beyondh_request(args.method, biz)
    domain = os.environ.get("BEYONDH_DOMAIN", "")
    summary = {
        "adapter_vendor": "beyondh",
        "channel_source": "pms",
        "data_source_type": "beyondh_api",
        "source_capability": "write_dry_run" if (args.dry_run or os.environ.get("BEYONDH_ENABLE_LIVE") != "1") else "write_live_pending",
        "field_quality": "confirmed" if os.environ.get("BEYONDH_CHANNEL_KEY") else "manual_required",
        "captured_at": now_local(),
        "method": args.method,
        "body": redacted_request(request_body),
        "domain": domain,
    }
    if args.dry_run or os.environ.get("BEYONDH_ENABLE_LIVE") != "1":
        if not getattr(args, "no_log", False):
            log_api(args.hotel_id, args.method, summary, {"dry_run": True}, "dry_run", args.db)
        emit(
            {
                "status": "dry_run",
                "request": summary,
                "message": "Direct OTA API live execution is deprecated. Use zhiting price task outbox for production price changes.",
                "blocked_reason": "dry_run_preview_only",
                "direct_api_execution_status": "deprecated",
                "live_call": False,
                "live_api_called": False,
            }
        )
        return

    emit(
        {
            "status": "blocked",
            "blocked_reason": "direct_api_execution_deprecated_use_price_task_outbox",
            "request": summary,
            "direct_api_execution_status": "deprecated",
            "live_call": False,
            "live_api_called": False,
            "message": "Direct OTA API live execution is deprecated. Write PENDING rows to the configured price task outbox tables and let the execution plugin process them.",
        }
    )
    return
