#!/usr/bin/env python3
"""Controlled CLI entrypoint for Hotel OTA capabilities."""

from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_PARENT = Path(__file__).resolve().parents[1]
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from runtime.feishu_calendar_scope_patch import install as _install_feishu_calendar_scope_patch
from runtime.feishu_role_command_patch import install as _install_feishu_role_command_patch

_install_feishu_calendar_scope_patch()
_install_feishu_role_command_patch()
del _install_feishu_calendar_scope_patch
del _install_feishu_role_command_patch

from runtime.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
