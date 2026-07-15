import test from 'node:test';
import assert from 'node:assert/strict';

import {
  characterEditorPath,
  eventEditorPath,
  isActivationKey,
} from '../src/utils/navigationState.js';
import { createTimeoutController } from '../src/utils/timeoutController.js';

test('dynamic editor routes encode IDs as individual path segments', () => {
  assert.equal(characterEditorPath('npc/a?b'), '/editor/npc%2Fa%3Fb');
  assert.equal(eventEditorPath('event #1'), '/events/event%20%231');
});

test('keyboard activation accepts Enter and Space only', () => {
  assert.equal(isActivationKey('Enter'), true);
  assert.equal(isActivationKey(' '), true);
  assert.equal(isActivationKey('Escape'), false);
});

test('timeout controller replaces stale callbacks and cancels on cleanup', () => {
  const callbacks = new Map();
  const cleared = [];
  let nextId = 0;
  const controller = createTimeoutController(
    (callback) => {
      nextId += 1;
      callbacks.set(nextId, callback);
      return nextId;
    },
    (id) => {
      cleared.push(id);
      callbacks.delete(id);
    },
  );

  controller.schedule(() => {}, 100);
  controller.schedule(() => {}, 200);
  assert.deepEqual(cleared, [1]);
  assert.equal(callbacks.has(2), true);

  controller.cancel();
  assert.deepEqual(cleared, [1, 2]);
  assert.equal(callbacks.size, 0);
});
