import test from 'node:test';
import assert from 'node:assert/strict';

import { shouldApplyClockRevision } from '../src/context/worldClockState.js';

test('world clock ignores a stale response after a newer write', () => {
  assert.equal(shouldApplyClockRevision(8, 7), false);
  assert.equal(shouldApplyClockRevision(8, 8), true);
  assert.equal(shouldApplyClockRevision(8, 9), true);
});

test('world clock accepts initial snapshots without revisions', () => {
  assert.equal(shouldApplyClockRevision(null, 1), true);
  assert.equal(shouldApplyClockRevision(null, undefined), true);
});
