from __future__ import annotations

from pathlib import Path

from runtime.decisions.calendar_seed_source_guard import (
    resolve_holiday_seed_selection,
)


def test_explicit_holiday_seed_path_is_reported(tmp_path: Path) -> None:
    selected, source = resolve_holiday_seed_selection(
        str(tmp_path / "runtime" / "decisions" / "calendar.py"),
        2026,
        str(tmp_path / "custom-seed.json"),
    )

    assert selected == str((tmp_path / "custom-seed.json").resolve())
    assert source == "seed_file:custom-seed.json"


def test_default_holiday_seed_path_is_reported(tmp_path: Path) -> None:
    calendar_file = tmp_path / "runtime" / "decisions" / "calendar.py"
    calendar_file.parent.mkdir(parents=True)
    calendar_file.write_text("", encoding="utf-8")
    seed = tmp_path / "data" / "holiday-seeds" / "holiday-seed-2026.json"
    seed.parent.mkdir(parents=True)
    seed.write_text("{}", encoding="utf-8")

    selected, source = resolve_holiday_seed_selection(
        str(calendar_file),
        2026,
    )

    assert selected == str(seed.resolve())
    assert source == "seed_file:holiday-seed-2026.json"
