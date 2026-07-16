import test, { after } from 'node:test';
import assert from 'node:assert/strict';

import { createServer } from 'vite';

const vite = await createServer({
  appType: 'custom',
  logLevel: 'silent',
  server: { middlewareMode: true },
});
const {
  applyDialogueStreamEvent,
  removeDialogueStreamPlaceholders,
  shouldFallbackFromDialogueStream,
} = await vite.ssrLoadModule('/src/pages/ChatRoom.jsx');

after(async () => {
  await vite.close();
});

test('group streaming keeps a completed first reply visible while updating only the next stream', () => {
  let messages = [{ role: 'user', content: '行动', client_id: 'pending-1', _pending: true }];

  messages = applyDialogueStreamEvent(messages, {
    type: 'character_started',
    data: {
      stream_id: 'turn-1:0',
      character_id: 'char-a',
      character_name: '阿青',
    },
  });
  messages = applyDialogueStreamEvent(messages, {
    type: 'dialogue_delta',
    data: { stream_id: 'turn-1:0', delta: '收到' },
  });
  messages = applyDialogueStreamEvent(messages, {
    type: 'character_completed',
    data: {
      stream_id: 'turn-1:0',
      response: {
        character_id: 'char-a',
        character_name: '阿青',
        dialogue: '收到。',
      },
    },
  });
  messages = applyDialogueStreamEvent(messages, {
    type: 'character_started',
    data: {
      stream_id: 'turn-1:1',
      character_id: 'char-b',
      character_name: '阿白',
    },
  });
  messages = applyDialogueStreamEvent(messages, {
    type: 'dialogue_delta',
    data: { stream_id: 'turn-1:1', delta: '明' },
  });

  assert.equal(messages[1].content, '收到');
  assert.equal(messages[1]._streaming, false);
  assert.equal(messages[2].content, '明');
  assert.equal(messages[2]._streaming, true);
});

test('turn_completed reconciles streamed placeholders to authoritative persisted messages', () => {
  let messages = [];
  messages = applyDialogueStreamEvent(messages, {
    type: 'character_started',
    data: { stream_id: 'turn-2:0', character_id: 'char-a' },
  });
  messages = applyDialogueStreamEvent(messages, {
    type: 'dialogue_delta',
    data: { stream_id: 'turn-2:0', delta: '临时内容' },
  });
  messages = applyDialogueStreamEvent(messages, {
    type: 'turn_completed',
    data: {
      response: {
        dialogue: '最终内容',
        assistant_message_id: 42,
        current_mood: 'happy',
      },
    },
  });

  assert.deepEqual(messages, [{
    role: 'assistant',
    content: '最终内容',
    charId: 'char-a',
    current_mood: 'happy',
    message_id: 42,
  }]);
});

test('stream failure cleanup removes only placeholders created by the failed turn', () => {
  const messages = [
    { role: 'assistant', content: '历史', message_id: 10 },
    { role: 'assistant', content: '本轮一', stream_id: 'turn-3:0', _streaming: false },
    { role: 'assistant', content: '其他请求', stream_id: 'turn-4:0', _streaming: true },
    { role: 'assistant', content: '本轮二', stream_id: 'turn-3:1', _streaming: true },
  ];

  const next = removeDialogueStreamPlaceholders(
    messages,
    new Set(['turn-3:0', 'turn-3:1']),
  );

  assert.deepEqual(next, [
    messages[0],
    messages[2],
  ]);
});

test('legacy reconcile is allowed before or after the first dialogue delta', () => {
  assert.equal(shouldFallbackFromDialogueStream(false), true);
  assert.equal(shouldFallbackFromDialogueStream(true), true);
});
