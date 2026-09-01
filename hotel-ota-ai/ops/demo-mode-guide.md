# Demo Mode Guide

Enable Demo Mode with `HOTEL_OTA_DEMO_MODE=1` or the runtime `--demo` flag where supported.

Demo Mode exists to run SC01-SC10 without production PMS/OTA/API/database data. It must always mark output as `demo_data`, `approval_data_allowed=false`, and `live_allowed=false`.

Allowed: diagnosis preview, message preview, dry-run request preview, external report preview, experience candidate preview.

Blocked: formal approval creation, live API write, production role-map mutation, private config export, claiming demo data is real current business data.
