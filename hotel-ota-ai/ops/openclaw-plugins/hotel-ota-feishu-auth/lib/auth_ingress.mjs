import crypto from "node:crypto";

const GENERIC_UNAUTHORIZED = "您好，当前会话没有业务访问权限，请在已授权群内使用已配置的飞书账号。";
const GENERIC_INVALID_IDENTITY = "您好，未收到可验证的飞书身份信息，暂不能处理该请求。";
const GENERIC_DUPLICATE = "您好，重复消息已忽略，请稍后查看上一条回复。";
const GENERIC_FAILURE = "您好，服务暂时不可用，请稍后重试。";
const GENERIC_MENU = "您好，暂未识别该请求。请发送“菜单”或直接发送功能名称。";
const OPENCLAW_SESSION_COMMAND = /^\/(?:new|clear|stop|restart)(?:\s|$)/i;
const OPENCLAW_CONVERSATION_MESSAGE = /^(?:hi|hey|hello|你好|嗨|在吗|你可以干什么|你能做什么|你能干什么|有什么能力|能提供什么帮助|你是谁|你是什么模型|当前模型|使用什么模型|你所部署的设备是|你当前运行在什么设备上|部署在哪|what can you do|who are you|what model)[?？!！。.\s]*$/i;

function asText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function firstText(...values) {
  for (const value of values) {
    const text = asText(value);
    if (text) return text;
  }
  return "";
}

function nestedValue(source, ...keys) {
  let value = source;
  for (const key of keys) {
    if (!value || typeof value !== "object") return undefined;
    value = value[key];
  }
  return value;
}

function contentText(value) {
  const raw = asText(value);
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object") return firstText(parsed.text, parsed.content, parsed.message);
  } catch {
    // Plain text content is valid for older Feishu event shapes.
  }
  return raw;
}

export function normalizeFeishuChatId(value) {
  let text = asText(value);
  if (!text) return "";
  if (text.startsWith("user:")) return "";
  for (const prefix of ["chat:", "conversation:"]) {
    if (text.startsWith(prefix)) {
      text = text.slice(prefix.length).trim();
      break;
    }
  }
  return text;
}

export function extractInboundContext(event = {}, ctx = {}) {
  const message = event.message && typeof event.message === "object" ? event.message : {};
  const sender = event.sender && typeof event.sender === "object" ? event.sender : message.sender || {};
  const text = firstText(
    contentText(event.content),
    event.text,
    message.text,
    contentText(message.content),
  );
  const rawChatId = firstText(
    event.conversationId,
    ctx.conversationId,
    event.chatId,
    event.chat_id,
    nestedValue(event, "conversation", "id"),
    nestedValue(event, "conversation", "conversationId"),
    nestedValue(ctx, "conversation", "id"),
    nestedValue(ctx, "conversation", "conversationId"),
    message.chatId,
    message.chat_id,
    nestedValue(message, "chat", "id"),
  );
  const chatId = normalizeFeishuChatId(rawChatId);
  const openId = firstText(
    event.senderId,
    ctx.senderId,
    sender.id,
    sender.openId,
    sender.open_id,
    nestedValue(event, "sender", "id"),
    nestedValue(ctx, "sender", "id"),
    nestedValue(sender, "sender_id", "open_id"),
    nestedValue(event, "sender_id", "open_id"),
    event.openId,
    event.open_id,
    message.openId,
    message.open_id,
  );
  // Prefer Feishu's explicit chat type. The host-level isGroup flag can be
  // inherited from a dispatch context and has misclassified p2p events.
  const explicitChatType = firstText(
    event.chatType,
    event.chat_type,
    message.chatType,
    message.chat_type,
    nestedValue(message, "chat", "type"),
  ).toLowerCase();
  const chatType = ["group", "p2p"].includes(explicitChatType)
    ? explicitChatType
    : event.isGroup === true || ctx.isGroup === true
      ? "group"
      : event.isGroup === false || ctx.isGroup === false
        ? "p2p"
        : "";
  const sendTarget = firstText(
    event.sendTarget,
    event.send_target,
    event.target,
    ctx.sendTarget,
    ctx.send_target,
    ctx.target,
    message.sendTarget,
    message.send_target,
    message.target,
    nestedValue(event, "recipient", "target"),
    chatType === "p2p" && openId ? `user:${openId}` : "",
    chatId,
  );
  return {
    accountId: firstText(
      event.accountId,
      event.account_id,
      nestedValue(event, "account", "id"),
      nestedValue(event, "account", "accountId"),
      nestedValue(event, "channel", "accountId"),
      nestedValue(event, "channel", "account", "id"),
      ctx.accountId,
      ctx.account_id,
      nestedValue(ctx, "account", "id"),
      nestedValue(ctx, "account", "accountId"),
      nestedValue(ctx, "channel", "accountId"),
      nestedValue(ctx, "channel", "account", "id"),
    ),
    channel: firstText(event.channel, ctx.channel, "feishu").toLowerCase(),
    messageId: firstText(event.messageId, event.message_id, message.messageId, message.message_id),
    chatId,
    authChatId: chatId,
    sendTarget,
    chatType,
    openId,
    userId: firstText(
      sender.userId,
      sender.user_id,
      nestedValue(sender, "sender_id", "user_id"),
      nestedValue(event, "sender_id", "user_id"),
      event.userId,
      event.user_id,
      message.userId,
      message.user_id,
    ),
    unionId: firstText(
      sender.unionId,
      sender.union_id,
      nestedValue(sender, "sender_id", "union_id"),
      nestedValue(event, "sender_id", "union_id"),
      event.unionId,
      event.union_id,
      message.unionId,
      message.union_id,
    ),
    text,
    isBot: Boolean(sender.isBot || sender.is_bot || event.isBot || event.is_bot || sender.type === "bot"),
  };
}

function matches(value, candidates) {
  return Boolean(value) && candidates.some((candidate) => asText(candidate) === value);
}

export function authorizeInbound(context, config = {}) {
  if (!context.chatId) return { allowed: false, reason: "missing_chat_id" };
  if (!(context.openId || context.userId || context.unionId)) return { allowed: false, reason: "missing_identity" };

  const users = Array.isArray(config.users) ? config.users : [];
  const isV3 = config.version === 3;
  const identityKeys = ["open_id", "feishu_open_id", "user_id", "feishu_user_id", "union_id", "feishu_union_id"];
  const seen = new Map();
  const principals = new Set();
  for (const [index, user] of users.entries()) {
    if (!user || typeof user !== "object") return { allowed: false, reason: "invalid_role_map" };
    if (isV3) {
      const principalId = asText(user.principal_id);
      if (!principalId || principals.has(principalId)) return { allowed: false, reason: "invalid_role_map" };
      principals.add(principalId);
    } else if (!["admin", "owner", "operator", "frontdesk"].includes(user.role)) {
      return { allowed: false, reason: "invalid_role_map" };
    }
    for (const key of identityKeys) {
      const value = asText(user[key]);
      if (!value) continue;
      const identity = `${key.replace("feishu_", "")}:${value}`;
      if (seen.has(identity) && seen.get(identity) !== index) return { allowed: false, reason: "duplicate_canonical_identity" };
      seen.set(identity, index);
    }
  }

  const chatType = firstText(context.chatType, context.chatId?.startsWith("user:") ? "p2p" : "group");
  const match = users.find((user) =>
    matches(context.openId, [user.open_id, user.feishu_open_id]) ||
    matches(context.userId, [user.user_id, user.feishu_user_id]) ||
    matches(context.unionId, [user.union_id, user.feishu_union_id]),
  );
  if (!match) return { allowed: false, reason: "user_not_allowed" };

  if (isV3) {
    const principalId = asText(match.principal_id);
    const isGlobalAdmin = Array.isArray(config.global_admin_principal_ids) && config.global_admin_principal_ids.includes(principalId);
    const memberships = Array.isArray(config.hotel_memberships)
      ? config.hotel_memberships.filter((item) => item && item.principal_id === principalId)
      : [];
    const groupBindings = Array.isArray(config.group_chat_bindings) ? config.group_chat_bindings : [];
    if (chatType === "group") {
      const binding = groupBindings.find((item) => item && normalizeFeishuChatId(item.chat_id) === context.chatId && asText(item.hotel_id));
      if (!binding) return { allowed: false, reason: "chat_not_bound_to_hotel" };
      const membership = memberships.find((item) => item.hotel_id === binding.hotel_id && ["owner", "operator", "frontdesk"].includes(item.role));
      if (!isGlobalAdmin && !membership) return { allowed: false, reason: "user_not_hotel_member" };
      return {
        allowed: true,
        role: isGlobalAdmin ? "admin" : membership.role,
        principalId,
        hotelId: binding.hotel_id,
      };
    }
    if (config.direct_message_policy !== "role_mapped_users_only") {
      return { allowed: false, reason: "direct_message_policy_denied" };
    }
    if (!isGlobalAdmin && memberships.length === 0) return { allowed: false, reason: "user_not_allowed" };
    return {
      allowed: true,
      role: isGlobalAdmin ? "admin" : memberships[0]?.role,
      principalId,
      hotelId: "",
    };
  }

  if (config.version === 2) {
    if (chatType === "p2p") {
      if (config.direct_message_policy !== "role_mapped_users_only") {
        return { allowed: false, reason: "direct_message_policy_denied" };
      }
    } else {
      const groups = Array.isArray(config.allowed_group_chat_ids) ? config.allowed_group_chat_ids : [];
      if (!groups.includes(context.chatId)) return { allowed: false, reason: "chat_not_allowed" };
    }
  } else {
    const allowedChatIds = Array.isArray(config.allowed_chat_ids)
      ? config.allowed_chat_ids
      : Array.isArray(config.groupAllowFrom)
        ? config.groupAllowFrom
        : [];
    const chatCandidates = [
      context.chatId,
      context.openId ? `user:${context.openId}` : "",
      context.userId ? `user:${context.userId}` : "",
      context.unionId ? `user:${context.unionId}` : "",
    ];
    if (allowedChatIds.length && !allowedChatIds.some((allowed) => chatCandidates.includes(asText(allowed)))) {
      return { allowed: false, reason: "chat_not_allowed" };
    }
  }

  if (!match || !["admin", "owner", "operator", "frontdesk"].includes(match.role)) {
    return { allowed: false, reason: "user_not_allowed" };
  }
  return { allowed: true, role: match.role };
}

export function dedupeKey(context) {
  const raw = context.messageId || `${context.accountId}:${context.chatId}:${context.openId || context.userId || context.unionId}:${context.text}`;
  return crypto.createHash("sha256").update(raw).digest("hex");
}

async function sendSafe(send, context, text) {
  await send({ accountId: context.accountId, channel: "feishu", target: context.sendTarget || context.chatId, text });
}

export function createInboundClaimHandler(dependencies) {
  const {
    targetAccounts,
    route,
    send,
    dedupe,
    memberInfo = async () => null,
    diagnose = () => {},
    hostDelivery = false,
  } = dependencies;
  const accounts = targetAccounts instanceof Set ? targetAccounts : new Set(targetAccounts || []);

  return async function inboundClaim(event, ctx = {}) {
    const context = extractInboundContext(event, ctx);
    const respond = async (text) => {
      if (hostDelivery) return { handled: true, text };
      await sendSafe(send, context, text);
      return { handled: true };
    };
    const accountMatch = accounts.has(context.accountId);
    const record = (claimDecision, reason) => diagnose({
      plugin_inbound_claim_seen: true,
      event_channel_present: Boolean(context.channel),
      event_account_id_present: Boolean(context.accountId),
      event_conversation_id_present: Boolean(context.chatId),
      event_sender_id_present: Boolean(context.openId || context.userId || context.unionId),
      account_match: accountMatch,
      claim_decision: claimDecision,
      reason,
    });
    if (context.channel !== "feishu" || !accountMatch) {
      record("pass", context.channel !== "feishu" ? "non_feishu_channel" : "account_not_targeted");
      return undefined;
    }
    if (OPENCLAW_SESSION_COMMAND.test(context.text.trim())) {
      record("pass", "openclaw_session_command");
      return undefined;
    }
    if (OPENCLAW_CONVERSATION_MESSAGE.test(context.text.trim())) {
      record("pass", "openclaw_conversation_message");
      return undefined;
    }
    if (context.isBot) {
      record("claimed", "bot_echo");
      return { handled: true };
    }

    const key = dedupeKey(context);
    try {
      if (await dedupe.seen(key)) {
        record("claimed", "duplicate_message");
        return await respond(GENERIC_DUPLICATE);
      }

      if (!context.chatId || !(context.openId || context.userId || context.unionId)) {
        const reply = !context.chatId || !(context.openId || context.userId || context.unionId) ? GENERIC_INVALID_IDENTITY : GENERIC_UNAUTHORIZED;
        await dedupe.remember(key);
        record("fail_closed", !context.chatId ? "missing_chat_id" : "missing_identity");
        return await respond(reply);
      }

      let resolvedMemberInfo = null;
      try {
        resolvedMemberInfo = await memberInfo(context);
      } catch {
        resolvedMemberInfo = null;
      }
      const routed = await route({
        message: context.text,
        accountId: context.accountId,
        chatId: context.chatId,
        openId: context.openId,
        userId: context.userId,
        unionId: context.unionId,
        chatType: context.chatType,
        memberInfo: Array.isArray(resolvedMemberInfo) ? resolvedMemberInfo : null,
      });
      const payload = routed?.send_payload || {};
      const text = payload.send_allowed === false ? GENERIC_FAILURE : asText(payload.text) || GENERIC_MENU;
      await dedupe.remember(key);
      record("claimed", "runtime_routed");
      return await respond(text);
    } catch {
      try {
        return await respond(GENERIC_FAILURE);
      } catch {
        // The inbound claim must remain fail-closed even when delivery is unavailable.
      }
      record("fail_closed", "plugin_exception");
      return { handled: true };
    }
  };
}
