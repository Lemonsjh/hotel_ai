from __future__ import annotations

import ast
from pathlib import Path


S11_PATCH = Path(__file__).resolve().parents[1] / "runtime" / "s11_readonly_plan_patch.py"


def test_s11_calls_s16_progress_with_keyword_only_contract() -> None:
    tree = ast.parse(S11_PATCH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_query_s16_progress"
    ]

    assert len(calls) == 1
    call = calls[0]
    assert call.args == []
    assert [keyword.arg for keyword in call.keywords] == [
        "hotel_id",
        "target_stay_date",
        "as_of_time",
        "db_path",
    ]
