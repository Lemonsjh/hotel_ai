from __future__ import annotations

import sys
from typing import Any

_INSTALLED = False
_S15_S16_INTENTS = {"sales_baseline_demo", "progress_deviation_demo"}


def remove_duplicate_summary(compact: dict[str, Any]) -> dict[str, Any]:
    result = dict(compact)
    if result.get("intent") not in _S15_S16_INTENTS:
        return result
    payload = result.get("send_payload")
    if not isinstance(payload, dict):
        return result
    text = payload.get("text")
    if text and result.get("summary") == text:
        result.pop("summary", None)
        result["summary_omitted_reason"] = (
            "identical_to_send_payload_text"
        )
    return result


def _patch_router_module(module: Any) -> None:
    if getattr(module, "_S15_S16_COMPACT_OUTPUT_PATCHED", False):
        return
    original = module.compact_feishu_route_result

    def compact_feishu_route_result(
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return remove_duplicate_summary(original(result))

    module.compact_feishu_route_result = compact_feishu_route_result
    module._S15_S16_COMPACT_OUTPUT_PATCHED = True


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime import live_contract_patch

    previous_apply = live_contract_patch._apply_patch

    def apply_patch(module: Any) -> None:
        previous_apply(module)
        if module.__name__ == "runtime.feishu_command_router":
            _patch_router_module(module)

    live_contract_patch._apply_patch = apply_patch
    existing = sys.modules.get("runtime.feishu_command_router")
    if existing is not None:
        _patch_router_module(existing)
