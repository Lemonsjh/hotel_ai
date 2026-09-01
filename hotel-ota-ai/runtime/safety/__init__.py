"""Auth, approval, and safety guard helpers."""

from __future__ import annotations

import sys
from typing import Any

from runtime.adapters import database as _database
from runtime.safety import auth as _auth

# S6 price execution ends at the approved task outbox. Operators may submit a
# confirmed price task, but this does not grant generic live-write or
# live-approval permission for other actions.
_auth.PERMISSIONS_BY_ROLE["operator"].add("enqueue_price_task")

# The S6 fast-confirm path historically called database_template_result with
# legacy product-filter kwargs (channel / ota_product_id). The canonical
# database adapter accepts source_platform and the caller already filters the
# returned rows by ota_product_id, so normalize only this legacy S6 call shape.
_S6_DATABASE_TEMPLATE_RESULT_BASE = _database.database_template_result


def _s6_database_template_result_compat(*args: Any, **kwargs: Any) -> dict[str, Any]:
    template = args[0] if args else kwargs.get("template")
    if template == "ota_price_mapping":
        channel = kwargs.pop("channel", None)
        kwargs.pop("ota_product_id", None)
        if channel and not kwargs.get("source_platform"):
            kwargs["source_platform"] = channel
    return _S6_DATABASE_TEMPLATE_RESULT_BASE(*args, **kwargs)


_s6_database_template_result_compat._S6_QUERY_FILTER_COMPAT_V1 = True  # type: ignore[attr-defined]
_database.database_template_result = _s6_database_template_result_compat

# feishu_command_router imports database_template_result before runtime.safety,
# so refresh that already-bound reference during its module initialization.
_router = sys.modules.get("runtime.feishu_command_router")
if _router is not None and hasattr(_router, "database_template_result"):
    _router.database_template_result = _s6_database_template_result_compat

del _auth
del _database
del _router
del sys
