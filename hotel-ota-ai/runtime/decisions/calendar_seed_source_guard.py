from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Any


_INSTALLED = False


def resolve_holiday_seed_selection(
    calendar_file: str,
    year: int,
    seed_file: str | None = None,
) -> tuple[str | None, str]:
    if seed_file:
        selected = Path(seed_file).expanduser().resolve()
        return str(selected), f"seed_file:{selected.name}"

    default_seed = (
        Path(calendar_file).resolve().parents[2]
        / "data"
        / "holiday-seeds"
        / f"holiday-seed-{year}.json"
    )
    if default_seed.exists():
        selected = default_seed.resolve()
        return str(selected), f"seed_file:{selected.name}"
    return None, "builtin_project_seed"


def install_calendar_seed_source_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from runtime.decisions import calendar as calendar_module

    previous = calendar_module.sync_calendar_year
    if getattr(previous, "_calendar_seed_source_guard", False):
        _INSTALLED = True
        return

    @wraps(previous)
    def sync_calendar_year(
        db_path: str,
        year: int,
        seed_file: str | None = None,
    ) -> dict[str, Any]:
        selected_seed_file, seed_source = resolve_holiday_seed_selection(
            calendar_module.__file__,
            year,
            seed_file,
        )
        result = previous(db_path, year, seed_file)
        if not isinstance(result, dict):
            return result
        copied = dict(result)
        copied["seed_file"] = selected_seed_file
        copied["seed_source"] = seed_source
        return copied

    sync_calendar_year._calendar_seed_source_guard = True  # type: ignore[attr-defined]
    calendar_module.sync_calendar_year = sync_calendar_year
    _INSTALLED = True
