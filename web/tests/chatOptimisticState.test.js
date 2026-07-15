import test from 'node:test';
import assert from 'node:assert/strict';

import {
  canApplySingleHistory,
  createPendingUserMessage,
  removePendingMessage,
  restoreFailedDraft,
  settlePendingMessage,
} from '../src/pages/chatOptimisticState.js';

test('single-chat optimistic messages carry a stable client identity', () => {
  assert.deepEqual(
    createPendingUserMessage('hello', '2026-07-15T10:00:00.000Z', 'client-1'),
    {
      role: 'user',
      content: 'hello',
      world_created_at: '2026-07-15T10:00:00.000Z',
      client_id: 'client-1',
      _pending: true,
    },
  );
});

test('successful single-chat sends settle only their own pending message', () => {
  const messages = [
    createPendingUserMessage('first', null, 'client-1'),
    createPendingUserMessage('second', null, 'client-2'),
  ];

  const settled = settlePendingMessage(messages, 'client-1');

  assert.equal(settled[0]._pending, false);
  assert.equal(settled[1]._pending, true);
});

test('failed single-chat sends remove only their own pending message', () => {
  const messages = [
    { role: 'assistant', content: 'existing' },
    createPendingUserMessage('first', null, 'client-1'),
    createPendingUserMessage('second', null, 'client-2'),
  ];

  assert.deepEqual(removePendingMessage(messages, 'client-1'), [
    { role: 'assistant', content: 'existing' },
    createPendingUserMessage('second', null, 'client-2'),
  ]);
});

test('single-chat history applies only to the conversation that requested it', () => {
  const request = {
    generation: 4,
    playerId: 'user-one',
    characterId: 'character-a',
  };

  assert.equal(canApplySingleHistory(request, {
    generation: 4,
    playerId: 'user-one',
    characterId: 'character-a',
  }), true);
  assert.equal(canApplySingleHistory(request, {
    generation: 5,
    playerId: 'user-one',
    characterId: 'character-b',
  }), false);
  assert.equal(canApplySingleHistory(request, {
    generation: 4,
    playerId: 'user-two',
    characterId: 'character-a',
  }), false);
});

test('failed send text is preserved ahead of a draft typed while waiting', () => {
  assert.equal(restoreFailedDraft('', 'first'), 'first');
  assert.equal(restoreFailedDraft('second', 'first'), 'first\nsecond');
  assert.equal(restoreFailedDraft('first', 'first'), 'first');
});
