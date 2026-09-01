#!/usr/bin/env sh
set -eu

if [ "${1:-}" != "--dry-run" ]; then
  echo "usage: $0 --dry-run" >&2
  exit 64
fi

service_user="${HOTEL_OTA_GATEWAY_USER:-openclaw}"
role_map="${HOTEL_OTA_AUTH_CONFIG:-/etc/hotel-ota-ai/feishu-role-map.json}"
market_config="${HOTEL_OTA_MARKET_SOURCE_CONFIG:-/etc/hotel-ota-ai/market-source.json}"
db_path="${HOTEL_OTA_DB:-/var/lib/hotel-ota-ai/hotel_ops.sqlite}"

status=0
check_path() {
  label="$1"
  path="$2"
  if [ -e "$path" ]; then
    echo "ok: $label exists"
  else
    echo "missing: $label" >&2
    status=1
  fi
}

if id "$service_user" >/dev/null 2>&1; then
  echo "ok: service user exists"
else
  echo "missing: service user" >&2
  status=1
fi
check_path "role map" "$role_map"
check_path "market config" "$market_config"
check_path "database directory" "$(dirname "$db_path")"
check_path "runtime entry" "${HOTEL_OTA_RUNTIME_ENTRY:-/opt/openclaw/workspaces/hotel-ota-ai/runtime/hotel_ota_runtime.py}"
check_path "python entry" "${HOTEL_OTA_PYTHON:-/opt/openclaw/workspaces/hotel-ota-ai/.venv/bin/python}"

if [ "$status" -eq 0 ]; then
  echo "preflight passed: no files, users, permissions, or services were changed"
else
  echo "preflight failed: no files, users, permissions, or services were changed" >&2
fi
exit "$status"
