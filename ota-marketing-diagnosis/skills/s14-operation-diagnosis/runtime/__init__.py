from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

SKILL_ID = "s14-operation-diagnosis"
SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parents[1]
DEFAULT_REPORT_ROOT = Path("/var/lib/ota-marketing-diagnosis/reports")
TRUE_VALUES = {"1", "true", "yes", "on"}
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from marketing_diagnosis.customer_excel_result import enrich_customer_excel_result
from marketing_diagnosis.data_v4 import normalize_dataset
from marketing_diagnosis.ctrip_flow import load_mysql_dsn_dataset
from marketing_diagnosis.excel_loader import load_excel_dataset
from marketing_diagnosis.reporting_v2 import write_reports
from marketing_diagnosis.runtime_env import load_local_s14_env
from marketing_diagnosis.room_name_manual_v43 import (
    normalize_room_type_names,
    parse_room_type_names_from_text,
)
from marketing_diagnosis.ctrip_flow_rules import process

from .feishu_adapter import build_feishu_card_reply, build_feishu_reply


def _safe_segment(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return text.strip("-._") or fallback


def _card_callback_enabled(config: dict[str, Any] | None = None) -> bool:
    configured = os.environ.get("S14_FEISHU_CARD_CALLBACK_ENABLED")
    if configured is None:
        configured = (config or {}).get("feishu_card_callback_enabled")
    return str(configured or "").strip().lower() in TRUE_VALUES


def _json_safe(value: Any) -> Any:
    """Convert a runtime result into values accepted by JSON/OpenClaw bridges."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    # NumPy scalar values and similar objects usually expose item().
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            scalar = item_method()
            if scalar is not value:
                return _json_safe(scalar)
        except (TypeError, ValueError):
            pass

    return str(value)


def _manual_room_names(inputs: dict[str, Any]) -> list[str]:
    explicit = (
        inputs.get("manual_room_type_names")
        or inputs.get("room_type_names")
        or inputs.get("manual_room_names")
    )
    names = normalize_room_type_names(explicit)
    if names:
        return names

    for key in (
        "request_text",
        "message_text",
        "voice_text",
        "transcript",
        "text",
    ):
        names = parse_room_type_names_from_text(inputs.get(key))
        if names:
            return names
    return []


def _manual_room_source(inputs: dict[str, Any], names: list[str]) -> str:
    if not names:
        return "用户手动输入（未提供）"
    if inputs.get("voice_text") or inputs.get("transcript"):
        return "飞书语音转写人工输入"
    if inputs.get("request_text") or inputs.get("message_text") or inputs.get("text"):
        return "飞书文本人工输入"
    return str(inputs.get("manual_input_source") or "网页/接口人工输入")


def _inject_manual_room_names(
    normalized: dict[str, Any],
    prepared: dict[str, Any],
) -> None:
    names = list(prepared.get("manual_room_type_names") or [])
    if not names:
        return
    sections = normalized.setdefault("sections", {})
    sections.setdefault("manual_inputs", []).append(
        {
            "room_type_names": names,
            "input_source": prepared.get("manual_input_source"),
            "source_table": prepared.get("manual_input_source"),
            "operator": prepared.get("manual_input_operator"),
            "recorded_at": prepared.get("manual_input_recorded_at"),
        }
    )


def _source_selection_result(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = (
        "请选择数据来源，回复：\n"
        "- **数据库** — 系统自动拉取数据诊断\n"
        "- **上传Excel** — 发送已填好的Excel附件诊断"
    )
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    "本次按已经映射好的字段执行**整体诊断**。\n\n"
                    "请选择从服务器数据库读取，或随后上传 Excel。"
                ),
            },
        }
    ]
    if _card_callback_enabled(config):
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "type": "primary",
                        "text": {"tag": "plain_text", "content": "数据库"},
                        "value": {
                            "action": "s14_source",
                            "source": "database",
                        },
                    },
                    {
                        "tag": "button",
                        "type": "default",
                        "text": {"tag": "plain_text", "content": "上传Excel"},
                        "value": {
                            "action": "s14_source",
                            "source": "excel",
                        },
                    },
                ],
            }
        )
    else:
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "请直接回复 **数据库** 或 **上传Excel**。",
                },
            }
        )

    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": "S14诊断｜请选择数据来源",
                },
            },
            "elements": elements,
        },
    }
    return {
        "skill_id": SKILL_ID,
        "status": "awaiting_source",
        "platform": "multi",
        "data_source": "pending",
        "feishu_message": message,
        "feishu_card": card,
    }


def _excel_pending_result() -> dict[str, Any]:
    message = (
        "数据来源：Excel\n"
        "请在当前群聊中直接发送 .xlsx 或 .xlsm 文件，无需再次@机器人。"
    )
    card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "turquoise",
                "title": {
                    "tag": "plain_text",
                    "content": "S14诊断｜等待Excel附件",
                },
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "**数据来源：Excel**\n\n"
                            "请在当前群聊中直接发送 `.xlsx` 或 `.xlsm` 文件，"
                            "**无需再次@机器人**。"
                        ),
                    },
                }
            ],
        },
    }
    return {
        "skill_id": SKILL_ID,
        "status": "awaiting_excel",
        "platform": "multi",
        "data_source": "excel_pending",
        "feishu_message": message,
        "feishu_card": card,
    }


def _apply_excel_context(prepared: dict[str, Any], raw_dataset: dict[str, Any]) -> None:
    """Use basic information embedded in the customer workbook.

    This helper is called only from ``excel_upload`` mode. Database mode and
    all Feishu response/card behavior remain unchanged.
    """
    context = raw_dataset.pop("__excel_context__", None)
    if not isinstance(context, dict):
        return

    for key in ("hotel_id", "hotel_name", "period_start", "period_end"):
        value = context.get(key)
        if value not in (None, ""):
            prepared[key] = value

    try:
        start = date.fromisoformat(str(prepared.get("period_start"))[:10])
        end = date.fromisoformat(str(prepared.get("period_end"))[:10])
        if end >= start:
            prepared["period_days"] = (end - start).days + 1
    except (TypeError, ValueError):
        pass


class S14OperationDiagnosis:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        prepared = self._prepare_inputs(inputs or {})
        mode = prepared["data_source_mode"]

        # OpenClaw may invoke the Skill directly from trigger metadata instead of
        # executing scripts/s14_feishu_entry.py. These two modes keep that path
        # deterministic, JSON-serializable, and free from accidental DB runs.
        if mode == "source_selection":
            return _source_selection_result(self.config)
        if mode == "excel_pending":
            return _excel_pending_result()

        if mode == "excel_upload":
            excel_path = prepared.get("input_excel_path")
            if not excel_path:
                raise ValueError("S14 excel_upload mode requires input_excel_path")
            raw_dataset = load_excel_dataset(excel_path)
            _apply_excel_context(prepared, raw_dataset)
            data_source = "excel_upload"
        elif mode == "database":
            dsn = self._resolve_dsn(prepared.get("hotel_id"))
            if not dsn:
                raise ValueError("S14 database mode requires S14_DB_DSN or config db_dsn")
            raw_dataset = load_mysql_dsn_dataset(
                dsn,
                limit=int(self.config.get("limit") or prepared.get("limit") or 5000),
                hotel_id=prepared.get("hotel_id"),
                ctrip_hotel_id=prepared.get("ctrip_hotel_id"),
                platform=prepared.get("platform"),
                period_start=prepared.get("period_start"),
                period_end=prepared.get("period_end"),
            )
            data_source = "hotel_puyue_mysql"
        else:
            raise ValueError(f"unsupported S14 data_source_mode: {mode}")

        normalized = normalize_dataset(raw_dataset)
        normalized["hotel_id"] = prepared.get("hotel_id")
        normalized["hotel_name"] = prepared.get("hotel_name")
        normalized["platform"] = prepared.get("platform")
        _inject_manual_room_names(normalized, prepared)
        result = process(normalized)
        if mode == "excel_upload":
            result = enrich_customer_excel_result(result, raw_dataset)
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        report_dir = self._report_dir(prepared, run_id)
        skill_result = {
            **result,
            "skill_id": SKILL_ID,
            "run_id": run_id,
            "hotel_id": prepared.get("hotel_id"),
            "hotel_name": prepared.get("hotel_name"),
            "platform": prepared.get("platform"),
            "period_start": prepared.get("period_start"),
            "period_end": prepared.get("period_end"),
            "period_days": prepared.get("period_days"),
            "data_source": data_source,
            "manual_room_type_names": prepared.get("manual_room_type_names"),
            "report_dir": str(report_dir),
            "approval_required": False,
            "dry_run": True,
        }
        paths = write_reports(skill_result, report_dir)
        report_file_path = paths["report_html"]
        report_url = self._public_url(report_file_path, prepared["output_root"])
        skill_result.update({
            "report_file_path": report_file_path,
            "report_url": report_url,
            "report_json": paths["report_json"],
            "report_markdown": paths["report_markdown"],
        })
        skill_result["feishu_message"] = build_feishu_reply(skill_result)
        skill_result["feishu_card"] = build_feishu_card_reply(skill_result)

        # OpenClaw serializes the complete return object before the model/channel
        # selects feishu_message or feishu_card. Normalize every nested value so
        # report links are not lost because of one Decimal/date/NumPy scalar.
        return _json_safe(skill_result)

    def _resolve_dsn(self, hotel_id: str | None = None) -> str | None:
        load_local_s14_env()
        if self.config.get("db_dsn"):
            return self.config["db_dsn"]
        if hotel_id:
            suffix = str(hotel_id).upper().replace("-", "_")
            return os.environ.get(f"S14_DB_DSN_{suffix}")
        env_name = self.config.get("db_dsn_env") or "S14_DB_DSN"
        return os.environ.get(env_name)

    def _prepare_inputs(self, inputs: dict[str, Any]) -> dict[str, Any]:
        hotel_id = str(inputs.get("hotel_id") or "").strip()
        if not hotel_id:
            raise ValueError("hotel_id_required")
        today = datetime.now().date()
        period_days = int(inputs.get("period_days") or 30)
        start = today - timedelta(days=max(1, period_days) - 1)
        output_root = (
            inputs.get("output_root")
            or inputs.get("output_dir")
            or self.config.get("report_output_dir")
            or os.environ.get("S14_REPORT_OUTPUT_DIR")
            or str(DEFAULT_REPORT_ROOT)
        )
        manual_names = _manual_room_names(inputs)
        return {
            "data_source_mode": inputs.get("data_source_mode") or "source_selection",
            "input_excel_path": inputs.get("input_excel_path"),
            "hotel_id": hotel_id,
            "ctrip_hotel_id": inputs.get("ctrip_hotel_id") or self.config.get("ctrip_hotel_id") or os.environ.get("S14_CTRIP_HOTEL_ID"),
            "hotel_name": inputs.get("hotel_name"),
            "platform": "multi",
            "period_start": inputs.get("period_start") or str(start),
            "period_end": inputs.get("period_end") or str(today),
            "period_days": period_days,
            "manual_room_type_names": manual_names,
            "manual_input_source": _manual_room_source(inputs, manual_names),
            "manual_input_operator": inputs.get("manual_input_operator") or inputs.get("sender_id"),
            "manual_input_recorded_at": inputs.get("manual_input_recorded_at") or datetime.now().isoformat(timespec="seconds"),
            "output_root": output_root,
            "public_base_url": inputs.get("public_base_url") or self.config.get("public_base_url") or os.environ.get("S14_PUBLIC_BASE_URL"),
            "dry_run": True,
            "limit": inputs.get("limit"),
        }

    def _report_dir(self, prepared: dict[str, Any], run_id: str) -> Path:
        root = Path(prepared["output_root"])
        hotel = _safe_segment(prepared.get("hotel_id"), "hotel")
        platform = _safe_segment(prepared.get("platform"), "multi")
        period = f"{_safe_segment(prepared.get('period_start'), 'start')}_{_safe_segment(prepared.get('period_end'), 'end')}"
        return root / hotel / platform / period / run_id

    def _public_url(self, report_file_path: str, output_root: str) -> str:
        base = self.config.get("public_base_url") or os.environ.get("S14_PUBLIC_BASE_URL")
        if base:
            try:
                rel = Path(report_file_path).resolve().relative_to(Path(output_root).resolve())
                return base.rstrip("/") + "/" + rel.as_posix()
            except ValueError:
                return base.rstrip("/") + "/" + Path(report_file_path).name
        return Path(report_file_path).resolve().as_uri()
