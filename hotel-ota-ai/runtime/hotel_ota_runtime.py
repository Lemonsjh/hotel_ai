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
    # Force UTF-8 on stdout/stderr so emoji and Chinese in runtime output do
    # not crash on Windows' default GBK codec. The plugin path already sets
    # PYTHONUTF8=1 when spawning, but the LLM/agent path invokes this CLI
    # directly and previously hit `UnicodeEncodeError: 'gbk' codec can't
    # encode '\U0001f3e8'`.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    raise SystemExit(main())
