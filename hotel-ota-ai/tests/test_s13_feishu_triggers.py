from runtime.s13.feishu import _parse_action, _render, is_s13_message


def test_documented_s13_entry_phrases_are_routable():
    assert is_s13_message("生成回复")
    assert is_s13_message("回复任务状态")
    assert _parse_action("生成回复") == ("list_pending", {})
    assert _parse_action("回复任务状态") == ("status_help", {})


def test_s13_entry_phrases_preserve_opaque_refs():
    review_ref = "REV-example_123"
    request_id = "REQ-example_123"

    assert _parse_action(f"生成回复 {review_ref}") == (
        "generate_draft",
        {"review_ref": review_ref},
    )
    assert _parse_action(f"回复任务状态 {request_id}") == (
        "query_status",
        {"request_id": request_id},
    )
    assert _parse_action(f"回复任务状态 {review_ref}") == (
        "query_status",
        {"review_ref": review_ref},
    )


def test_existing_s13_aliases_remain_routable():
    assert is_s13_message("生成评论回复")
    assert is_s13_message("评论回复任务状态")
    assert _parse_action("生成评论回复") == ("list_pending", {})
    assert _parse_action("评论回复任务状态") == ("status_help", {})


def test_status_help_requires_opaque_reference():
    text = _render(
        {
            "status": "needs_reference",
            "action": "status_help",
            "blocked_reason": "reply_status_reference_required",
        }
    )
    assert "REQ-*" in text
    assert "REV-*" in text
