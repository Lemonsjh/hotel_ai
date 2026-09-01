from __future__ import annotations

import sys
from typing import Any, Mapping


_INSTALLED = False
_TARGETS = {
    "runtime.feishu_command_router",
    "runtime.s13.feishu",
}

_GENERAL_REVIEW_TERMS = (
    "评论回复",
    "差评回复",
    "回复评论",
    "回复评价",
    "点评回复",
    "评价回复",
    "评论草稿",
    "回复草稿",
    "生成评论回复",
    "帮我写评论回复",
)

_AUTH_BLOCK_REASONS = frozenset(
    {
        "tenant_scope_mismatch",
        "missing_required_feishu_auth_context",
        "group_chat_not_bound",
        "direct_message_hotel_membership_missing",
        "tenant_selection_required",
        "missing_trusted_business_chat_id",
        "missing_feishu_identity",
        "missing_required_chat_id",
        "missing_business_chat_id",
        "chat_not_allowed",
        "chat_not_bound_to_hotel",
        "user_not_hotel_member",
        "unknown_tenant",
        "verified_identity_required",
    }
)

_BASE_KEYS = frozenset(
    {
        "run_id",
        "correlation_id",
        "source",
        "generated_by_runtime",
        "auth_role",
        "personal_role",
        "auth_backend",
        "auth_status",
        "tenant_status",
        "resolved_hotel_id",
        "hotel_id",
        "output_profile",
        "production_feishu",
        "identity_present",
        "chat_bound",
        "raw_message_kind",
    }
)


def _contains_general_review_term(message: str) -> bool:
    text = str(message or "").strip()
    return any(term in text for term in _GENERAL_REVIEW_TERMS)


def _explicit_demo_requested(message: str) -> bool:
    text = str(message or "").strip().lower()
    return any(term in text for term in ("demo", "演示", "样例", "示例"))


def _auth_blocked(result: Mapping[str, Any]) -> bool:
    return str(result.get("blocked_reason") or result.get("reason") or "") in _AUTH_BLOCK_REASONS


def _trusted_auth_context(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild the trusted Feishu principal from the same gateway arguments.

    The old S13 post-router received hotel and role fields from the base route,
    but the authenticated principal was not copied into the public result.  Do
    not use a self-declared role or raw ID as the S13 principal; resolve it
    again through the controlled auth backend instead.
    """

    user_id = kwargs.get("user_id")
    open_id = kwargs.get("open_id")
    union_id = kwargs.get("union_id")
    chat_id = kwargs.get("chat_id")
    if not (user_id or open_id or union_id) or not chat_id:
        return {}

    from runtime.safety.auth import build_auth_context

    context = build_auth_context(
        source="feishu",
        user_id=user_id,
        open_id=open_id,
        union_id=union_id,
        chat_id=chat_id,
        chat_type=kwargs.get("chat_type"),
        user_role=kwargs.get("role"),
        config_path=kwargs.get("auth_config"),
        auth_db_path=kwargs.get("db_path"),
        requested_hotel_id=kwargs.get("hotel_id"),
    )
    if (
        context.get("auth_status") != "authorized"
        or not context.get("principal_id")
        or not context.get("resolved_hotel_id")
    ):
        return {}
    return context


def _clean_s13_base(result: Mapping[str, Any], trusted: Mapping[str, Any]) -> dict[str, Any]:
    """Keep auth/trace metadata while dropping legacy N017 demo payloads."""

    base = {key: result.get(key) for key in _BASE_KEYS if key in result}
    base.setdefault("source", "feishu")
    base.setdefault("generated_by_runtime", True)

    if trusted:
        role = trusted.get("user_role")
        hotel_id = trusted.get("resolved_hotel_id")
        base.update(
            {
                "principal_id": trusted.get("principal_id"),
                "auth_role": role,
                "personal_role": role,
                "resolved_hotel_id": hotel_id,
                "hotel_id": hotel_id,
                "auth_backend": trusted.get("auth_backend"),
                "auth_status": trusted.get("auth_status"),
                "tenant_status": trusted.get("tenant_status"),
                "identity_present": True,
                "chat_bound": bool(hotel_id),
            }
        )
    elif result.get("principal_id"):
        base["principal_id"] = result.get("principal_id")

    return base


def _patch_feishu(feishu: Any) -> None:
    if getattr(feishu, "_S13_REAL_ROUTE_TERMS_PATCHED", False):
        return

    original_is_s13_message = feishu.is_s13_message
    original_parse_action = feishu._parse_action
    original_blocked_base_result = feishu._blocked_base_result

    def is_s13_message(message: str) -> bool:
        if _explicit_demo_requested(message):
            return False
        return bool(original_is_s13_message(message) or _contains_general_review_term(message))

    def parse_action(message: str) -> tuple[str, dict[str, str]]:
        action, fields = original_parse_action(message)
        if action != "unknown":
            return action, fields
        # A generic request has not selected an opaque REV reference yet.  The
        # safe next action is to show the real pending queue, never to fall back
        # to the legacy N017 demo draft.
        if is_s13_message(message):
            return "list_pending", {}
        return action, fields

    def blocked_base_result(base_result: dict[str, Any]) -> bool:
        return bool(original_blocked_base_result(base_result) or _auth_blocked(base_result))

    feishu.is_s13_message = is_s13_message
    feishu._parse_action = parse_action
    feishu._blocked_base_result = blocked_base_result
    feishu._S13_REAL_ROUTE_TERMS_PATCHED = True


def _patch_router(router: Any) -> None:
    if getattr(router, "_S13_REAL_ROUTE_OVERRIDE_PATCHED", False):
        return

    original_route = router.route_feishu_command

    def route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_route(message, *args, **kwargs)

        from runtime.s13 import feishu

        if not feishu.is_s13_message(message):
            return result

        # Explicit demo requests remain owned by the legacy demo route.
        if _explicit_demo_requested(message):
            return result

        # A successfully generated real S13 result must not be executed twice.
        if (
            result.get("skill_id") == "S13"
            and result.get("intent") == "review_reply"
            and result.get("blocked_reason") != "missing_trusted_s13_request_context"
        ):
            return result

        trusted = _trusted_auth_context(kwargs)
        if _auth_blocked(result) and not trusted:
            return result

        base = _clean_s13_base(result, trusted)
        routed = feishu.route_s13_message(
            message,
            base,
            kwargs={**kwargs, "_s13_trusted_auth_context": trusted},
        )

        # These fields are evidence that the old N017/demo branch leaked into
        # the result.  A real S13 response must never carry them.
        for key in (
            "demo_dataset_id",
            "demo_business_date",
            "demo_run_id",
            "node_result",
            "run_context",
            "allow_demo_fallback",
            "allow_sample_evidence",
            "fallback_used",
            "draft_preview_allowed",
            "publish_allowed",
            "publish_attempted",
        ):
            routed.pop(key, None)
        return routed

    route_feishu_command._s13_real_route_override = True  # type: ignore[attr-defined]
    router.route_feishu_command = route_feishu_command
    router._S13_REAL_ROUTE_OVERRIDE_PATCHED = True


def _apply_patch(module: Any) -> None:
    if module.__name__ == "runtime.s13.feishu":
        _patch_feishu(module)
    elif module.__name__ == "runtime.feishu_command_router":
        _patch_router(module)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import live_contract_patch as live_patch

    live_patch._TARGETS.update(_TARGETS)
    original_apply = live_patch._apply_patch
    if not getattr(original_apply, "_S13_REAL_ROUTE_COMBINED_PATCH", False):

        def combined_apply(module: Any) -> None:
            original_apply(module)
            _apply_patch(module)

        combined_apply._S13_REAL_ROUTE_COMBINED_PATCH = True  # type: ignore[attr-defined]
        live_patch._apply_patch = combined_apply

    for name in list(_TARGETS):
        loaded = sys.modules.get(name)
        if loaded is not None:
            live_patch._apply_patch(loaded)
