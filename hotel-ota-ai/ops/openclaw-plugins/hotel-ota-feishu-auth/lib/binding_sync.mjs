import crypto from "node:crypto";

export const PLUGIN_ID = "hotel-ota-feishu-auth";
export const PLUGIN_NAME = "Hotel OTA Feishu Authorization";

export const SQLITE_BINDING_QUERY = `
SELECT
  chat_id,
  chat_type,
  hotel_id,
  'chat_bindings' AS source_table
FROM chat_bindings
WHERE status = 'active'
  AND chat_id LIKE 'oc_%'

UNION ALL

SELECT
  chat_id,
  'group' AS chat_type,
  hotel_id,
  'group_chat_bindings' AS source_table
FROM group_chat_bindings
WHERE status = 'active'
  AND chat_id LIKE 'oc_%'
`;

function asText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeChatType(value) {
  const text = asText(value).toLowerCase();
  if (text === "group" || text === "p2p") return text;
  return "unknown";
}

export function normalizeAccountHotelMap(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return new Map();
  return new Map(
    Object.entries(value)
      .map(([accountId, hotelId]) => [asText(accountId), asText(hotelId)])
      .filter(([accountId, hotelId]) => accountId && hotelId),
  );
}

export function isOpenClawFeishuConversationId(value) {
  return asText(value).startsWith("oc_");
}

export function normalizeSQLiteBindingRows(rows = []) {
  const normalized = [];
  const seen = new Set();
  const skipped = { invalidChatId: 0, duplicate: 0 };

  for (const row of Array.isArray(rows) ? rows : []) {
    const chatId = asText(row?.chat_id ?? row?.chatId);
    if (!isOpenClawFeishuConversationId(chatId)) {
      skipped.invalidChatId += 1;
      continue;
    }

    const chatType = normalizeChatType(row?.chat_type ?? row?.chatType);
    const hotelId = asText(row?.hotel_id ?? row?.hotelId);
    const sourceTable = asText(row?.source_table ?? row?.sourceTable) || "unknown";
    const key = `${chatId}:${chatType}:${hotelId}`;
    if (seen.has(key)) {
      skipped.duplicate += 1;
      continue;
    }
    seen.add(key);

    normalized.push({ chatId, chatType, hotelId, sourceTable });
  }

  return { bindings: normalized, skipped };
}

export async function loadSQLiteBindingRows({ dbPath, execFileAsync, sqliteBinary = "sqlite3" }) {
  const database = asText(dbPath);
  if (!database) throw new Error("missing SQLite database path for Feishu binding sync");
  if (typeof execFileAsync !== "function") throw new Error("missing execFileAsync for Feishu binding sync");

  const { stdout } = await execFileAsync(sqliteBinary, ["-readonly", "-json", database, SQLITE_BINDING_QUERY], {
    timeout: 30000,
    maxBuffer: 256 * 1024,
  });
  const trimmed = asText(stdout);
  if (!trimmed) return [];
  const parsed = JSON.parse(trimmed);
  return Array.isArray(parsed) ? parsed : [];
}

export function buildPluginBindingSessionKey({ pluginId = PLUGIN_ID, channel, accountId, conversationId }) {
  const hash = crypto
    .createHash("sha256")
    .update(JSON.stringify({
      pluginId,
      channel: asText(channel).toLowerCase(),
      accountId: asText(accountId),
      conversationId: asText(conversationId),
    }))
    .digest("hex")
    .slice(0, 24);
  return `plugin-binding:${pluginId}:${hash}`;
}

export function isOwnedPluginBinding(record, pluginId = PLUGIN_ID) {
  if (!record) return false;
  if (record.pluginId === pluginId) return true;
  const metadata = record.metadata;
  return Boolean(
    metadata &&
    typeof metadata === "object" &&
    metadata.pluginBindingOwner === "plugin" &&
    metadata.pluginId === pluginId,
  );
}

export function buildPluginBindingConversation({ accountId, binding }) {
  const conversationId = asText(binding?.chatId ?? binding?.chat_id);
  const resolvedAccountId = asText(accountId);
  if (!resolvedAccountId) throw new Error("missing Feishu account ID for binding sync");
  if (!isOpenClawFeishuConversationId(conversationId)) throw new Error("binding sync requires an oc_ Feishu conversation ID");
  return {
    channel: "feishu",
    accountId: resolvedAccountId,
    conversationId,
  };
}

export function buildPluginBindingRequestParams({ binding }) {
  return {
    summary: "Hotel OTA Feishu auth gateway binding",
    detachHint: "Disable HOTEL_OTA_FEISHU_BINDING_SYNC or detach this plugin conversation binding.",
    data: {
      source: "sqlite-active-auth",
      hotelId: asText(binding?.hotelId ?? binding?.hotel_id),
      chatType: normalizeChatType(binding?.chatType ?? binding?.chat_type),
      sourceTable: asText(binding?.sourceTable ?? binding?.source_table),
    },
  };
}

export function buildConversationBindingInput({ accountId, binding, pluginRoot, pluginId = PLUGIN_ID, pluginName = PLUGIN_NAME }) {
  const conversation = buildPluginBindingConversation({ accountId, binding });
  return {
    pluginId,
    pluginName,
    pluginRoot: asText(pluginRoot),
    conversation,
    binding: buildPluginBindingRequestParams({ binding }),
  };
}

export function buildManagedBindingRecordInput({ accountId, binding, pluginRoot, pluginId = PLUGIN_ID, pluginName = PLUGIN_NAME }) {
  const request = buildConversationBindingInput({ accountId, binding, pluginRoot, pluginId, pluginName });
  return {
    targetSessionKey: buildPluginBindingSessionKey({
      pluginId,
      channel: request.conversation.channel,
      accountId: request.conversation.accountId,
      conversationId: request.conversation.conversationId,
    }),
    targetKind: "session",
    conversation: request.conversation,
    placement: "current",
    metadata: {
      pluginBindingOwner: "plugin",
      pluginId,
      pluginName,
      pluginRoot: request.pluginRoot,
      summary: request.binding.summary,
      detachHint: request.binding.detachHint,
      data: request.binding.data,
    },
  };
}

async function getCurrentBinding(bindingRuntime, pluginRoot, conversation) {
  if (typeof bindingRuntime.getCurrentPluginConversationBinding !== "function") return null;
  return await bindingRuntime.getCurrentPluginConversationBinding({ pluginRoot, conversation });
}

export async function syncConversationBindings({
  rows,
  accounts,
  accountHotelMap,
  bindingRuntime,
  pluginRoot,
  dryRun = false,
  diagnose = () => {},
}) {
  const accountList = [...new Set((Array.isArray(accounts) ? accounts : [...accounts || []]).map(asText).filter(Boolean))];
  const accountHotels = normalizeAccountHotelMap(accountHotelMap);
  const resolvedPluginRoot = asText(pluginRoot);
  if (!accountList.length) throw new Error("missing target Feishu accounts for binding sync");
  if (!resolvedPluginRoot) throw new Error("missing plugin root for binding sync");
  if (!bindingRuntime || typeof bindingRuntime.createConversationBindingRecord !== "function") {
    throw new Error("missing OpenClaw plugin conversation binding runtime");
  }

  const { bindings, skipped } = normalizeSQLiteBindingRows(rows);
  const stats = {
    dry_run: Boolean(dryRun),
    candidates: bindings.length,
    accounts: accountList.length,
    create: 0,
    created: 0,
    bound: 0,
    keep: 0,
    skip_invalid_chat_id: skipped.invalidChatId,
    skip_duplicate: skipped.duplicate,
    skip_unmapped_account: 0,
    skip_hotel_mismatch: 0,
    errors: 0,
  };

  for (const accountId of accountList) {
    const accountHotelId = accountHotels.get(accountId);
    if (!accountHotelId) {
      stats.skip_unmapped_account += 1;
      continue;
    }
    for (const binding of bindings) {
      if (binding.hotelId !== accountHotelId) {
        stats.skip_hotel_mismatch += 1;
        continue;
      }
      const record = buildManagedBindingRecordInput({
        accountId,
        binding,
        pluginRoot: resolvedPluginRoot,
      });

      try {
        const existing = await getCurrentBinding(bindingRuntime, resolvedPluginRoot, record.conversation);
        if (existing && isOwnedPluginBinding(existing)) {
          stats.keep += 1;
          continue;
        }

        stats.create += 1;
        if (dryRun) continue;

        await bindingRuntime.createConversationBindingRecord(record);
        stats.bound += 1;
        stats.created += 1;
      } catch {
        stats.errors += 1;
      }
    }
  }

  diagnose({ binding_sync: true, ...stats });
  return stats;
}

export async function syncSQLiteConversationBindings({
  dbPath,
  execFileAsync,
  accounts,
  accountHotelMap,
  bindingRuntime,
  pluginRoot,
  dryRun = false,
  diagnose = () => {},
}) {
  const rows = await loadSQLiteBindingRows({ dbPath, execFileAsync });
  return syncConversationBindings({ rows, accounts, accountHotelMap, bindingRuntime, pluginRoot, dryRun, diagnose });
}
