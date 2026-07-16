import test from 'node:test';
import assert from 'node:assert/strict';

import {
  isDialogueTurnProcessingConflict,
  retryDialogueTurnConflict,
} from '../src/utils/dialogueFallback.js';

function processingConflict() {
  const error = new Error('该请求正在处理中');
  error.status = 409;
  error.body = { detail: '该请求正在处理中' };
  return error;
}

test('retryDialogueTurnConflict polls the same legacy request until it completes', async () => {
  const attempts = [];
  const sleeps = [];

  const result = await retryDialogueTurnConflict(
    async () => {
      attempts.push(attempts.length + 1);
      if (attempts.length < 3) throw processingConflict();
      return { dialogue: '完成' };
    },
    {
      maxAttempts: 4,
      initialDelayMs: 10,
      maxDelayMs: 20,
      sleep: async delay => sleeps.push(delay),
    },
  );

  assert.deepEqual(result, { dialogue: '完成' });
  assert.deepEqual(attempts, [1, 2, 3]);
  assert.deepEqual(sleeps, [10, 20]);
});

test('retryDialogueTurnConflict does not retry unrelated conflicts', async () => {
  const error = new Error('该会话已有消息正在处理中');
  error.status = 409;
  error.body = { detail: '该会话已有消息正在处理中' };
  let attempts = 0;

  await assert.rejects(
    retryDialogueTurnConflict(async () => {
      attempts += 1;
      throw error;
    }),
    error,
  );

  assert.equal(attempts, 1);
  assert.equal(isDialogueTurnProcessingConflict(error), false);
});

test('retryDialogueTurnConflict stops after its bounded attempt budget', async () => {
  const error = processingConflict();
  let attempts = 0;

  await assert.rejects(
    retryDialogueTurnConflict(
      async () => {
        attempts += 1;
        throw error;
      },
      {
        maxAttempts: 3,
        sleep: async () => {},
      },
    ),
    error,
  );

  assert.equal(attempts, 3);
  assert.equal(isDialogueTurnProcessingConflict(error), true);
});

test('retryDialogueTurnConflict rechecks request ownership after waiting', async () => {
  const error = processingConflict();
  let attempts = 0;
  let current = true;

  await assert.rejects(
    retryDialogueTurnConflict(
      async () => {
        attempts += 1;
        throw error;
      },
      {
        maxAttempts: 3,
        sleep: async () => {
          current = false;
        },
        shouldRetry: () => current,
      },
    ),
    error,
  );

  assert.equal(attempts, 1);
});

test('default retry budget covers the backend dialogue execution window', async () => {
  const error = processingConflict();
  const sleeps = [];
  let attempts = 0;

  await assert.rejects(
    retryDialogueTurnConflict(
      async () => {
        attempts += 1;
        throw error;
      },
      {
        sleep: async delay => sleeps.push(delay),
      },
    ),
    error,
  );

  assert.ok(attempts >= 120);
  assert.ok(sleeps.reduce((total, delay) => total + delay, 0) >= 240_000);
});
