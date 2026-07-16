import test from 'node:test';
import assert from 'node:assert/strict';

import {
  appendDialogueDelta,
  completeCharacter,
  reconcileTurn,
  startCharacter,
} from '../src/utils/dialogueStreamState.js';

test('startCharacter immutably adds a stream-keyed assistant placeholder', () => {
  const originalMessage = { role: 'user', content: 'hello', message_id: 10 };
  const state = [originalMessage];

  const next = startCharacter(state, {
    stream_id: 'req-1:0',
    character_id: 'char-a',
    character_name: '阿青',
  });

  assert.deepEqual(state, [originalMessage]);
  assert.notEqual(next, state);
  assert.equal(next[0], originalMessage);
  assert.deepEqual(next[1], {
    role: 'assistant',
    content: '',
    stream_id: 'req-1:0',
    charId: 'char-a',
    charName: '阿青',
    _streaming: true,
  });
});

test('appendDialogueDelta updates only the matching stream without mutating prior state', () => {
  const state = [
    startCharacter([], {
      stream_id: 'req-1:0',
      character_id: 'char-a',
      character_name: '阿青',
    })[0],
    startCharacter([], {
      stream_id: 'req-1:1',
      character_id: 'char-b',
      character_name: '阿白',
    })[0],
  ];

  const next = appendDialogueDelta(state, {
    stream_id: 'req-1:1',
    delta: '你',
  });
  const final = appendDialogueDelta(next, {
    stream_id: 'req-1:1',
    delta: '好',
  });

  assert.equal(state[1].content, '');
  assert.equal(next[0], state[0]);
  assert.equal(next[1].content, '你');
  assert.equal(final[1].content, '你好');
});

test('completeCharacter preserves streamed text and attaches authoritative metadata', () => {
  const state = appendDialogueDelta(
    startCharacter([], {
      stream_id: 'req-1:0',
      character_id: 'char-a',
      character_name: '阿青',
    }),
    { stream_id: 'req-1:0', delta: '你好' },
  );

  const next = completeCharacter(state, {
    stream_id: 'req-1:0',
    response: {
      character_id: 'char-a',
      character_name: '阿青',
      dialogue: '你好。',
      action: 'wave',
      message_id: 21,
      current_mood: 'warm',
    },
  });

  assert.equal(state[0]._streaming, true);
  assert.equal(next[0].content, '你好');
  assert.equal(next[0].action, 'wave');
  assert.equal(next[0].message_id, 21);
  assert.equal(next[0].current_mood, 'warm');
  assert.equal(next[0]._streaming, false);
});

test('reconcileTurn replaces placeholders with final group responses and removes ID duplicates', () => {
  let state = [{ role: 'user', content: '行动', message_id: 20 }];
  state = startCharacter(state, {
    stream_id: 'req-group:0',
    character_id: 'char-a',
    character_name: '阿青',
  });
  state = appendDialogueDelta(state, {
    stream_id: 'req-group:0',
    delta: '收',
  });
  state = completeCharacter(state, {
    stream_id: 'req-group:0',
    response: {
      character_id: 'char-a',
      character_name: '阿青',
      dialogue: '收到',
      action: 'nod',
    },
  });
  state = startCharacter(state, {
    stream_id: 'req-group:1',
    character_id: 'char-b',
    character_name: '阿白',
  });
  state = appendDialogueDelta(state, {
    stream_id: 'req-group:1',
    delta: '明白',
  });
  state = [
    ...state,
    {
      role: 'assistant',
      content: 'stale duplicate',
      charId: 'char-a',
      message_id: 21,
    },
  ];
  const original = structuredClone(state);

  const next = reconcileTurn(state, {
    responses: [
      {
        message_id: 21,
        character_id: 'char-a',
        character_name: '阿青',
        dialogue: '收到',
        action: 'nod',
      },
      {
        message_id: 22,
        character_id: 'char-b',
        character_name: '阿白',
        dialogue: '明白了',
        action: 'salute',
      },
    ],
  });

  assert.deepEqual(state, original);
  assert.deepEqual(next.map(message => message.message_id), [20, 21, 22]);
  assert.deepEqual(next.map(message => message.content), ['行动', '收到', '明白了']);
  assert.equal(next[1].charId, 'char-a');
  assert.equal(next[2].charId, 'char-b');
  assert.equal(next.some(message => 'stream_id' in message), false);
  assert.equal(next.some(message => '_streaming' in message), false);
});

test('reconcileTurn maps a single final response assistant ID onto its placeholder', () => {
  const state = appendDialogueDelta(
    startCharacter([], {
      stream_id: 'req-single:0',
      character_id: 'char-a',
    }),
    { stream_id: 'req-single:0', delta: '临时文本' },
  );

  const next = reconcileTurn(state, {
    dialogue: '最终文本',
    action: 'smile',
    assistant_message_id: 12,
  });

  assert.deepEqual(next, [{
    role: 'assistant',
    content: '最终文本',
    charId: 'char-a',
    action: 'smile',
    message_id: 12,
  }]);
});
