from __future__ import annotations

from typing import Any, Callable

_INSTALLED = False
VERSION = "s2-daily-report-route.v1"


def _normalize(message: Any) -> str:
    text = str(message or "").strip().lower()
    for char in " \t\r\n，。！？、；：,.!?;:":
        text = text.replace(char, "")
    return text


_TODAY_REPORT_CORES = tuple(
    _normalize(item)
    for item in (
        "今日日报",
        "今天日报",
        "今日经营日报",
        "今天经营日报",
    )
)

_YESTERDAY_REPORT_CORES = tuple(
    _normalize(item)
    for item in (
        "昨日日报",
        "昨天日报",
        "昨日经营日报",
        "昨天经营日报",
    )
)


def daily_report_scope(message: Any) -> str | None:
    """Return ``today``/``yesterday`` for generic S2 daily-report requests.

    The match is intentionally narrow.  ``今日市场日报`` and ``昨日推广日报``
    are not generic S2 operating reports because the domain word breaks the
    supported report core.
    """
    normalized = _normalize(message)
    matches: list[tuple[int, str]] = []
    for core in _TODAY_REPORT_CORES:
        position = normalized.find(core)
        if position >= 0:
            matches.append((position, "today"))
    for core in _YESTERDAY_REPORT_CORES:
        position = normalized.find(core)
        if position >= 0:
            matches.append((position, "yesterday"))
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def is_s2_daily_report_request(message: Any) -> bool:
    return daily_report_scope(message) is not None


def _wrap_s14_main_request(previous: Callable[[Any], bool]) -> Callable[[Any], bool]:
    def _is_main_s14_request(message: Any) -> bool:
        # S14 retirement historically caught the broad token “经营日报”.  The
        # explicit today/yesterday operating report is now owned by S2, so it
        # must pass through the retirement wrapper instead of being blocked.
        if is_s2_daily_report_request(message):
            return False
        return previous(message)

    _is_main_s14_request._S2_DAILY_REPORT_ROUTE_V1 = True  # type: ignore[attr-defined]
    return _is_main_s14_request


def _wrap_intent_detector(previous: Callable[[str], str]) -> Callable[[str], str]:
    def detect_intent(message: str) -> str:
        if is_s2_daily_report_request(message):
            return "run_s02_demo"
        return previous(message)

    # Preserve wrapper markers used by existing route-regression tests while
    # making the S2 daily-report rule the final detector owner.
    detect_intent._S2_DAILY_REPORT_ROUTE_V1 = True  # type: ignore[attr-defined]
    detect_intent._S14_PRODUCTION_RETIRED_V1 = bool(  # type: ignore[attr-defined]
        getattr(previous, "_S14_PRODUCTION_RETIRED_V1", False)
    )
    detect_intent._P0_ROUTE_OWNERSHIP_V1 = bool(  # type: ignore[attr-defined]
        getattr(previous, "_P0_ROUTE_OWNERSHIP_V1", False)
    )
    detect_intent._P0_ROUTE_OWNERSHIP_V2 = bool(  # type: ignore[attr-defined]
        getattr(previous, "_P0_ROUTE_OWNERSHIP_V2", False)
    )
    return detect_intent


def _wrap_time_resolver(previous: Callable[..., dict[str, str]]) -> Callable[..., dict[str, str]]:
    def resolve_request_as_of_time(
        message: str | None,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, str]:
        scope = daily_report_scope(message)
        if scope is None:
            return previous(message, *args, **kwargs)

        # The report phrase owns the business date.  Canonicalizing the input
        # prevents “今日日报，对比昨日” from accidentally switching the target
        # date, while retaining an explicitly written clock time.
        from runtime.time_context import normalize_as_of_time

        canonical = "今天" if scope == "today" else "昨天"
        explicit_clock = normalize_as_of_time(message)
        if explicit_clock:
            canonical = f"{canonical} {explicit_clock}"
        return previous(canonical, *args, **kwargs)

    resolve_request_as_of_time._S2_DAILY_REPORT_ROUTE_V1 = True  # type: ignore[attr-defined]
    return resolve_request_as_of_time


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router
    from runtime import s14_retirement_patch as s14_retirement

    previous_s14_match = s14_retirement._is_main_s14_request
    if not getattr(previous_s14_match, "_S2_DAILY_REPORT_ROUTE_V1", False):
        s14_retirement._is_main_s14_request = _wrap_s14_main_request(previous_s14_match)

    previous_detect = router._detect_intent
    if not getattr(previous_detect, "_S2_DAILY_REPORT_ROUTE_V1", False):
        router._detect_intent = _wrap_intent_detector(previous_detect)

    previous_time = router.resolve_request_as_of_time
    if not getattr(previous_time, "_S2_DAILY_REPORT_ROUTE_V1", False):
        router.resolve_request_as_of_time = _wrap_time_resolver(previous_time)

    router.S2_DAILY_REPORT_ROUTE_VERSION = VERSION
