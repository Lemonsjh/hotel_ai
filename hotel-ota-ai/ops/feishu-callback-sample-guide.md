# Archived: Feishu Callback Sample Collection Guide

> This is not a current deployment requirement. The active control-plane path is chat-created request plus authenticated `确认 CFG-...` / `确认 ROLE-...`; it does not configure a public callback URL or card callback transport.

## Goal

Collect one real interactive-card callback envelope for parser design without exposing a token, signature, identity, message content, card payload or customer data. Do not enable configuration application during collection.

## 1. Create a non-production card

Use an existing test Feishu app and test group. The card action must contain only a synthetic request ID, synthetic nonce and synthetic payload hash. Do not use a real price policy or role change request.

## 2. Capture at the HTTP boundary

Temporarily log only the callback key tree and value types. Never log complete request headers or JSON. The capture must retain whether these fields exist:

```text
headers.timestamp
headers.signature
headers.token
body.challenge
body.encrypt
operator.open_id/user_id/union_id
action.value.request_id
action.value.nonce
action.value.payload_hash
message_id
open_chat_id or conversation id
```

Replace each scalar value with its type and a boolean, for example `{"present":true,"type":"string"}`. Replace any array with its length. Delete the raw access log immediately after producing this structural sample.

## 3. Produce the shareable sample

The resulting JSON must contain no value matching an Open ID, chat ID, app ID, token, signature, URL, message body, card text, customer field or server path. Include the OpenClaw and Feishu app event version, endpoint method, and the request field hierarchy.

## 4. Validate before sharing

```bash
rg -n 'ou_|oc_|cli_|tenant_access_token|app_secret|signature|token|https?://' callback-shape-sanitized.json
```

The command must return no sensitive values. Share only the sanitized shape with development. The follow-up callback transport change will use it to implement signature verification, challenge response, operator authentication, tenant scope checks, nonce/hash validation, replay rejection and audit events.
