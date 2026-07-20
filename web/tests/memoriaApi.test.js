import test from 'node:test';
import assert from 'node:assert/strict';

import { dialogue, knowledgeApi, multiDialogue, userApi } from '../src/api/memoria.js';

function streamResponse(text, chunkSizes = [1]) {
  const bytes = new TextEncoder().encode(text);
  const chunks = [];
  let offset = 0;
  let sizeIndex = 0;
  while (offset < bytes.length) {
    const size = chunkSizes[sizeIndex % chunkSizes.length];
    chunks.push(bytes.slice(offset, offset + size));
    offset += size;
    sizeIndex += 1;
  }

  return {
    ok: true,
    status: 200,
    body: new ReadableStream({
      start(controller) {
        chunks.forEach(chunk => controller.enqueue(chunk));
        controller.close();
      },
    }),
  };
}

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

test('knowledge preview forwards abort signals', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({ sources: [] }),
    };
  };

  try {
    await knowledgeApi.preview(
      {
        query: 'harbor',
        knowledge_base_id: 'kb-graytide',
      },
      { signal: controller.signal },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/v1/knowledge/preview');
  assert.equal(calls[0].options.signal, controller.signal);
  assert.equal(calls[0].options.method, 'POST');
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

test('dialogue stream parses UTF-8 and multi-line SSE data across arbitrary byte boundaries', async () => {
  const originalFetch = globalThis.fetch;
  const events = [];
  globalThis.fetch = async () => streamResponse([
    'event: character_started',
    'data: {"stream_id":"req-1:0","character_name":"阿青"}',
    '',
    'event: dialogue_delta',
    'data: {"stream_id":"req-1:0",',
    'data: "delta":"你好"}',
    '',
    'event: turn_completed',
    'data: {"response":{"dialogue":"你好","assistant_message_id":12}}',
  ].join('\n'), [1, 2, 5, 3]);

  try {
    const result = await dialogue.streamMessage(
      'single-session',
      '请回答',
      'req-1',
      event => events.push(event),
    );

    assert.deepEqual(events, [
      {
        type: 'character_started',
        data: {
          stream_id: 'req-1:0',
          character_name: '阿青',
        },
      },
      {
        type: 'dialogue_delta',
        data: {
          stream_id: 'req-1:0',
          delta: '你好',
        },
      },
      {
        type: 'turn_completed',
        data: {
          response: {
            dialogue: '你好',
            assistant_message_id: 12,
          },
        },
      },
    ]);
    assert.deepEqual(result, {
      dialogue: '你好',
      assistant_message_id: 12,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('stream APIs preserve request payloads, credentials, and fetch options', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  const controller = new AbortController();
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return streamResponse(
      'event: turn_completed\ndata: {"response":{"responses":[]}}\n\n',
      [4, 7],
    );
  };

  try {
    await dialogue.streamMessage(
      'single-session',
      'hello',
      'req-single',
      () => {},
      { signal: controller.signal },
    );
    await multiDialogue.streamDiscussMessage(
      'group-session',
      'hello everyone',
      2,
      'req-group',
      () => {},
      { signal: controller.signal },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.equal(calls.length, 2);
  assert.equal(calls[0].url, '/api/v1/dialogue/turn/stream');
  assert.equal(calls[0].options.credentials, 'include');
  assert.equal(calls[0].options.signal, controller.signal);
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    session_id: 'single-session',
    player_message: 'hello',
    request_id: 'req-single',
  });

  assert.equal(calls[1].url, '/api/v1/multi-dialogue/turn/stream');
  assert.equal(calls[1].options.credentials, 'include');
  assert.equal(calls[1].options.signal, controller.signal);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    session_id: 'group-session',
    player_message: 'hello everyone',
    discussion_mode: true,
    request_id: 'req-group',
    max_responses: 2,
  });
});

test('stream error events are dispatched and reject with parsed server details', async () => {
  const originalFetch = globalThis.fetch;
  const events = [];
  globalThis.fetch = async () => streamResponse(
    'event: error\ndata: {"detail":"provider unavailable","error_type":"RuntimeError"}',
    [2, 1, 3],
  );

  try {
    await assert.rejects(
      dialogue.streamMessage(
        'single-session',
        'hello',
        'req-error',
        event => events.push(event),
      ),
      error => {
        assert.equal(error.message, 'provider unavailable');
        assert.deepEqual(error.body, {
          detail: 'provider unavailable',
          error_type: 'RuntimeError',
        });
        return true;
      },
    );
    assert.deepEqual(events, [{
      type: 'error',
      data: {
        detail: 'provider unavailable',
        error_type: 'RuntimeError',
      },
    }]);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
