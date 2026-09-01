from runtime.s16_skill_delivery_patch import (
    _replace_room_structure_section,
    build_s16_response_contract,
    render_complete_room_structure,
)


def _report() -> dict:
    statuses = [
        "fast",
        "normal",
        "significant_slow",
        "normal",
        "slow",
        "normal",
        "significant_fast",
        "normal",
        "sample_insufficient",
        "normal",
    ]
    rows = []
    for index, status in enumerate(statuses, start=1):
        sold = 0 if index in {4, 9} else index % 5
        total = 6 + index
        expected = index / 2
        gap = sold - expected
        delta_pp = 0.0 if status == "normal" else float(index)
        rows.append(
            {
                "room_type_id": f"room-{index:02d}",
                "room_type_name": f"测试房型{index:02d}",
                "committed_sold": sold,
                "total_rooms": total,
                "current_expected_sold": expected,
                "checkpoint_room_gap": gap,
                "sales_progress_delta_pp": delta_pp,
                "sales_status": status,
            }
        )
    return {
        "intent": "progress_deviation_demo",
        "dynamic_diagnosis": {
            "room_structure": {
                "room_type_results": rows,
            }
        },
    }


def test_room_structure_keeps_every_room_even_when_more_than_eight() -> None:
    report = _report()
    source = "\n".join(
        [
            "一、当前结论",
            "- 示例",
            "",
            "三、房型结构",
            "- 旧的异常房型摘要",
            "",
            "四、原因判断",
            "- 示例原因",
        ]
    )

    rendered = _replace_room_structure_section(source, report)

    for index in range(1, 11):
        assert f"测试房型{index:02d}" in rendered
    assert rendered.count("已售 ") == 10
    assert "测试房型04：已售 0/10间" in rendered
    assert "测试房型02" in rendered and "正常。" in rendered
    assert "测试房型09：已售 0/15间" in rendered
    assert "样本不足。" in rendered
    assert "测试房型10" in rendered
    assert "旧的异常房型摘要" not in rendered


def test_room_structure_preserves_pp_for_normal_and_abnormal_rooms() -> None:
    text = render_complete_room_structure(_report())

    assert "测试房型01" in text
    assert "进度偏差 +1.0个百分点，偏快。" in text
    assert "测试房型02" in text
    assert "进度偏差 +0.0个百分点，正常。" in text
    assert "测试房型03" in text
    assert "进度偏差 +3.0个百分点，明显偏慢。" in text


def test_response_contract_locks_full_room_structure() -> None:
    contract = build_s16_response_contract(_report())

    assert contract["room_type_count"] == 10
    assert contract["all_room_type_ids"] == [
        f"room-{index:02d}" for index in range(1, 11)
    ]
    assert contract["must_preserve_all_room_types"] is True
    assert contract["locked_room_structure_must_preserve_verbatim"] is True
    locked = contract["locked_room_structure_text"]
    for index in range(1, 11):
        assert f"测试房型{index:02d}" in locked
