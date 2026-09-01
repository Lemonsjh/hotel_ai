from __future__ import annotations

from pathlib import Path


def test_static_cron_does_not_install_retired_s14() -> None:
    text = (Path(__file__).resolve().parents[1] / "cron" / "setup-cron.sh").read_text(
        encoding="utf-8"
    )
    active_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert all("s14-operation-diagnosis" not in line.lower() for line in active_lines)
    assert all("s14 weekly operation diagnosis" not in line.lower() for line in active_lines)


def test_cron_reference_disclaims_scheduler_and_delivery_truth() -> None:
    text = (Path(__file__).resolve().parents[1] / "cron" / "setup-cron.sh").read_text(
        encoding="utf-8"
    )
    assert "NOT evidence that the server currently has these" in text
    assert "SCHEDULED_TASK_POLICY.md" in text
    assert "actual bot/app/" in text
