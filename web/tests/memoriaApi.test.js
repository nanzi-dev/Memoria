import test from 'node:test';
import assert from 'node:assert/strict';

import { dialogue, multiDialogue } from '../src/api/memoria.js';

test('dialogue APIs include caller request IDs for idempotent retries', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({}),
    };
  };

  try {
    await dialogue.sendMessage('single-session', 'hello', 'req-single');
    await multiDialogue.discussMessage(
      'group-session',
      'hello everyone',
      2,
      'req-group',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, '/api/v1/dialogue/turn');
  assert.equal(calls[0].options.credentials, 'include');
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    session_id: 'single-session',
    player_message: 'hello',
    request_id: 'req-single',
  });

  assert.equal(calls[1].url, '/api/v1/multi-dialogue/turn');
  assert.equal(calls[1].options.credentials, 'include');
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    session_id: 'group-session',
    player_message: 'hello everyone',
    discussion_mode: true,
    request_id: 'req-group',
    max_responses: 2,
  });
});
