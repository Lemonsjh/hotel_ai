from __future__ import annotations

from typing import Any, Mapping

_INSTALLED = False
VERSION = "s15-complete-matrix.v3"


_MATRIX = (
    "全店最终销售目标",
    "房型最终销售目标",
    "全店小时销售进度",
    "房型小时销售进度",
    "大盘订单基准（估算）",
    "本店市场份额基准（估算）",
    "浏览基准（日级）",
    "一转基准（日级）",
    "二转基准（日级+滚动30日同行背景）",
    "房型历史价格基准",
    "引流价及排名基准（日级）",
    "携程相关基准",
)


def _ctrip_section(payload: Mapping[str, Any]) -> list[str]:
    identity_verified = bool(
        payload.get("ctrip_identity_verified")
        or (
            (payload.get("ctrip_identity_consistency") or {}).get("status")
            == "verified"
        )
    )
    canonical_verified = bool(
        payload.get("ctrip_canonical_mapping_verified")
        or (
            (payload.get("ctrip_mapping_consistency") or {}).get("status")
            == "verified"
        )
    )
    ctrip = ((payload.get("ota_baselines") or {}).get("ctrip")) or {}
    if identity_verified and canonical_verified and ctrip:
        selected_dates = ctrip.get("selected_dates") or []
        baselines = ctrip.get("baselines") or {}
        return [
            "十二、携程相关基准",
            "- 酒店主体和 canonical 房型映射已通过验证，可按携程自身口径独立展示。",
            f"- 历史选中样本 {len(selected_dates)} 天；可用指标族 {len(baselines)} 个。",
            "- 携程与美团口径保持分离，不跨平台相加或混算。",
        ]
    return [
        "十二、携程相关基准",
        "- 当前整组禁用：酒店主体一致性或 canonical 房型映射未通过验证。",
        "- 不参与本酒店大盘、份额、流量、转化、价格比较或动作判断；不跨酒店借数。",
    ]


def _apply_matrix_contract(base: str, payload: Mapping[str, Any]) -> str:
    text = base.replace(
        "一、销售进度基准线（全店）",
        "一、销售进度基准线（全店）｜全店最终销售目标与全店小时销售进度",
    ).replace(
        "二、销售进度基准线（全部房型）",
        "二、销售进度基准线（全部房型）｜房型最终销售目标与房型小时销售进度",
    )
    header = [
        "基准线完整性清单：" + "；".join(_MATRIX) + "。",
        "以下各项即使不可用也保留段落并说明原因，不静默省略。",
        "",
    ]
    if "十二、携程相关基准" not in text:
        text += "\n\n" + "\n".join(_ctrip_section(payload))
    return "\n".join(header) + text


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s15_s16_complete_output_patch
    from runtime.sales_progress import presentation

    previous = s15_s16_complete_output_patch.s15_message
    if getattr(previous, "_S15_MATRIX_CONTRACT_V3", False):
        return

    def s15_message(payload: Mapping[str, Any]) -> str:
        return _apply_matrix_contract(previous(payload), payload)

    s15_message._S15_MATRIX_CONTRACT_V3 = True  # type: ignore[attr-defined]
    s15_s16_complete_output_patch.s15_message = s15_message
    presentation.build_s15_user_message = s15_message
