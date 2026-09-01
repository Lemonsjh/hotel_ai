#!/usr/bin/env bash
set -euo pipefail

service_name="${1:-openclaw-gateway.service}"
config_path="${2:-/root/.openclaw/openclaw.json}"
agent_id="${3:-hotel-ota-chief}"

pid="$(systemctl show "$service_name" --property=MainPID --value)"
if [[ ! "$pid" =~ ^[1-9][0-9]*$ ]] || [[ ! -r "/proc/$pid/environ" ]]; then
  echo "gateway_plugin_environment: unavailable"
  exit 1
fi

actual="$({ tr '\0' '\n' < "/proc/$pid/environ" || true; } | awk -F= '/^HOTEL_OTA_FEISHU_AUTH_ACCOUNTS=/{print $2}' | tr ',' '\n' | sed '/^[[:space:]]*$/d' | sort | paste -sd, -)"
expected="$(jq -r --arg agent "$agent_id" '.bindings[] | select(.type == "route" and .agentId == $agent and .match.channel == "feishu") | .match.accountId' "$config_path" | sort | paste -sd, -)"

if [[ -z "$actual" ]]; then
  echo "gateway_plugin_account_variable: missing"
  exit 1
fi

actual_count="$(tr ',' '\n' <<< "$actual" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"
if [[ "$actual_count" != "2" ]]; then
  echo "gateway_plugin_account_count: $actual_count (expected 2)"
  exit 1
fi

if [[ "$actual" != "$expected" ]]; then
  echo "gateway_plugin_account_set: mismatch"
  exit 1
fi

echo "gateway_plugin_account_variable: present"
echo "gateway_plugin_account_count: 2"
echo "gateway_plugin_account_set: matches_hotel_agent_bindings"
