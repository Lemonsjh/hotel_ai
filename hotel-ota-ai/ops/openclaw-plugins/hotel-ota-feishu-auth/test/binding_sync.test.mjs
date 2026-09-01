import assert from "node:assert/strict";
import test from "node:test";

import { syncConversationBindings } from "../lib/binding_sync.mjs";

function createBindingRuntime() {
  const created = [];
  return {
    created,
    async getCurrentPluginConversationBinding() {
      return null;
    },
    async createConversationBindingRecord(record) {
      created.push(record);
      return record;
    },
  };
}

test("binding sync binds each Feishu account only to its mapped hotel chats", async () => {
  const bindingRuntime = createBindingRuntime();
  const stats = await syncConversationBindings({
    rows: [
      { chat_id: "oc_hotel_a", chat_type: "group", hotel_id: "hotel-a" },
      { chat_id: "oc_hotel_b", chat_type: "group", hotel_id: "hotel-b" },
    ],
    accounts: ["hotel-a-chief", "hotel-a-s14", "hotel-b-chief"],
    accountHotelMap: {
      "hotel-a-chief": "hotel-a",
      "hotel-a-s14": "hotel-a",
      "hotel-b-chief": "hotel-b",
    },
    bindingRuntime,
    pluginRoot: "/plugin",
  });

  assert.equal(stats.created, 3);
  assert.equal(stats.skip_hotel_mismatch, 3);
  assert.deepEqual(
    bindingRuntime.created.map((record) => [record.conversation.accountId, record.conversation.conversationId]),
    [
      ["hotel-a-chief", "oc_hotel_a"],
      ["hotel-a-s14", "oc_hotel_a"],
      ["hotel-b-chief", "oc_hotel_b"],
    ],
  );
  assert.ok(bindingRuntime.created.every((record) => record.metadata.pluginBindingOwner === "plugin"));
});

test("binding sync fails closed for target accounts without a hotel map", async () => {
  const bindingRuntime = createBindingRuntime();
  const stats = await syncConversationBindings({
    rows: [{ chat_id: "oc_hotel_a", chat_type: "group", hotel_id: "hotel-a" }],
    accounts: ["unknown-account"],
    accountHotelMap: {},
    bindingRuntime,
    pluginRoot: "/plugin",
  });

  assert.equal(stats.created, 0);
  assert.equal(stats.skip_unmapped_account, 1);
  assert.equal(bindingRuntime.created.length, 0);
});
