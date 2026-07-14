import test from 'node:test';
import assert from 'node:assert/strict';

import { narrativePeriod } from '../src/utils/worldClock.js';

test('world clock derives the narrative period from a localized hour part', () => {
  const worldNow = new Date('2026-07-14T13:17:00.000Z');

  assert.equal(narrativePeriod(worldNow, 'Asia/Shanghai'), '傍晚');
  assert.equal(narrativePeriod(worldNow, 'UTC'), '中午');
});

test('world clock keeps late hours in the night period', () => {
  const worldNow = new Date('2026-07-14T15:30:00.000Z');

  assert.equal(narrativePeriod(worldNow, 'Asia/Shanghai'), '深夜');
});
