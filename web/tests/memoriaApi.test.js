import test from 'node:test';
import assert from 'node:assert/strict';

import { dialogue, multiDialogue, userApi } from '../src/api/memoria.js';

test('new dialogue sessions always use Chinese', async () => {
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
    await dialogue.startSession('npc-one', 'player-one', '旅人');
    await multiDialogue.startSession(
      'player-one',
      '旅人',
      ['npc-one', 'npc-two'],
      '同行者',
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(JSON.parse(calls[0].options.body), {
    character_id: 'npc-one',
    player_id: 'player-one',
    player_name: '旅人',
    locale: 'zh-CN',
  });
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    player_id: 'player-one',
    player_name: '旅人',
    group_name: '同行者',
    character_ids: ['npc-one', 'npc-two'],
    locale: 'zh-CN',
  });
});

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

test('user character-card APIs use the authenticated persona endpoints', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({ display_name: '旅人' }),
    };
  };

  try {
    await userApi.getCharacterCard();
    await userApi.updateCharacterCard({ display_name: '旅人', age: 24 });
    await userApi.uploadCharacterCardAvatar(new Blob(['avatar'], { type: 'image/png' }));
    await userApi.setCharacterCardAvatarUrl('https://example.test/avatar.png');
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(calls.map(call => call.url), [
    '/api/v1/user/character-card',
    '/api/v1/user/character-card',
    '/api/v1/user/character-card/avatar/upload',
    '/api/v1/user/character-card/avatar/url',
  ]);
  assert.equal(calls[0].options.credentials, 'include');
  assert.equal(calls[1].options.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    display_name: '旅人',
    age: 24,
  });
  assert.equal(calls[2].options.method, 'POST');
  assert.ok(calls[2].options.body instanceof FormData);
  assert.equal(calls[3].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[3].options.body), {
    url: 'https://example.test/avatar.png',
  });
});
