from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


ALLOWED_FIELDS = [
    "脱敏摘要",
    "诊断结论",
    "证据日期",
    "数据新鲜度",
    "风险",
    "建议动作",
    "审批状态",
]

CONFIG_EXPORT_RE = re.compile(
    r"(feishu-role-map|database-source|auth-profiles|openclaw[_\-.]?config|hotel-ota\.env|env_config|\.env\b|"
    r"HOTEL_OTA_DB_DSN|HOTEL_OTA_DB_DSN_PUYUE|HOTEL_OTA_DB_DSN_ZHITING|HOTEL_OTA_DB_DSN_XINGFENG|"
    r"mysql://|mysql\+pymysql://|pymysql\.connect|SHOW\s+DATABASES|SHOW\s+TABLES|DESCRIBE\b|information_schema|"
    r"角色表|数据库映射|系统配置|配置包|auth profile|dsn|密钥|密码|token|secret)",
    re.IGNORECASE,
)
RAW_DATA_RE = re.compile(
    r"(daily_metrics|fact_daily_metrics|fact_room_fee_daily|fact_room_status_snapshot|数据库导出|原始数据|原始表|"
    r"byh_plugin_auth_status|byh_plugin_run_log|jd01_booking_detail|jd04_inhouse_extension|rs01_room_revenue_daily|"
    r"kf11_room_status_snapshot|ctrip_ota_goods_price_mapping|meituan_ota_goods_price_mapping|"
    r"ctrip_zhiting_price_task|meituan_zhiting_price_task|"
    r"MCP\s*原始|mcp\s*raw|天气\s*原始|weather\s*raw|"
    r"\bcsv\b|\bxlsx\b|\bjson\b|\bsqlite\b|\bdb\b|完整 runtime|runtime json)",
    re.IGNORECASE,
)
SOURCE_EXPORT_RE = re.compile(r"(源码|源代码|source code|repo|repository|项目代码|打包项目|zip)", re.IGNORECASE)
SOURCE_TEXT_EXPORT_RE = re.compile(
    r"(SKILL\.md|skill\s*源码|runtime_commands\.md|references/?|reference 五件套|五件套链接|"
    r"input_schema\.json|output_schema\.json|rules\.md|examples\.md|"
    r"(全文|完整文本|完整源码|具体文本|具体的文本|贴出来|调出来).*(skill|reference|references|runtime_commands|rules|examples|schema)|"
    r"(skill|reference|references|runtime_commands|rules|examples|schema).*(全文|完整文本|完整源码|具体文本|具体的文本|贴出来|调出来))",
    re.IGNORECASE,
)
OPS_INSTALL_RE = re.compile(
    r"((下载|安装|部署|装一下|拉取).*(模型|插件|应用|二进制|工具|GGUF|embedding)|"
    r"(模型|插件|应用|GGUF).*(下载|安装|部署|装到服务器))",
    re.IGNORECASE,
)
APPROVAL_BYPASS_RE = re.compile(
    r"((bypass|绕过|跳过|强制|直接).*(新鲜度|审批|approval|freshness|数据校验)|"
    r"(手动|聊天).*(ADR|平均房价|今日数据).*(正式审批|创建审批|调价审批)|"
    r"(正式审批|创建审批|调价审批).*(手动|聊天).*(ADR|平均房价|今日数据))",
    re.IGNORECASE,
)
MODEL_PROVIDER_ERROR_RE = re.compile(
    r"(API provider returned a billing error|provider\s+(billing|quota|unavailable|error)|"
    r"insufficient balance|run out of credits|INVALID_API_KEY|model unavailable)",
    re.IGNORECASE,
)
MUTATION_RE = re.compile(
    r"(写文件|创建文件|修改文件|删除文件|改代码|修改代码|改配置|修改配置|角色表.*(加|删|改)|"
    r"CREATE\s+OR\s+REPLACE\s+VIEW|CREATE\s+VIEW|DROP\s+VIEW|ALTER\s+TABLE|GRANT\b|REVOKE\b|FLUSH\s+PRIVILEGES|"
    r"\bgit\b|git pull|git reset|git clean|git stash|stash|工作区.*(干净|clean)|已修改|已改|已经修改|已回滚|已完成.*回滚|"
    r"重启|restart|systemctl|openclaw gateway restart)",
    re.IGNORECASE,
)
FEISHU_TOOL_RAW_WRITE_RE = re.compile(
    r"(多维表格|飞书文档|飞书表格|doc|sheet).*(源码|配置|密钥|env|原始数据|数据库原始表)|"
    r"(源码|配置|密钥|env|原始数据|数据库原始表).*(多维表格|飞书文档|飞书表格|doc|sheet)",
    re.IGNORECASE,
)
INTERNAL_VALUE_RE = re.compile(
    r"(mysql(\+pymysql)?://|postgres(ql)?://|ou_[A-Za-z0-9_\-]+|oc_[A-Za-z0-9_\-]+|on_[A-Za-z0-9]{16,}|"
    r"open_id|chat_id|(user_id|union_id)\s*[:=]\s*[A-Za-z0-9_\-]+|"
    r"api 请求体|request body|signature_content|ChannelKey|AppKey|Sign=)",
    re.IGNORECASE,
)
MODEL_FOOTER_RE = re.compile(r"(^|\n)\s*(Agent|Model|Provider)\s*:", re.IGNORECASE)


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() == "1"


def _production_mode() -> bool:
    env = os.environ.get("HOTEL_OTA_ENV", "production").strip().lower()
    return env not in {"dev", "development", "local", "test", "testing"}


def _ext(filename: str | None) -> str:
    if not filename:
        return ""
    return Path(filename).suffix.lower()


PRIVATE_PATH_RE = re.compile(
    r"(/etc/hotel-ota-ai/[^\s]+|/opt/openclaw/[^\s]+|/usr/local/lib/node_modules/openclaw/[^\s]+|"
    r"/var/lib/[^\s]+|/usr/share/nginx/[^\s]+|[A-Za-z]:\\[^\s]+)",
    re.IGNORECASE,
)


def _combined_text(*values: str | None) -> str:
    return "\n".join(value for value in values if value)


def _blocked(reason: str, template_id: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "blocked_reason": reason,
        "template_id": template_id,
        "allowed_fields": ALLOWED_FIELDS,
    }


def feishu_output_gate(
    *,
    source: str = "feishu",
    content_kind: str = "text",
    message: str | None = None,
    filename: str | None = None,
    artifact_kind: str | None = None,
) -> dict[str, Any]:
    """Protect system/security internals at final delivery; business authorization happens upstream."""

    source = source or "feishu"
    content_kind = content_kind or "text"
    artifact_kind = artifact_kind or ""
    text = _combined_text(message, filename, artifact_kind)
    lower_kind = artifact_kind.lower()
    extension = _ext(filename)

    if source != "feishu":
        return {
            "status": "ok",
            "blocked_reason": None,
            "template_id": "allowed-non-feishu",
            "allowed_fields": ALLOWED_FIELDS,
        }

    if MODEL_PROVIDER_ERROR_RE.search(text):
        return _blocked("model_provider_error", "model-provider-error")

    if OPS_INSTALL_RE.search(text):
        return _blocked("ops_install_not_allowed", "ops-refusal")

    if APPROVAL_BYPASS_RE.search(text):
        return _blocked("approval_bypass_not_allowed", "approval-bypass-refusal")

    if FEISHU_TOOL_RAW_WRITE_RE.search(text):
        return _blocked("feishu_tool_raw_write_not_allowed", "export-refusal")

    if SOURCE_TEXT_EXPORT_RE.search(text):
        return _blocked("source_text_export_not_allowed", "export-refusal")

    if CONFIG_EXPORT_RE.search(text) or lower_kind in {"config", "env", "role_map", "database_mapping"}:
        return _blocked("config_or_secret_export_not_allowed", "export-refusal")

    raw_data_text = re.sub(r"\b(sqlite|db)\b", "", text, flags=re.IGNORECASE)
    if RAW_DATA_RE.search(raw_data_text) or lower_kind in {"raw_data", "runtime_json", "database_export", "table_export"}:
        if not _env_flag("HOTEL_OTA_FEISHU_ALLOW_RAW_DATA_EXPORT", "0"):
            return _blocked("raw_data_export_not_allowed", "export-refusal")

    source_export_match = SOURCE_EXPORT_RE.search(text)
    if source_export_match and source_export_match.group(0).lower() == "repo" and not re.search(r"\brepo\b", text, re.IGNORECASE):
        source_export_match = None
    if source_export_match:
        return _blocked("source_export_not_allowed", "export-refusal")

    if MUTATION_RE.search(text):
        return _blocked("feishu_agent_mutation_not_allowed", "debug-refusal")

    if PRIVATE_PATH_RE.search(text):
        return _blocked("private_path_not_allowed", "debug-refusal")

    if INTERNAL_VALUE_RE.search(text):
        return _blocked("internal_identifier_or_request_detail_not_allowed", "debug-refusal")

    if not _production_mode() and _env_flag("HOTEL_OTA_FEISHU_DEBUG", "0"):
        if content_kind in {"file", "artifact"} and not _env_flag("HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT", "0"):
            return _blocked("file_export_disabled", "export-refusal")
        return {
            "status": "ok",
            "blocked_reason": None,
            "template_id": "allowed-development-debug",
            "allowed_fields": ALLOWED_FIELDS,
        }

    if content_kind in {"file", "artifact"}:
        if not _env_flag("HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT", "0"):
            return _blocked("file_export_disabled", "export-refusal")
        if extension in {".env", ".zip", ".csv", ".xlsx", ".xls", ".json", ".sqlite", ".db", ".sql"}:
            return _blocked("unsafe_file_type_for_feishu", "export-refusal")

    return {
        "status": "ok",
        "blocked_reason": None,
        "template_id": "allowed-summary",
        "allowed_fields": ALLOWED_FIELDS,
    }
