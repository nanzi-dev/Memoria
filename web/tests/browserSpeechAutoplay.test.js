import test from 'node:test';
import assert from 'node:assert/strict';

import { uniqueAutoplayDescriptors } from '../src/hooks/useBrowserSpeech.js';

test('autoplay descriptors are unique within and across enqueue calls', () => {
  const seenKeys = new Set();

  assert.deepEqual(
    uniqueAutoplayDescriptors([7, 7, 8], 'session-one', 'single', seenKeys),
    [
      { mode: 'single', sessionId: 'session-one', messageId: 7 },
      { mode: 'single', sessionId: 'session-one', messageId: 8 },
    ],
  );
  assert.deepEqual(
    uniqueAutoplayDescriptors([7, 8], 'session-one', 'single', seenKeys),
    [],
  );
  assert.deepEqual(
    uniqueAutoplayDescriptors(7, 'session-two', 'single', seenKeys),
    [{ mode: 'single', sessionId: 'session-two', messageId: 7 }],
  );
});

test('autoplay descriptors require a session and mode', () => {
  const seenKeys = new Set();

  assert.deepEqual(uniqueAutoplayDescriptors(7, null, 'single', seenKeys), []);
  assert.deepEqual(uniqueAutoplayDescriptors(7, 'session-one', null, seenKeys), []);
  assert.equal(seenKeys.size, 0);
});
