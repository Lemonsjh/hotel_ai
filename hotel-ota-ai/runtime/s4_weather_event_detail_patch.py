from __future__ import annotations

from typing import Any, Mapping


_INSTALLED = False
VERSION = "s4-weather-event-detail.v1"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _display_value(value: Any, suffix: str = "") -> str | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{value}{suffix}"
    rendered = str(int(number)) if number.is_integer() else f"{number:.1f}".rstrip("0").rstrip(".")
    return f"{rendered}{suffix}"


def _weather_line(weather: Mapping[str, Any]) -> str:
    summary = (
        weather.get("weather_summary")
        or weather.get("weather_text")
        or weather.get("weather_context")
        or "天气详情不可用"
    )
    details: list[str] = []
    temperature = _display_value(weather.get("temperature_c"), "℃")
    apparent = _display_value(weather.get("apparent_temperature_c"), "℃")
    precipitation = _display_value(weather.get("precipitation_mm"), "mm")
    wind = _display_value(weather.get("wind_speed_kmh"), "km/h")
    if temperature:
        details.append(f"气温 {temperature}")
    if apparent:
        details.append(f"体感 {apparent}")
    if precipitation:
        details.append(f"降水 {precipitation}")
    if wind:
        details.append(f"风速 {wind}")
    risk = weather.get("weather_risk_level") or "-"
    signal = weather.get("weather_signal") or "-"
    suffix = f"；{'，'.join(details)}" if details else ""
    return f"天气：{summary}{suffix}；信号 {signal}，风险 {risk}"


def _event_detail_lines(events: Mapping[str, Any]) -> list[str]:
    count = events.get("local_event_count") or 0
    heat = events.get("event_heat_level") or "-"
    lines = [f"周边活动：{count} 个，热度等级 {heat}"]
    rows = events.get("events")
    if not isinstance(rows, list):
        return lines
    for item in rows[:5]:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("event_name") or item.get("name") or "").strip()
        if not name:
            continue
        details: list[str] = []
        date = item.get("date")
        location = item.get("location")
        distance = _display_value(item.get("distance_km"), "km")
        expected_heat = item.get("expected_heat")
        if date:
            details.append(str(date))
        if location:
            details.append(str(location))
        if distance:
            details.append(f"距酒店 {distance}")
        if expected_heat and expected_heat != "unknown":
            details.append(f"预计热度 {expected_heat}")
        suffix = f"（{'，'.join(details)}）" if details else ""
        lines.append(f"- {name}{suffix}")
    return lines


def render_s4_weather_event_details(
    base_text: str,
    result: Mapping[str, Any],
) -> str:
    lines = str(base_text).splitlines()
    weather = _mapping(result.get("weather_context"))
    events = _mapping(result.get("event_context"))

    output: list[str] = []
    weather_replaced = False
    event_replaced = False
    for line in lines:
        if line.startswith("天气信号：") and weather:
            output.append(_weather_line(weather))
            weather_replaced = True
            continue
        if line.startswith("周边活动：") and events:
            output.extend(_event_detail_lines(events))
            event_replaced = True
            continue
        output.append(line)

    boundary_index = len(output)
    for index, line in enumerate(output):
        if line.startswith("S4 只提供"):
            boundary_index = index
            break
    if weather and not weather_replaced:
        output.insert(boundary_index, _weather_line(weather))
        boundary_index += 1
    if events and not event_replaced:
        detail_lines = _event_detail_lines(events)
        output[boundary_index:boundary_index] = detail_lines
    return "\n".join(output)


def install_s4_weather_event_detail_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from runtime import s4_market_heat_contract_patch as s4_module

    previous = s4_module.render_s4_market_text
    if getattr(previous, "_s4_weather_event_detail", False):
        _INSTALLED = True
        return

    def render_s4_market_text(result: Mapping[str, Any]) -> str:
        return render_s4_weather_event_details(previous(result), result)

    render_s4_market_text._s4_weather_event_detail = True  # type: ignore[attr-defined]
    s4_module.render_s4_market_text = render_s4_market_text
    _INSTALLED = True
