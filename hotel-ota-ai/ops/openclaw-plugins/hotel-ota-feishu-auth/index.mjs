import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

import { createInboundClaimHandler } from "./lib/auth_ingress.mjs";
import { bindingSyncEnabled, runBindingSync } from "./binding_startup.mjs";

const execFileAsync = promisify(execFile);

function loadHotelEnvFile() {
  const explicitPath = process.env.HOTEL_OTA_ENV_FILE;
  const candidates = explicitPath
    ? [explicitPath]
    : ["/etc/hotel-ota-ai/hotel-ota.env", "C:/ProgramData/hotel-ota-ai/config/hotel-ota.env"];
  const envPath = candidates.find((candidate) => fs.existsSync(candidate));
  if (!envPath) return;
  for (const rawLine of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, "");
    if (key && process.env[key] === undefined) process.env[key] = value;
  }
}

function targetAccounts() {
  const configured = (process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (configured.length === 0) {
    throw new Error("HOTEL_OTA_FEISHU_AUTH_ACCOUNTS must list at least one hotel Feishu account ID");
  }
  // Multiple hotels share this runtime; every account in the list is a targeted
  // Feishu bot. Chat→hotel scoping is resolved via the V3 role map's
  // group_chat_bindings (chat_id → hotel_id), not by accountId.
  return new Set(configured);
}

function runtimeEntry() {
  return process.env.HOTEL_OTA_RUNTIME_ENTRY || path.resolve(process.cwd(), "runtime", "hotel_ota_runtime.py");
}

function authConfigPath() {
  return process.env.HOTEL_OTA_AUTH_CONFIG || "/etc/hotel-ota-ai/feishu-role-map.json";
}

function databasePath() {
  return process.env.HOTEL_OTA_DB || "/var/lib/hotel-ota-ai/hotel_ops.sqlite";
}

export function parseRuntimeJson(stdout) {
  try {
    const parsed = JSON.parse((stdout || "").trim());
    if (parsed && typeof parsed === "object") return parsed;
  } catch {
    // Fall through for JSONL-compatible runtime emitters.
  }
  for (const line of (stdout || "").split(/\r?\n/).reverse()) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      return JSON.parse(trimmed);
    } catch {
      // Continue until the runtime JSON envelope is found.
    }
  }
  throw new Error("runtime returned no JSON envelope");
}

async function routeRuntime(identity) {
  const args = [
    runtimeEntry(),
    "--db",
    databasePath(),
    "feishu-route",
    "--production-feishu",
    "--message",
    identity.message || "",
    "--chat-id",
    identity.chatId,
    "--auth-config",
    authConfigPath(),
    "--render",
  ];
  if (identity.chatType) args.push("--chat-type", identity.chatType);
  if (identity.openId) args.push("--open-id", identity.openId);
  if (identity.userId) args.push("--user-id", identity.userId);
  if (identity.unionId) args.push("--union-id", identity.unionId);
  if (identity.accountId) args.push("--account-id", identity.accountId);
  if (identity.hotelId) args.push("--hotel-id", identity.hotelId);
  if (Array.isArray(identity.memberInfo) && identity.memberInfo.length) {
    args.push("--member-info-json", JSON.stringify(identity.memberInfo));
  }
  const { stdout } = await execFileAsync(process.env.HOTEL_OTA_PYTHON || "python", args, {
    timeout: 90000,
    maxBuffer: 256 * 1024,
    // The runtime renders Chinese Feishu payloads. Force UTF-8 for Windows
    // child processes so JSON output remains parseable by this Node plugin.
    env: { ...process.env, PYTHONUTF8: process.env.PYTHONUTF8 || "1" },
  });
  return parseRuntimeJson(stdout);
}

async function sendFeishu({ accountId, channel, target, text }) {
  await execFileAsync(
    "openclaw",
    ["message", "send", "--account", accountId, "--channel", channel, "--target", target, "--message", text, "--json"],
    { timeout: 30000, maxBuffer: 128 * 1024 },
  );
}

export function createMemoryDedupe() {
  const seen = new Map();
  const ttlMs = Number(process.env.HOTEL_OTA_FEISHU_DEDUPE_TTL_MS || 10 * 60 * 1000);
  return {
    async seen(key) {
      const timestamp = seen.get(key);
      if (!timestamp) return false;
      if (Date.now() - timestamp > ttlMs) {
        seen.delete(key);
        return false;
      }
      return true;
    },
    async remember(key) {
      seen.set(key, Date.now());
    },
  };
}

function safeDiagnostic(entry) {
  if (process.env.HOTEL_OTA_FEISHU_PLUGIN_DIAGNOSTICS !== "1") return;
  console.info(JSON.stringify({ component: "hotel_ota_feishu_auth", ...entry }));
}

function normalizeMemberInfoPayload(payload) {
  const rawItems = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.members)
      ? payload.members
      : Array.isArray(payload?.items)
        ? payload.items
        : [];
  return rawItems
    .map((item) => ({
      name: item?.name,
      display_name: item?.display_name ?? item?.displayName,
      nickname: item?.nickname,
      open_id: item?.open_id ?? item?.openId,
      user_id: item?.user_id ?? item?.userId,
      union_id: item?.union_id ?? item?.unionId,
    }))
    .filter((item) => item.name || item.display_name || item.nickname || item.open_id || item.user_id || item.union_id);
}

function createMemberInfoLookup(api) {
  const candidates = [
    api?.memberInfo,
    api?.getMemberInfo,
    api?.channels?.feishu?.memberInfo,
    api?.channels?.feishu?.getMemberInfo,
    api?.channel?.memberInfo,
    api?.channel?.getMemberInfo,
  ].filter((fn) => typeof fn === "function");
  if (!candidates.length) return async () => null;
  return async (context) => {
    if (context.chatType !== "group" && context.chatType !== "p2p") return null;
    for (const fn of candidates) {
      try {
        const payload = await fn.call(api, {
          accountId: context.accountId,
          channel: "feishu",
          chatId: context.chatId,
          conversationId: context.chatId,
        });
        const normalized = normalizeMemberInfoPayload(payload);
        if (normalized.length) return normalized;
      } catch {
        // Member-info is best-effort. Runtime must fail closed for role changes
        // that require unique member identity.
      }
    }
    return null;
  };
}

export function register(api) {
  loadHotelEnvFile();
  const handler = createInboundClaimHandler({
    targetAccounts: targetAccounts(),
    route: routeRuntime,
    send: sendFeishu,
    dedupe: createMemoryDedupe(),
    memberInfo: createMemberInfoLookup(api),
    diagnose: safeDiagnostic,
    hostDelivery: true,
  });
  // `inbound_claim` only runs for a conversation already owned by a plugin.
  // Hotel bots use normal account routes, so intercept before Agent dispatch:
  // this keeps every targeted Feishu message on the runtime-backed path.
  api.on("before_dispatch", handler);
  if (bindingSyncEnabled()) api.on("gateway_start", runBindingSync);
}

export default {
  id: "hotel-ota-feishu-auth",
  register,
};
