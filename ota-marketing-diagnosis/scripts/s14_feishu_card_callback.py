from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.s14_feishu_entry import handle_card_source_choice


LOGGER = logging.getLogger("s14.feishu.card_callback")
SUPPORTED_ACTION = "s14_source"
SUPPORTED_SOURCES = {"database", "excel"}
GENERIC_FAILURE_MESSAGE = "S14诊断处理失败，请稍后重试。"


@dataclass(frozen=True)
class CardSourceAction:
    event_id: str
    message_id: str
    chat_id: str
    sender_id: str
    source: str

    @property
    def dedupe_key(self) -> str:
        return "|".join(
            (self.message_id, self.chat_id, self.sender_id, SUPPORTED_ACTION, self.source)
        )


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_card_source_action(payload: dict[str, Any]) -> CardSourceAction | None:
    """Parse only the S14 source selector from a verified Feishu callback."""
    header = _mapping(payload.get("header"))
    event = _mapping(payload.get("event"))
    action = _mapping(event.get("action"))
    value = _mapping(action.get("value"))
    context = _mapping(event.get("context"))
    operator = _mapping(event.get("operator"))

    if value.get("action") != SUPPORTED_ACTION:
        return None
    source = str(value.get("source") or "").strip().lower()
    if source not in SUPPORTED_SOURCES:
        return None

    chat_id = str(context.get("open_chat_id") or "").strip()
    sender_id = str(
        operator.get("open_id")
        or operator.get("user_id")
        or operator.get("union_id")
        or ""
    ).strip()
    if not chat_id or not sender_id:
        return None

    return CardSourceAction(
        event_id=str(header.get("event_id") or "").strip(),
        message_id=str(context.get("open_message_id") or "").strip(),
        chat_id=chat_id,
        sender_id=sender_id,
        source=source,
    )


def outbound_message_parts(payload: Any) -> tuple[str, str]:
    """Build Feishu API fields without ever converting code/errors to chat text."""
    if isinstance(payload, dict):
        msg_type = payload.get("msg_type")
        card = payload.get("card")
        if msg_type == "interactive" and isinstance(card, dict):
            return "interactive", json.dumps(card, ensure_ascii=False)
    if isinstance(payload, str) and payload.strip():
        return "text", json.dumps({"text": payload.strip()}, ensure_ascii=False)
    return "text", json.dumps({"text": GENERIC_FAILURE_MESSAGE}, ensure_ascii=False)


class CardCallbackController:
    """Acknowledge callbacks immediately and finish diagnosis in the background."""

    def __init__(
        self,
        send_message: Callable[[str, Any], None],
        *,
        run_source_choice: Callable[..., Any] = handle_card_source_choice,
        submit_background: Callable[[Callable[[], None]], None] | None = None,
        dedupe_ttl_seconds: int = 600,
    ) -> None:
        self._send_message = send_message
        self._run_source_choice = run_source_choice
        self._dedupe_ttl_seconds = max(60, int(dedupe_ttl_seconds))
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="s14-card")
        self._submit_background = submit_background or self._submit_to_pool

    def _submit_to_pool(self, job: Callable[[], None]) -> None:
        self._pool.submit(job)

    def accept(self, payload: dict[str, Any]) -> tuple[str, str]:
        action = parse_card_source_action(payload)
        if action is None:
            return "ignored", "未识别该操作，请重新发送“S14诊断”。"

        now = time.monotonic()
        with self._lock:
            expired = [
                key
                for key, timestamp in self._seen.items()
                if now - timestamp > self._dedupe_ttl_seconds
            ]
            for key in expired:
                self._seen.pop(key, None)
            if action.dedupe_key in self._seen:
                return "duplicate", "该操作正在处理中，请勿重复点击。"
            self._seen[action.dedupe_key] = now

        self._submit_background(lambda: self._process(action))
        if action.source == "database":
            return "accepted", "已选择数据库，正在生成诊断报告。"
        return "accepted", "已选择上传Excel，请按提示发送附件。"

    def _process(self, action: CardSourceAction) -> None:
        try:
            result = self._run_source_choice(
                action.source,
                chat_id=action.chat_id,
                sender_id=action.sender_id,
            )
            self._send_message(action.chat_id, result)
        except Exception:
            LOGGER.error(
                "S14 card action failed: source=%s chat=%s event=%s",
                action.source,
                action.chat_id,
                action.event_id or "<missing>",
            )
            try:
                self._send_message(action.chat_id, GENERIC_FAILURE_MESSAGE)
            except Exception:
                LOGGER.error(
                    "Unable to send bounded S14 failure message: chat=%s",
                    action.chat_id,
                )


def _required_env(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    raise RuntimeError(f"missing required environment variable: {' or '.join(names)}")


def _flask_parse_suffix() -> tuple[Any, ...]:
    """Return (parse_req, parse_resp) from the Feishu Flask adapter."""
    try:
        from lark_oapi.adapter.flask import parse_req, parse_resp
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
            P2CardActionTriggerResponse,
        )
        return parse_req, parse_resp, P2CardActionTrigger, P2CardActionTriggerResponse
    except ImportError as exc:
        raise RuntimeError(
            "Feishu callback dependencies are missing; run pip install -e ."
        ) from exc


def _load_bot_credentials() -> dict[str, dict[str, str]]:
    """Load S14 bot credentials keyed by app_id.

    - If S14_ACCOUNT_MAP (default /etc/hotel-ota-ai/s14-account-map.json) defines
      bots, use per-bot credential prefixes S14_BOT_{HOTEL}_{APP_SECRET|VERIFICATION_TOKEN|ENCRYPT_KEY}.
    - Otherwise fall back to the legacy single bot env (FEISHU/LARK_APP_ID).
      The legacy bot's app_id is only known at first run; we return it under
      the key "legacy" and resolve app_secret via _required_env().
    """
    credentials: dict[str, dict[str, str]] = {}
    map_path = os.environ.get(
        "S14_ACCOUNT_MAP", "/etc/hotel-ota-ai/s14-account-map.json"
    )
    try:
        data = json.loads(Path(map_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}

    bots = data.get("bots") or {}
    if bots:
        for account_id, info in bots.items():
            mapping = _mapping(info)
            hotel_id = str(mapping.get("hotel_id") or "").strip()
            prefix = str(mapping.get("credential_prefix") or f"S14_BOT_{hotel_id.upper()}").strip()
            app_id = str(mapping.get("app_id") or os.environ.get(f"{prefix}_APP_ID") or "").strip()
            app_secret = str(os.environ.get(f"{prefix}_APP_SECRET") or "").strip()
            verification_token = str(os.environ.get(f"{prefix}_VERIFICATION_TOKEN") or "").strip()
            encrypt_key = str(os.environ.get(f"{prefix}_ENCRYPT_KEY") or "").strip()
            if app_id and app_secret:
                credentials[app_id] = {
                    "hotel_id": hotel_id,
                    "account_id": account_id,
                    "app_id": app_id,
                    "app_secret": app_secret,
                    "verification_token": verification_token,
                    "encrypt_key": encrypt_key,
                }
        if credentials:
            return credentials

    # Single-bot fallback is opt-in only; multi-hotel deployments must never
    # silently route a second hotel's callback through the first bot.
    if str(os.environ.get("S14_ALLOW_LEGACY_SINGLE_BOT") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("S14_ACCOUNT_MAP is required unless S14_ALLOW_LEGACY_SINGLE_BOT=1")
    app_id = str(os.environ.get("FEISHU_APP_ID") or os.environ.get("LARK_APP_ID") or "").strip()
    return {
        app_id: {
            "hotel_id": "puyue",
            "account_id": os.environ.get("FEISHU_ACCOUNT_ID", "s14-ext"),
            "app_id": app_id,
            "app_secret": _required_env("FEISHU_APP_SECRET", "LARK_APP_SECRET"),
            "verification_token": _required_env(
                "FEISHU_VERIFICATION_TOKEN", "LARK_VERIFICATION_TOKEN"
            ),
            "encrypt_key": str(
                os.environ.get("FEISHU_ENCRYPT_KEY")
                or os.environ.get("LARK_ENCRYPT_KEY")
                or ""
            ),
        }
    }


def create_app() -> Any:
    """Create the verified multi-tenant HTTP callback app using Feishu's official SDK.

    Each S14 bot gets its own Feishu Client so card-action replies are sent with the
    same app that rendered the card. The incoming body's app_id selects the handler.
    """
    try:
        import lark_oapi as lark
        from flask import Flask, request
    except ImportError as exc:
        raise RuntimeError(
            "Feishu callback dependencies are missing; run pip install -e ."
        ) from exc
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
    )

    _parse_req, _parse_resp, P2CardActionTrigger, P2CardActionTriggerResponse = _flask_parse_suffix()

    credentials = _load_bot_credentials()
    if not credentials:
        raise RuntimeError(
            "No Feishu S14 bot credentials configured. Set S14_ACCOUNT_MAP with bots "
            "or the legacy FEISHU_APP_ID/FEISHU_APP_SECRET."
        )

    reactor = {}  # app_id -> handler
    for cfg in credentials.values():
        client = (
            lark.Client.builder()
            .app_id(cfg["app_id"])
            .app_secret(cfg["app_secret"])
            .log_level(lark.LogLevel.WARNING)
            .build()
        )

        def send_message(chat_id: str, payload: Any, *, _client=client) -> None:
            msg_type, content = outbound_message_parts(payload)
            request = (
                CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                )
                .build()
            )
            response = _client.im.v1.message.create(request)
            if not response.success():
                raise RuntimeError(
                    f"Feishu message API failed with code {response.code}"
                )

        controller = CardCallbackController(send_message)

        def on_card_action(
            data: P2CardActionTrigger,
            *,
            _controller=controller,
        ) -> P2CardActionTriggerResponse:
            raw = lark.JSON.marshal(data)
            try:
                payload = json.loads(raw or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            status, toast = _controller.accept(payload)
            toast_type = "info" if status in {"accepted", "duplicate"} else "warning"
            return P2CardActionTriggerResponse(
                {"toast": {"type": toast_type, "content": toast}}
            )

        handler = (
            lark.EventDispatcherHandler.builder(
                cfg["encrypt_key"], cfg["verification_token"]
            )
            .register_p2_card_action_trigger(on_card_action)
            .build()
        )
        reactor[cfg["app_id"]] = handler

    default_app_id = next(iter(reactor))
    app = Flask(__name__)
    callback_path = str(
        os.environ.get("S14_FEISHU_CALLBACK_PATH")
        or "/s14/feishu/card-callback"
    )

    @app.post(callback_path)
    def card_callback() -> Any:
        raw_data = request.get_data(cache=True)
        payload = None
        if raw_data:
            try:
                payload = json.loads(raw_data.decode("utf-8", errors="ignore") or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = None
        app_id = ""
        if isinstance(payload, dict):
            app_id = str(
                (payload.get("header") or {}).get("app_id")
                or (payload.get("event") or {}).get("app_id")
                or ""
            ).strip()
        handler = reactor.get(app_id)
        if handler is None:
            return {"error": "unknown_feishu_app"}, 403
        return _parse_resp(handler.do(_parse_req()))

    @app.get("/healthz")
    def healthz() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    return app


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("S14_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app = create_app()
    host = str(os.environ.get("S14_FEISHU_CALLBACK_HOST") or "127.0.0.1")
    port = int(os.environ.get("S14_FEISHU_CALLBACK_PORT") or "8091")
    app.run(host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
