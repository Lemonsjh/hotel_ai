from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from marketing_diagnosis.reporting_v6 import _json_default


def test_json_default_serializes_database_native_values():
    payload = {
        "period_start_date": date(2026, 6, 21),
        "snapshot_time": datetime(2026, 7, 20, 12, 30, 45),
        "amount": Decimal("123.45"),
    }

    encoded = json.dumps(payload, ensure_ascii=False, default=_json_default)
    decoded = json.loads(encoded)

    assert decoded["period_start_date"] == "2026-06-21"
    assert decoded["snapshot_time"] == "2026-07-20T12:30:45"
    assert decoded["amount"] == 123.45
