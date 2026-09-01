from __future__ import annotations

from runtime.s4_weather_event_detail_patch import (
    render_s4_weather_event_details,
)


def test_s4_weather_and_event_details_are_rendered() -> None:
    rendered = render_s4_weather_event_details(
        "\n".join(
            [
                "S4 环境行情感知",
                "天气信号：neutral（风险 low）",
                "周边活动：2 个，热度等级 medium",
                "S4 只提供只读行情信号，不直接触发调价。",
            ]
        ),
        {
            "weather_context": {
                "weather_summary": "partly_cloudy",
                "temperature_c": 26,
                "apparent_temperature_c": 27.5,
                "precipitation_mm": 0,
                "wind_speed_kmh": 8,
                "weather_signal": "neutral",
                "weather_risk_level": "low",
            },
            "event_context": {
                "local_event_count": 2,
                "event_heat_level": "medium",
                "events": [
                    {
                        "event_name": "音乐节",
                        "date": "2026-08-06",
                        "location": "花溪公园",
                        "distance_km": 1.2,
                        "expected_heat": "high",
                    }
                ],
            },
        },
    )

    assert "天气：partly_cloudy" in rendered
    assert "气温 26℃" in rendered
    assert "体感 27.5℃" in rendered
    assert "周边活动：2 个，热度等级 medium" in rendered
    assert "- 音乐节（2026-08-06，花溪公园，距酒店 1.2km，预计热度 high）" in rendered
