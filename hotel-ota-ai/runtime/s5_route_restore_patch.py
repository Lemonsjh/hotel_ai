from __future__ import annotations

import re

_INSTALLED = False
VERSION = "s5-direct-pricing-route.v2"

_DIRECT_PRICE_TERMS = (
    "调价吗",
    "调不调价",
    "需要调价吗",
    "是否需要调价",
    "要不要调价",
    "该不该调价",
    "该调价吗",
    "需不需要调价",
    "调价建议",
    "给调价建议",
    "需要涨价吗",
    "是否需要涨价",
    "要不要涨价",
    "需要降价吗",
    "是否需要降价",
    "要不要降价",
    "该涨还是该降",
    "涨还是降",
    "价格要不要动",
    "房价要不要调",
    "房价该怎么调",
    "哪些房型需要调价",
    "哪些商品需要调价",
)

_DIAGNOSIS_CONTEXT_TERMS = (
    "为什么",
    "原因",
    "销售落后",
    "销售偏慢",
    "进度落后",
    "经营怎么样",
    "经营好不好",
    "大盘",
    "份额",
    "浏览",
    "一转",
    "二转",
    "转化",
    "是不是价格导致",
    "价格是不是原因",
)

_EXECUTION_TERMS = (
    "dry-run",
    "dry run",
    "调价预览",
    "执行预览",
    "确认执行",
    "立即执行",
    "同步房价",
    "创建任务",
    "提交审批",
)


def _normalize(message: str) -> str:
    text = str(message or "").strip().lower()
    return re.sub(r"[\s，。！？、；：,.!?;:]+", "", text)


def is_direct_s5_pricing_request(message: str) -> bool:
    raw = str(message or "")
    normalized = _normalize(raw)
    if not normalized:
        return False
    if any(_normalize(term) in normalized for term in _EXECUTION_TERMS):
        return False
    if "s16" in normalized and ("分析" in normalized or "诊断" in normalized):
        return False
    direct = any(_normalize(term) in normalized for term in _DIRECT_PRICE_TERMS)
    if not direct:
        return False
    return not any(_normalize(term) in normalized for term in _DIAGNOSIS_CONTEXT_TERMS)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router

    previous = router._detect_intent
    if getattr(previous, "_S5_DIRECT_PRICING_ROUTE_V2", False):
        return

    def detect_intent(message: str) -> str:
        if is_direct_s5_pricing_request(message):
            return "revenue_decision"
        return previous(message)

    detect_intent._S5_DIRECT_PRICING_ROUTE_V2 = True  # type: ignore[attr-defined]
    router._detect_intent = detect_intent
