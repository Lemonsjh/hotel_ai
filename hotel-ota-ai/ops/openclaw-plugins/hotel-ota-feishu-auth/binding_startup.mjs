import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { SQLITE_BINDING_QUERY, syncConversationBindings } from "./lib/binding_sync.mjs";

const PLUGIN_ROOT = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_RUNTIME_MODULE = "/usr/local/lib/node_modules/openclaw/dist/plugin-sdk/conversation-runtime.js";

function targetAccounts() {
  return (process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

function databasePath() {
  return process.env.HOTEL_OTA_DB || "/var/lib/hotel-ota-ai/hotel_ops.sqlite";
}

function authConfigPath() {
  return process.env.HOTEL_OTA_AUTH_CONFIG || "/etc/hotel-ota-ai/feishu-role-map.json";
}

function loadAccountHotelMap() {
  try {
    const config = JSON.parse(readFileSync(authConfigPath(), "utf8"));
    const map = config?.bot_account_hotel_map;
    return map && typeof map === "object" && !Array.isArray(map) ? map : null;
  } catch {
    return null;
  }
}

export function bindingSyncEnabled() {
  return process.env.HOTEL_OTA_FEISHU_BINDING_SYNC === "1";
}

function bindingSyncDryRun() {
  return process.env.HOTEL_OTA_FEISHU_BINDING_SYNC_DRY_RUN === "1";
}

function safeDiagnostic(entry) {
  if (process.env.HOTEL_OTA_FEISHU_PLUGIN_DIAGNOSTICS !== "1") return;
  console.info(JSON.stringify({ component: "hotel_ota_feishu_auth", ...entry }));
}

function loadSQLiteRows() {
  const db = new DatabaseSync(databasePath());
  try {
    return db.prepare(SQLITE_BINDING_QUERY).all();
  } finally {
    db.close();
  }
}

async function loadBindingRuntime() {
  const candidates = [
    process.env.HOTEL_OTA_OPENCLAW_CONVERSATION_RUNTIME,
    DEFAULT_RUNTIME_MODULE,
    "openclaw/plugin-sdk/conversation-runtime",
  ].filter(Boolean);

  let lastError = null;
  for (const candidate of candidates) {
    try {
      return await import(candidate);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("conversation binding runtime unavailable");
}

export async function runBindingSync() {
  const accounts = targetAccounts();
  if (accounts.length === 0) {
    safeDiagnostic({ binding_sync: true, status: "skipped", reason: "target_accounts_empty" });
    return;
  }
  const accountHotelMap = loadAccountHotelMap();
  if (!accountHotelMap) {
    safeDiagnostic({ binding_sync: true, status: "skipped", reason: "bot_account_hotel_map_unavailable" });
    return;
  }

  try {
    const bindingRuntime = await loadBindingRuntime();
    await syncConversationBindings({
      rows: loadSQLiteRows(),
      accounts,
      accountHotelMap,
      bindingRuntime,
      pluginRoot: PLUGIN_ROOT,
      dryRun: bindingSyncDryRun(),
      diagnose: safeDiagnostic,
    });
  } catch (error) {
    safeDiagnostic({ binding_sync: true, status: "failed", reason: error?.code || error?.message || "unknown_error" });
  }
}
