from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_sales_progress_shortcuts_route_to_s16() -> None:
    code = """
import runtime
from runtime.feishu_command_router import _detect_intent
for message in ('S16', 's16', 'S16 销售进度', '销售进度', '查看销售进度', '看下销售进度', '看看销售进度'):
    assert _detect_intent(message) == 'progress_deviation_demo', message
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
