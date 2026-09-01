#!/usr/bin/env bash
set -euo pipefail

# Run from the OpenClaw workspace root on the Alibaba server.
#
# IMPORTANT: this file is only an operator reference for installing local
# OpenClaw cron jobs. It is NOT evidence that the server currently has these
# jobs installed, that a run succeeded, or that a Feishu message was delivered.
# Before any Feishu delivery task is created or changed, follow
# SCHEDULED_TASK_POLICY.md: resolve the trusted chat_id and the actual bot/app/
# account for that group, perform the real scheduler mutation, then read it back.
#
# S2 scheduled pushes are intentionally absent. The previous agentTurn/system-
# event cron can time out at model-call-started, and the project does not deploy
# a replacement timer by default. Do not claim that an S2 group push exists
# unless the live scheduler has been queried and verified.

openclaw cron add \
  --name "S15 daily sales baseline" \
  --cron "30 7 * * *" \
  --tz "Asia/Shanghai" \
  --session main \
  --system-event "Run /skill s15-sales-baseline for hotel_id=puyue and today's business date. Persist the baseline and send the daily target summary."

openclaw cron add \
  --name "S16 hourly deviation diagnosis" \
  --cron "12 * * * *" \
  --tz "Asia/Shanghai" \
  --session main \
  --system-event "Run /skill s16-progress-deviation for hotel_id=puyue. Compare current progress with baseline and send actionable deviations."

# S14 main diagnosis is retired. Do not install or recreate an S14 cron here.

openclaw cron list
