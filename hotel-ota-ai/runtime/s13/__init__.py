"""MD-aligned S13 review reply runtime."""

from runtime.s13.contracts import RequestContext, ReviewRecord, TaskRecord
from runtime.s13.service import S13Service
from runtime.s13.dianping_task_contract_patch import install as _install_dianping_task_contract_patch
from runtime.s13_feishu_route_fix_patch import install as _install_s13_feishu_route_fix_patch


_install_dianping_task_contract_patch()
_install_s13_feishu_route_fix_patch()

del _install_dianping_task_contract_patch
del _install_s13_feishu_route_fix_patch

__all__ = ["RequestContext", "ReviewRecord", "TaskRecord", "S13Service"]
