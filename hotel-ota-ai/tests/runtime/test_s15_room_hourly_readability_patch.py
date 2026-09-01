from __future__ import annotations

from runtime.s15_room_hourly_readability_patch import (
    readable_room_hourly_block,
    replace_room_hourly_block,
)


def _payload() -> dict:
    hours = [9, 12, 14, 16, 18, 20, 22]
    hotel_points = []
    room_points = []
    for index, hour in enumerate(hours):
        hotel_points.append(
            {
                "hour": hour,
                "exact_sample_count": 12 - index,
                "fallback_sample_count": index % 2,
                "target_completion": {"sample_count": 12, "median": index / 10},
                "capacity": {"sample_count": 12, "median": index / 10},
            }
        )
        room_points.append(
            {
                "hour": hour,
                "exact_sample_count": 12 - index,
                "fallback_sample_count": index % 2,
                "target_completion": {"sample_count": 12, "median": (index + 1) / 10},
                "capacity": {"sample_count": 12, "median": (index + 1) / 12},
            }
        )
    return {
        "as_of_datetime": "2026-08-06T14:10:00+08:00",
        "hotel": {"hourly_points": hotel_points},
        "room_types": {
            "r1": {"room_type_name": "电竞大床房", "hourly_points": room_points}
        },
    }


def test_room_hourly_output_is_readable_and_samples_are_summarized_once() -> None:
    text = readable_room_hourly_block(_payload())
    assert "二、各房型历史小时销售进度" in text
    assert "电竞大床房：09点 10% → 12点 20% → 14点 30%" in text
    assert "样本质量（以上房型共用）" in text
    assert "容量线/最终完成线/精确小时样本" not in text
    assert " 容" not in text and "/完" not in text and "/精" not in text


def test_old_dense_room_block_is_replaced() -> None:
    old = (
        "一、目标\n\n二、全部房型小时销售进度（优先保留）\n"
        "- 格式：容量线/最终完成线/精确小时样本。\n"
        "- 电竞大床房：09 容10%/完20%/精12\n\n"
        "三、全店小时销售基准\n- 09:00"
    )
    text = replace_room_hourly_block(old, _payload())
    assert "二、各房型历史小时销售进度" in text
    assert "09 容10%" not in text
    assert "三、全店小时销售基准" in text
