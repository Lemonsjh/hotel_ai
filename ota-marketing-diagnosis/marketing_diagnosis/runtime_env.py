from __future__ import annotations

import os
from pathlib import Path


_S14_ENV_KEYS = {
    "S14_DB_DSN",
    "S14_CTRIP_HOTEL_ID",
    "S14_REPORT_OUTPUT_DIR",
    "S14_PUBLIC_BASE_URL",
}


def load_local_s14_env() -> None:
    """Load local S14 settings without overriding a deployed environment."""

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in _S14_ENV_KEYS or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
