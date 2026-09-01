from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import sys
from typing import Any


_TARGETS = {"runtime.adapters.database", "runtime.feishu_command_router", "runtime.safety.auth"}
_INSTALLED = False


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _safe_short_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    return text[:6] + "…" if len(text) > 8 else text


def _review_score(row: dict[str, Any]) -> float | None:
    for key in ("review_score", "score_value", "score"):
        try:
            value = row.get(key)
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _review_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        score = _review_score(row)
        negative = _as_bool(row.get("is_negative_review") or row.get("bad_comment"))
        replied = _as_bool(row.get("is_replied"))
        if replied and not negative and not (score is not None and score <= 3.0):
            continue
        content = str(row.get("review_content") or row.get("comment") or "").strip()
        if not content:
            continue
        candidates.append(
            {
                "review_id": row.get("review_id") or row.get("comment_id"),
                "review_id_short": _safe_short_id(row.get("review_id") or row.get("comment_id")),
                "review_score": score,
                "review_content_summary": content[:120],
                "review_time": row.get("review_time") or row.get("comment_time"),
                "is_replied": replied,
                "is_negative_review": negative,
                "room_type_id": row.get("room_type_id"),
                "room_type_name": row.get("room_type_name") or row.get("room_name"),
                "room_type_match_quality": "exact_id" if row.get("room_type_id") else "name_fallback",
            }
        )
    candidates.sort(key=lambda item: (not item["is_negative_review"], item["review_score"] if item["review_score"] is not None else 99))
    return candidates[:5]


def _review_draft_text(candidate: dict[str, Any]) -> str:
    score = candidate.get("review_score") if candidate.get("review_score") is not None else "-"
    room = candidate.get("room_type_id") or candidate.get("room_type_name") or "-"
    return (
        "【评论回复草稿】\n"
        "当前阶段仅生成草稿，不会发布到平台。\n\n"
        f"候选评论：{candidate.get('review_id_short')}\n"
        f"评分：{score}\n"
        f"房型：{room}\n"
        f"评论摘要：{candidate.get('review_content_summary')}\n\n"
        "建议回复：\n"
        "尊敬的客人，感谢您反馈本次入住体验。非常抱歉本次服务没有完全达到您的预期。"
        "您提到的问题我们会反馈给门店负责人逐项跟进，重点检查卫生、设施和服务流程，避免类似情况再次发生。"
        "感谢您的提醒，也欢迎您后续继续监督我们的改进。\n\n"
        "边界：未创建平台审批，未写入平台，未执行发布。"
    )


def _extract_review_rows(db_result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = db_result.get("payload") if isinstance(db_result, dict) else None
    if not isinstance(payload, dict):
        return []
    for key in ("review_candidates", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
    return []


def _compact_or_full(module: Any, result: dict[str, Any], compact: bool) -> dict[str, Any]:
    if compact:
        return module.compact_feishu_route_result(result)
    return result


def _blocked_other_hotel_result(module: Any, result: dict[str, Any], *, compact: bool) -> dict[str, Any]:
    blocked_reason = result.get("blocked_reason") or "tenant_scope_mismatch"
    result.update(
        {
            "status": "blocked",
            "blocked_reason": blocked_reason,
            "reason": blocked_reason,
            "business_result_generated": False,
            "formal_approval_created": False,
            "live_execution_count": 0,
            "send_payload": {
                "text": "当前会话不能查询演示酒店或其他酒店数据。",
                "card": None,
                "send_allowed": True,
                "output_profile": result.get("output_profile") or "owner_business",
                "warnings": [blocked_reason],
            },
        }
    )
    return _compact_or_full(module, result, compact)


def _sqlite_dm_open_id_context(
    module: Any,
    db_path: str,
    *,
    user_id: str | None,
    open_id: str | None,
    union_id: str | None,
    requested_hotel_id: str | None,
) -> dict[str, Any]:
    try:
        with module.closing(module.connect(db_path)) as conn:
            state = conn.execute(
                "SELECT status FROM auth_backend_state WHERE backend_name='feishu_active_auth'"
            ).fetchone()
            if not state or state["status"] != "active":
                return {"auth_status": "unavailable", "reason": "sqlite_active_auth_unavailable"}
            principal = conn.execute(
                "SELECT * FROM auth_principals WHERE status='active' AND (open_id=? OR user_id=? OR union_id=?) LIMIT 1",
                (open_id, user_id, union_id),
            ).fetchone()
            if not principal:
                return {"auth_status": "unauthorized", "reason": "sqlite_principal_not_found"}
            item = dict(principal)
            memberships = [
                dict(row)
                for row in conn.execute(
                    "SELECT hotel_id, role FROM hotel_memberships WHERE principal_id=? AND status='active'",
                    (item["principal_id"],),
                ).fetchall()
            ]
            authorized_hotel_ids = sorted({str(row["hotel_id"]) for row in memberships if row.get("hotel_id")})
            if not memberships:
                return {
                    "auth_status": "unauthorized",
                    "reason": "direct_message_hotel_membership_missing",
                    "principal_id": item["principal_id"],
                    "user_role": "admin" if bool(item.get("is_global_admin")) else "guest",
                    "global_admin": bool(item.get("is_global_admin")),
                    "resolved_hotel_id": None,
                    "authorized_hotel_ids": [],
                    "tenant_status": "direct_message_unbound",
                }
            selected_hotel_id = requested_hotel_id
            if not selected_hotel_id and len(authorized_hotel_ids) == 1:
                selected_hotel_id = authorized_hotel_ids[0]
            if not selected_hotel_id:
                return {
                    "auth_status": "authorized",
                    "reason": "tenant_selection_required",
                    "principal_id": item["principal_id"],
                    "user_role": "admin" if bool(item.get("is_global_admin")) else "guest",
                    "global_admin": bool(item.get("is_global_admin")),
                    "resolved_hotel_id": None,
                    "authorized_hotel_ids": authorized_hotel_ids,
                    "tenant_status": "tenant_selection_required",
                }
            membership = next((row for row in memberships if str(row.get("hotel_id")) == str(selected_hotel_id)), None)
            if not membership and not bool(item.get("is_global_admin")):
                return {
                    "auth_status": "unauthorized",
                    "reason": "tenant_scope_mismatch",
                    "principal_id": item["principal_id"],
                    "user_role": "guest",
                    "global_admin": False,
                    "resolved_hotel_id": None,
                    "authorized_hotel_ids": authorized_hotel_ids,
                    "tenant_status": "tenant_scope_mismatch",
                }
            role = "admin" if bool(item.get("is_global_admin")) else str(membership.get("role") or "guest")
            return {
                "auth_status": "authorized",
                "reason": "authorized_by_open_id_membership",
                "principal_id": item["principal_id"],
                "user_role": role,
                "global_admin": bool(item.get("is_global_admin")),
                "resolved_hotel_id": str(selected_hotel_id),
                "authorized_hotel_ids": authorized_hotel_ids,
                "tenant_status": "bound_by_open_id",
            }
    except Exception:
        return {"auth_status": "unavailable", "reason": "sqlite_active_auth_unavailable"}


def _patch_auth(module: Any) -> None:
    if getattr(module, "_LIVE_CONTRACT_PATCHED", False):
        return
    original_build_auth_context = module.build_auth_context

    def build_auth_context(
        *,
        source: str = "manual_test",
        user_id: str | None = None,
        open_id: str | None = None,
        union_id: str | None = None,
        chat_id: str | None = None,
        chat_type: str | None = None,
        user_role: str | None = None,
        config_path: str | None = None,
        auth_db_path: str | None = None,
        requested_hotel_id: str | None = None,
    ) -> dict[str, Any]:
        if source == "feishu" and auth_db_path and (user_id or open_id or union_id):
            resolved_chat_type = chat_type if chat_type in {"group", "p2p"} else ("p2p" if str(chat_id or "").startswith("user:") or not chat_id else "group")
            chat_resolution = module.resolve_feishu_business_chat_id(chat_id)
            if resolved_chat_type == "p2p" and chat_resolution.get("status") != "ok":
                sqlite_context = _sqlite_dm_open_id_context(
                    module,
                    auth_db_path,
                    user_id=user_id,
                    open_id=open_id,
                    union_id=union_id,
                    requested_hotel_id=requested_hotel_id,
                )
                if sqlite_context.get("auth_status") != "unavailable":
                    role = sqlite_context.get("user_role") or "guest"
                    return {
                        "source": source,
                        "auth_status": sqlite_context["auth_status"],
                        "reason": sqlite_context.get("reason") or "authorized_by_open_id_membership",
                        "user_role": role,
                        "matched_by": "sqlite_open_id_membership",
                        "matched_role_name": None,
                        "identity_warning": "p2p_chat_id_missing_used_open_id_membership",
                        "principal_id": sqlite_context.get("principal_id"),
                        "role_map_version": 3,
                        "auth_backend": "sqlite_active",
                        "global_admin": bool(sqlite_context.get("global_admin")),
                        "resolved_hotel_id": sqlite_context.get("resolved_hotel_id"),
                        "authorized_hotel_ids": sqlite_context.get("authorized_hotel_ids") or [],
                        "tenant_status": sqlite_context.get("tenant_status") or "unresolved",
                        "feishu_user_id": user_id,
                        "feishu_open_id": open_id,
                        "feishu_union_id": union_id,
                        "feishu_chat_id": None,
                        "chat_type": "p2p",
                        "permissions": module.permissions_for_role(role),
                    }
        return original_build_auth_context(
            source=source,
            user_id=user_id,
            open_id=open_id,
            union_id=union_id,
            chat_id=chat_id,
            chat_type=chat_type,
            user_role=user_role,
            config_path=config_path,
            auth_db_path=auth_db_path,
            requested_hotel_id=requested_hotel_id,
        )

    module.build_auth_context = build_auth_context
    module._LIVE_CONTRACT_PATCHED = True


def _patch_database(module: Any) -> None:
    if getattr(module, "_LIVE_CONTRACT_PATCHED", False):
        return
    original_col = module._col

    def _hotel_id_first_col(columns: dict[str, str], key: str) -> str:
        if key == "hotel_name" and isinstance(columns, dict) and columns.get("hotel_id"):
            return columns["hotel_id"]
        return original_col(columns, key)

    module._col = _hotel_id_first_col

    if "ota_review_detail" not in module.TEMPLATES:
        module.TEMPLATES = tuple(module.TEMPLATES) + ("ota_review_detail",)
    module.TEMPLATE_REQUIRED_CANONICAL_FIELDS["ota_review_detail"] = ("hotel_id", "review_text")
    module.V4_TEMPLATE_TABLE_KEYS["ota_review_detail"] = ("meituan_review_detail",)
    module._LIVE_CONTRACT_PATCHED = True


def _patch_router(module: Any) -> None:
    if getattr(module, "_LIVE_CONTRACT_PATCHED", False):
        return
    original_other_hotel = module._requested_other_hotel_name
    original_price_guard_payload = module._chat_price_guard_payload
    original_safe_route = module.safe_route_feishu_command
    requested_demo_hotel_id = getattr(module, "_requested_demo_hotel_id", lambda message: False)

    def _requested_other_hotel_name(message: str, resolved_hotel_id: str | None) -> bool:
        if requested_demo_hotel_id(message):
            return True
        return original_other_hotel(message, resolved_hotel_id)

    def _chat_price_guard_payload(message: str) -> dict[str, Any] | None:
        parsed = original_price_guard_payload(message)
        if parsed:
            parsed.setdefault("room_type_match_quality", "exact_id")
            return parsed
        import re

        raw = message or ""
        match = re.search(
            r"(?:把|将)?\s*(?P<room>[^，,。\s]+(?:房|房型|大床房|双床房|电竞房)[^，,。\s]*)\s*(?:的)?底价\s*(?:设为|设置为|为|=|：|:)?\s*[¥￥]?(?P<floor>\d+(?:\.\d+)?)\s*[，,、\s]+(?:顶价|封顶价|最高价)\s*(?:设为|设置为|为|=|：|:)?\s*[¥￥]?(?P<ceiling>\d+(?:\.\d+)?)",
            raw,
        )
        if not match:
            return None
        return {
            "room_type_id": f"NAME_{hashlib.sha256(match.group('room').encode('utf-8')).hexdigest()[:12].upper()}",
            "room_type_name": match.group("room").strip(),
            "room_type_match_quality": "name_fallback",
            "requires_room_type_confirmation": True,
            "floor_price": float(match.group("floor")),
            "ceiling_price": float(match.group("ceiling")),
            "min_increase_pct": 0.01,
            "min_decrease_pct": 0.01,
            "max_increase_pct": 0.15,
            "max_decrease_pct": 0.15,
        }

    def _handle_snapshot_alias_query(message: str, result: dict[str, Any], compact: bool) -> dict[str, Any] | None:
        text = str(message or "").lower()
        if "经营快照" not in text:
            return None
        if requested_demo_hotel_id(message):
            return _blocked_other_hotel_result(module, result, compact=compact)
        hotel_id = result.get("resolved_hotel_id") or result.get("hotel_id")
        if not hotel_id:
            return None
        if not module.database_source_enabled():
            return None
        db_result = module.database_template_result("operating_snapshot", str(hotel_id))
        if not isinstance(db_result, dict) or db_result.get("status") != "ok":
            result.update({"status": "data_gap", "reason": "operating_snapshot_data_gap", "business_result_generated": False})
            return _compact_or_full(module, result, compact)
        payload = db_result.get("payload") or {}
        result.update(
            {
                "status": "ok",
                "intent": "run_s02",
                "hotel_id": str(hotel_id),
                "data_source_type": db_result.get("data_source_type") or "mysql_db",
                "core_metrics": {
                    "sold_room_nights_today": payload.get("sold_room_nights_today") or payload.get("sold_rooms"),
                    "sold_orders_today": payload.get("sold_orders_today") or payload.get("orders_today"),
                    "sold_rooms": payload.get("sold_rooms"),
                    "total_rooms": payload.get("total_rooms"),
                },
                "business_result_generated": True,
            }
        )
        return _compact_or_full(module, result, compact)

    def _handle_review_draft_query(message: str, result: dict[str, Any], compact: bool) -> dict[str, Any] | None:
        text = str(message or "")
        is_review_draft = result.get("intent") == "review_reply_draft" or "评论草稿" in text or "待回复评论" in text or "差评回复草稿" in text
        if not is_review_draft or "发布" in text:
            return None
        hotel_id = result.get("resolved_hotel_id") or result.get("hotel_id")
        if not hotel_id:
            return None
        db_result = module.database_template_result("ota_review_detail", str(hotel_id))
        rows = _extract_review_rows(db_result)
        candidates = _review_candidates(rows)
        if not candidates:
            result.update(
                {
                    "status": "data_gap",
                    "source_status": db_result.get("status") if isinstance(db_result, dict) else "data_gap",
                    "reason": "review_detail_no_candidate_rows",
                    "business_result_generated": False,
                    "review_publish_attempted": False,
                }
            )
            return _compact_or_full(module, result, compact)
        candidate = candidates[0]
        text_payload = _review_draft_text(candidate)
        result.update(
            {
                "status": "ok",
                "intent": "review_reply_draft",
                "source_status": "ok",
                "review_draft_generated": True,
                "review_publish_attempted": False,
                "formal_approval_created": False,
                "live_execution_count": 0,
                "review_candidates": candidates,
                "suggested_reply": text_payload,
                "business_result_generated": True,
                "data_source_type": "mysql_db",
                "send_payload": {
                    "text": text_payload,
                    "card": None,
                    "send_allowed": True,
                    "output_profile": result.get("output_profile") or "owner_business",
                    "warnings": [],
                    "data_source_type": "mysql_db",
                    "freshness_status": result.get("freshness_status"),
                },
            }
        )
        return _compact_or_full(module, result, compact)

    def safe_route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_safe_route(message, *args, **kwargs)
        if not kwargs.get("production_feishu"):
            return result
        compact = bool(kwargs.get("compact"))
        if requested_demo_hotel_id(message):
            if result.get("blocked_reason") == "demo_hotel_not_allowed_in_production_feishu":
                return _compact_or_full(module, result, compact)
            return _blocked_other_hotel_result(module, result, compact=compact)
        snapshot_result = _handle_snapshot_alias_query(message, result, compact)
        if snapshot_result is not None:
            return snapshot_result
        review_result = _handle_review_draft_query(message, result, compact)
        if review_result is not None:
            return review_result
        return result

    module._requested_other_hotel_name = _requested_other_hotel_name
    module._chat_price_guard_payload = _chat_price_guard_payload
    module.safe_route_feishu_command = safe_route_feishu_command
    module._LIVE_CONTRACT_PATCHED = True


def _apply_patch(module: Any) -> None:
    if module.__name__ == "runtime.adapters.database":
        _patch_database(module)
    elif module.__name__ == "runtime.feishu_command_router":
        _patch_router(module)


class _PatchLoader(importlib.abc.Loader):
    def __init__(self, loader: importlib.abc.Loader, fullname: str) -> None:
        self.loader = loader
        self.fullname = fullname

    def create_module(self, spec):  # type: ignore[no-untyped-def]
        create = getattr(self.loader, "create_module", None)
        if create:
            return create(spec)
        return None

    def exec_module(self, module):  # type: ignore[no-untyped-def]
        self.loader.exec_module(module)  # type: ignore[attr-defined]
        _apply_patch(module)


class _PatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any = None, target: Any = None):  # type: ignore[no-untyped-def]
        if fullname not in _TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if not spec or not spec.loader:
            return None
        if isinstance(spec.loader, _PatchLoader):
            return spec
        spec.loader = _PatchLoader(spec.loader, fullname)
        return spec


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    sys.meta_path.insert(0, _PatchFinder())
    for name in list(_TARGETS):
        module = sys.modules.get(name)
        if module is not None:
            _apply_patch(module)
