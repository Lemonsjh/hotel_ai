# Agent Instructions

This workspace is for S14 OTA marketing diagnosis only.

Rules:
- Default communication language is Chinese.
- Use the project runtime to generate reports. Do not invent scores, report paths, filenames, cards, buttons, or data conclusions.
- Generated reports are runtime artifacts and must be written under `S14_REPORT_OUTPUT_DIR`, not committed to git.
- This project only generates diagnosis reports. It does not write prices, inventory, promotions, or review replies.
- Current reports use the already mapped fields as one overall diagnosis. Never ask the user to choose Meituan, Ctrip, Fliggy, or multi-channel. Internally always use `platform=multi`.
- Never send internal development summaries such as “修复已就绪”, source-code change descriptions, test summaries, or root-cause tables to a normal Feishu user.
- Never send serialized card JSON, source code, command output, or exception tracebacks to a Feishu user. Callback failures must use the fixed bounded Chinese error message.
- Never say “点击上面卡片” unless an interactive card was actually included in the same outbound message.
- Never claim a report was generated unless the runtime returned a real non-empty `report_url`.

## Feishu flow

When the user sends `S14诊断`:

1. Prefer the Skill runtime's `source_selection` result. For an ordinary OpenClaw reply, send only its `feishu_message` field. Never send the complete result object or provider-native `feishu_card` JSON as assistant text.
2. OpenClaw must render rich UI through its own message/presentation layer. When executing the CLI wrapper through a shell/exec tool, always use `--format text` and send that stdout exactly once. It asks the user to type `数据库` or `上传Excel`.
3. For a database choice, invoke the Skill with `data_source_mode=database`, `platform=multi`, or call the same script with `--source-choice database`, using the same chat and sender IDs.
4. For an Excel choice, invoke the Skill with `data_source_mode=excel_pending`, or call the same script with `--source-choice excel`, using the same chat and sender IDs.
5. After Excel is selected, accept the same user's next `.xlsx` or `.xlsm` attachment in the same group without another @ mention. Download it locally and call the script with `--excel`, the same chat ID, the same sender ID, and `--format text`.
6. The pending Excel state expires after 10 minutes. Do not run an attachment diagnosis unless the same chat and sender have selected Excel.
7. Interactive-card callbacks are handled by `scripts/s14_feishu_card_callback.py`. It accepts only action `s14_source`, passes its validated `source` value to the diagnosis entry, and sends the resulting structured card directly with Feishu OpenAPI.
8. After database or Excel diagnosis completes, send `feishu_message` exactly once when using exec/CLI. A dedicated structured adapter may request `--format card --raw-card-json`, parse the JSON, and send it through the channel API; its stdout must never be copied into chat. The result must contain the actual HTML report URL.

Validated command pattern:

```bash
cd /opt/openclaw/workspaces/ota-marketing-diagnosis
source .venv/bin/activate
set -a
source /etc/hotel-ota-ai/hotel-ota.env
set +a
python scripts/s14_feishu_entry.py --text 'S14诊断' --chat-id CHAT_ID --sender-id SENDER_ID --format text
```

Always send the runtime output exactly once. Do not prepend, summarize, repeat, or replace it with an explanation of code changes.

## Current database reporting (multi-hotel · mandatory)

Every Feishu group is bound to exactly one hotel via SQLite
`chat_bindings` / `group_chat_bindings`. When the user asks anything like
“现在连接的是哪个数据库 / 库名告诉我 / db / database”，你必须用下面的命令
确定性解析，而不是自己读环境变量拼答案：

```bash
cd /opt/openclaw/workspaces/ota-marketing-diagnosis
source .venv/bin/activate
set -a
source /etc/hotel-ota-ai/hotel-ota.env
set +a
python scripts/s14_feishu_entry.py --report-current-db --chat-id '<当前群的chat_id>' --format text
```

Rule:
- THE `--chat-id` IS MANDATORY. The exec environment does NOT auto-provide it.
  Fill `<当前群的chat_id>` from your current session (the `groupId` / the
  `to` in `route.target`, e.g. `oc_5dfd742373dcb9997450ef6120965f23` for the
  智町/zhiting group). Never omit it.
- The entry script resolves the current group's bound hotel and returns the
  correct library name automatically (e.g. zhiting group → `hotel_zhiting`,
  puyue group → `hotel_puyue`). Reply with its output verbatim, exactly once.
- If the output ever says `未绑定群` or returns the default, that means the
  `--chat-id` was missing/wrong — rerun with the correct `<当前群的chat_id>`.
- NEVER read or quote the default `S14_DB_DSN` when serving zhiting: that is
  the puyue library. Never repeat stale answers such as `TEST_DB`.
- Never expose credentials; the command already masks them.
- Do not override the command's output with a hotel you “remember”. Multi-hotel
  binding is authoritative.

## Tools

### Local notes (migrated from TOOLS.md)

# Tools

Primary runtime commands:

```bash
python scripts/s14_feishu_entry.py --text 'S14诊断' --format text
```

```bash
ota-marketing-diagnosis diagnose-db --dsn-env S14_DB_DSN --hotel-id puyue --platform multi --output "$S14_REPORT_OUTPUT_DIR"
```

Expected outputs:

- `report.html`
- `report.json`
- `report.md`

Reports are generated under `S14_REPORT_OUTPUT_DIR` in a run-specific directory.
