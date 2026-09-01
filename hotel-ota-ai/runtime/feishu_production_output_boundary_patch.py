from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable


_INSTALLED = False
_PRODUCTION_FEISHU_RENDER = ContextVar("hotel_ota_production_feishu_render", default=False)
_DEMO_PROVENANCE_FIELDS = ("demo_dataset_id", "demo_business_date", "demo_run_id")
_DEMO_SOURCE_TYPES = {"demo_data", "sample_data", "synthetic_today_demo"}


def _strip_demo_provenance(result: dict[str, Any]) -> dict[str, Any]:
    for key in _DEMO_PROVENANCE_FIELDS:
        result.pop(key, None)
    return result


def _has_explicit_demo_source(result: dict[str, Any]) -> bool:
    return str(result.get("data_source_type") or "").strip().lower() in _DEMO_SOURCE_TYPES


def _render_input(result: dict[str, Any]) -> dict[str, Any]:
    if not _PRODUCTION_FEISHU_RENDER.get() and _has_explicit_demo_source(result):
        return result
    return _strip_demo_provenance(dict(result))


def _patch_router(router: Any) -> None:
    original_safe: Callable[..., dict[str, Any]] = router.safe_route_feishu_command
    if getattr(original_safe, "_production_output_boundary_patch", False):
        return

    original_render = router.render_feishu_output
    original_payload = router.build_feishu_send_payload

    def render_feishu_output(result: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        return original_render(_render_input(result), *args, **kwargs)

    def build_feishu_send_payload(result: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
        return original_payload(_render_input(result), *args, **kwargs)

    def safe_route_feishu_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
        production_feishu = bool(kwargs.get("production_feishu", False))
        token = _PRODUCTION_FEISHU_RENDER.set(production_feishu)
        try:
            result = original_safe(*args, **kwargs)
        finally:
            _PRODUCTION_FEISHU_RENDER.reset(token)
        if isinstance(result, dict) and (
            production_feishu or not _has_explicit_demo_source(result)
        ):
            _strip_demo_provenance(result)
        return result

    safe_route_feishu_command._production_output_boundary_patch = True  # type: ignore[attr-defined]
    router.render_feishu_output = render_feishu_output
    router.build_feishu_send_payload = build_feishu_send_payload
    router.safe_route_feishu_command = safe_route_feishu_command


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from runtime import feishu_command_router as router

    _patch_router(router)
    _INSTALLED = True
