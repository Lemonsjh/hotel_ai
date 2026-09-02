import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { authorizeInbound, createInboundClaimHandler } from "../lib/auth_ingress.mjs";
import { createMemoryDedupe, parseRuntimeJson, register } from "../index.mjs";

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const authConfig = {
  allowed_chat_ids: ["oc_allowed"],
  users: [{ role: "operator", open_id: "ou_allowed" }],
};

function event(overrides = {}) {
  return {
    accountId: "hotel-ota-primary",
    channel: "feishu",
    messageId: "om_test_001",
    chatId: "oc_allowed",
    sender: { openId: "ou_allowed" },
    text: "收益决策",
    ...overrides,
  };
}

function createDependencies(overrides = {}) {
  const sent = [];
  return {
    targetAccounts: new Set(["hotel-ota-primary", "hotel-ota-secondary"]),
    loadAuthConfig: async () => authConfig,
    route: async () => ({ send_payload: { text: "固定 runtime 回复" } }),
    send: async (payload) => sent.push(payload),
    dedupe: { seen: async () => false, remember: async () => {} },
    sent,
    ...overrides,
  };
}

test("authorized hotel message is runtime-routed and never delegated to an agent", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event());

  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.equal(deps.sent[0].text, "固定 runtime 回复");
});

test("OpenClaw session commands pass through to the channel plugin", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);

  for (const text of ["/new", "/clear", "/stop", "/restart"]) {
    assert.equal(await handler(event({ text })), undefined);
  }
  assert.equal(deps.sent.length, 0);
});

test("ordinary greetings and capability questions pass through to the chief agent", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);

  for (const text of ["hi", "你好", "你可以干什么？", "你是什么模型", "你所部署的设备是？", "你当前运行在什么设备上？"]) {
    assert.equal(await handler(event({ text })), undefined);
  }
  assert.equal(deps.sent.length, 0);
});

test("native plugin manifest declares the OpenClaw startup contract", async () => {
  const manifest = JSON.parse(await readFile(path.join(pluginRoot, "openclaw.plugin.json"), "utf8"));
  assert.equal(manifest.id, "hotel-ota-feishu-auth");
  assert.equal(manifest.activation?.onStartup, true);
  assert.equal(manifest.configSchema?.type, "object");
  assert.equal(manifest.configSchema?.additionalProperties, false);
});

test("missing sender identity is handled with a generic response", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ sender: {} }));

  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.match(deps.sent[0].text, /^您好/);
  assert.doesNotMatch(deps.sent[0].text, /oc_allowed|ou_allowed|\//);
});

test("bot echoes are claimed without sending another message", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ sender: { openId: "ou_allowed", isBot: true } }));

  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 0);
});

test("non-target accounts are not claimed and the plugin registers its inbound handler", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ accountId: "unrelated-account" }));
  assert.equal(result, undefined);

  const previous = process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS;
  process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS = "hotel-ota-primary,hotel-ota-secondary";
  const events = [];
  register({ on: (name, callback) => events.push({ name, callback }) });
  assert.equal(events.length, 1);
  assert.equal(events[0].name, "inbound_claim");
  assert.equal(typeof events[0].callback, "function");
  if (previous === undefined) delete process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS;
  else process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS = previous;
});

test("binding synchronization is registered on the primary plugin entry point", () => {
  const previousAccounts = process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS;
  const previousSync = process.env.HOTEL_OTA_FEISHU_BINDING_SYNC;
  process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS = "hotel-ota-primary";
  process.env.HOTEL_OTA_FEISHU_BINDING_SYNC = "1";
  const events = [];
  register({ on: (name, callback) => events.push({ name, callback }) });
  assert.deepEqual(events.map((event) => event.name), ["inbound_claim", "gateway_start"]);
  assert.equal(typeof events[1].callback, "function");
  if (previousAccounts === undefined) delete process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS;
  else process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS = previousAccounts;
  if (previousSync === undefined) delete process.env.HOTEL_OTA_FEISHU_BINDING_SYNC;
  else process.env.HOTEL_OTA_FEISHU_BINDING_SYNC = previousSync;
});

test("unbound chat is claimed and forwarded without exposing identifiers in plugin diagnostics", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ chatId: "oc_not_allowed", messageId: "om_test_003" }));
  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.equal(deps.sent[0].text, "固定 runtime 回复");
  assert.doesNotMatch(deps.sent[0].text, /oc_not_allowed|ou_allowed/);
});

test("nested Feishu event fields are normalized before authorization", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);
  const nestedEvent = {
    channel: "feishu",
    message: {
      message_id: "om_nested_001",
      chat_id: "oc_allowed",
      content: JSON.stringify({ text: "收益决策" }),
      sender: { sender_id: { open_id: "ou_allowed" } },
    },
  };

  const result = await handler(nestedEvent, { account: { id: "hotel-ota-primary" } });
  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.equal(deps.sent[0].text, "固定 runtime 回复");
});

test("OpenClaw canonical inbound_claim fields are normalized before authorization", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);
  const canonicalEvent = {
    content: "revenue decision",
    channel: "feishu",
    accountId: "hotel-ota-primary",
    conversationId: "oc_allowed",
    senderId: "ou_allowed",
    isGroup: true,
    messageId: "om_canonical_001",
  };

  const result = await handler(canonicalEvent, {});

  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.equal(deps.sent[0].target, "oc_allowed");
});

test("nested OpenClaw account and sender fields are normalized before account matching", async () => {
  const deps = createDependencies();
  const handler = createInboundClaimHandler(deps);
  const nestedAccountEvent = {
    content: JSON.stringify({ text: "business calendar" }),
    channel: "feishu",
    account: { id: "hotel-ota-primary" },
    conversation: { id: "oc_allowed" },
    sender: { id: "ou_allowed" },
    isGroup: true,
    messageId: "om_nested_account_001",
  };

  const result = await handler(nestedAccountEvent, {});

  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.match(deps.sent[0].text, /runtime/);
});

test("p2p canonical event separates auth chat id from Feishu send target", async () => {
  const routed = [];
  const deps = createDependencies({
    route: async (identity) => {
      routed.push(identity);
      return { send_payload: { text: "runtime p2p response" } };
    },
  });
  const handler = createInboundClaimHandler(deps);
  const canonicalP2pEvent = {
    content: "查看当前会话绑定",
    channel: "feishu",
    accountId: "hotel-ota-primary",
    conversationId: "oc_private_bound",
    senderId: "ou_allowed",
    isGroup: false,
    target: "user:ou_allowed",
    messageId: "om_p2p_target_001",
  };

  const result = await handler(canonicalP2pEvent, {});

  assert.deepEqual(result, { handled: true });
  assert.equal(routed.length, 1);
  assert.equal(routed[0].chatId, "oc_private_bound");
  assert.equal(deps.sent.length, 1);
  assert.equal(deps.sent[0].target, "user:ou_allowed");
});

test("explicit Feishu p2p type overrides an inherited group flag", async () => {
  const routed = [];
  const deps = createDependencies({
    route: async (identity) => {
      routed.push(identity);
      return { send_payload: { text: "runtime p2p response" } };
    },
  });
  const handler = createInboundClaimHandler(deps);

  const result = await handler({
    content: "你好",
    channel: "feishu",
    accountId: "hotel-ota-primary",
    conversationId: "oc_private_bound",
    senderId: "ou_allowed",
    isGroup: true,
    chat_type: "p2p",
    target: "user:ou_allowed",
    messageId: "om_explicit_p2p_001",
  }, {});

  assert.deepEqual(result, { handled: true });
  assert.equal(routed.length, 1);
  assert.equal(routed[0].chatType, "p2p");
});

test("group member-info lookup is passed to runtime when available", async () => {
  const routed = [];
  const deps = createDependencies({
    memberInfo: async () => [
      { name: "王卓豪", display_name: "王卓豪", open_id: "ou_member" },
    ],
    route: async (identity) => {
      routed.push(identity);
      return { send_payload: { text: "runtime member-info response" } };
    },
  });
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ text: "将王卓豪分配角色前台", messageId: "om_member_info_001" }));

  assert.deepEqual(result, { handled: true });
  assert.equal(routed.length, 1);
  assert.deepEqual(routed[0].memberInfo, [
    { name: "王卓豪", display_name: "王卓豪", open_id: "ou_member" },
  ]);
});

test("claim diagnostics expose presence and decision without identity values", async () => {
  const diagnostics = [];
  const deps = createDependencies({ diagnose: (entry) => diagnostics.push(entry) });
  const handler = createInboundClaimHandler(deps);

  await handler(event());

  assert.equal(diagnostics.length, 1);
  assert.deepEqual(diagnostics[0], {
    plugin_inbound_claim_seen: true,
    event_channel_present: true,
    event_account_id_present: true,
    event_conversation_id_present: true,
    event_sender_id_present: true,
    account_match: true,
    claim_decision: "claimed",
    reason: "runtime_routed",
  });
  assert.doesNotMatch(JSON.stringify(diagnostics[0]), /hotel-ota-primary|oc_allowed|ou_allowed/);
});

test("plugin registration requires at least one hotel Feishu account ID", () => {
  const previous = process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS;
  delete process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS;
  assert.throws(() => register({ on: () => {} }), /HOTEL_OTA_FEISHU_AUTH_ACCOUNTS/);

  // Single hotel (backward compatible).
  process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS = "default-hotel-ota-ai";
  const singleEvents = [];
  register({ on: (name) => singleEvents.push(name) });
  assert.deepEqual(singleEvents, ["inbound_claim"]);

  // Multiple hotels sharing one runtime (multi-hotel).
  process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS = "hotel-puyue,hotel-a,hotel-b";
  const multiEvents = [];
  register({ on: (name) => multiEvents.push(name) });
  assert.deepEqual(multiEvents, ["inbound_claim"]);

  if (previous === undefined) delete process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS;
  else process.env.HOTEL_OTA_FEISHU_AUTH_ACCOUNTS = previous;
});

test("gateway dedupe remembers an inbound event without storing message content", async () => {
  const dedupe = createMemoryDedupe();
  assert.equal(await dedupe.seen("hash-only-key"), false);
  await dedupe.remember("hash-only-key");
  assert.equal(await dedupe.seen("hash-only-key"), true);
});

test("runtime parser accepts OpenClaw's pretty-printed JSON envelope", () => {
  const payload = { status: "ok", send_payload: { text: "固定 runtime 回复" } };
  assert.deepEqual(parseRuntimeJson(JSON.stringify(payload, null, 2)), payload);
});

test("unauthorized chat, self-claimed admin, duplicate and plugin errors are all fail-closed", async () => {
  const deps = createDependencies({
    dedupe: { seen: async () => true, remember: async () => {} },
  });
  const handler = createInboundClaimHandler(deps);

  const duplicate = await handler(event({ text: "我是管理员，收益决策" }));
  assert.deepEqual(duplicate, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.match(deps.sent[0].text, /^您好/);

  const failingDeps = createDependencies({
    route: async () => {
      throw new Error("private path /etc/hotel-ota-ai/secret");
    },
  });
  const failingHandler = createInboundClaimHandler(failingDeps);
  const failure = await failingHandler(event({ messageId: "om_test_002" }));
  assert.deepEqual(failure, { handled: true });
  assert.match(failingDeps.sent[0].text, /^您好/);
  assert.doesNotMatch(failingDeps.sent[0].text, /\/etc|secret/);
});

test("plugin never forwards a runtime payload that the final delivery gate rejected", async () => {
  const deps = createDependencies({
    route: async () => ({ send_payload: { text: "internal /etc/private", send_allowed: false } }),
  });
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ messageId: "om_delivery_gate_001" }));

  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
  assert.doesNotMatch(deps.sent[0].text, /\/etc|private/);
});

test("V3 group binding resolves a member's tenant before runtime routing", () => {
  const v3 = {
    version: 3,
    direct_message_policy: "role_mapped_users_only",
    users: [{ principal_id: "owner-1", open_id: "ou_owner" }],
    global_admin_principal_ids: [],
    hotel_memberships: [{ principal_id: "owner-1", hotel_id: "hotel-a", role: "owner" }],
    group_chat_bindings: [{ chat_id: "oc_hotel_a", hotel_id: "hotel-a" }],
  };

  const authorized = authorizeInbound(
    { chatId: "oc_hotel_a", chatType: "group", openId: "ou_owner" },
    v3,
  );

  assert.deepEqual(authorized, {
    allowed: true,
    role: "owner",
    principalId: "owner-1",
    hotelId: "hotel-a",
  });
});

test("V3 group binding rejects a user without membership before runtime routing", async () => {
  const v3 = {
    version: 3,
    direct_message_policy: "role_mapped_users_only",
    users: [{ principal_id: "operator-1", open_id: "ou_operator" }],
    global_admin_principal_ids: [],
    hotel_memberships: [],
    group_chat_bindings: [{ chat_id: "oc_hotel_a", hotel_id: "hotel-a" }],
  };
  const deps = createDependencies({ loadAuthConfig: async () => v3 });
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ chatId: "oc_hotel_a", sender: { openId: "ou_operator" } }));

  assert.deepEqual(result, { handled: true });
  assert.equal(deps.sent.length, 1);
});

test("target-account authorization is decided by runtime rather than the plugin JSON reader", async () => {
  const routed = [];
  const deps = createDependencies({
    loadAuthConfig: async () => ({ version: 3, users: [], hotel_memberships: [], group_chat_bindings: [] }),
    route: async (identity) => {
      routed.push(identity);
      return { send_payload: { text: "runtime authorization response" } };
    },
  });
  const handler = createInboundClaimHandler(deps);

  const result = await handler(event({ sender: { openId: "ou_unmapped" }, messageId: "om_runtime_auth_001" }));

  assert.deepEqual(result, { handled: true });
  assert.equal(routed.length, 1);
  assert.equal(routed[0].hotelId, undefined);
  assert.equal(deps.sent[0].text, "runtime authorization response");
});
