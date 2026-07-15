import test from 'node:test';
import assert from 'node:assert/strict';

import {
  beginOwnedRequest,
  completeLogoutMutation,
  createRequestEpoch,
  createSerialTaskQueue,
  reconcileLatestRequestState,
  withRequestTimeout,
} from '../src/utils/asyncRequestState.js';

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test('serial task queue preserves auth mutation order', async () => {
  const queue = createSerialTaskQueue();
  const first = deferred();
  const calls = [];

  const logout = queue.enqueue(async () => {
    calls.push('logout:start');
    await first.promise;
    calls.push('logout:end');
  });
  const login = queue.enqueue(async () => {
    calls.push('login');
  });

  await Promise.resolve();
  assert.deepEqual(calls, ['logout:start']);

  first.resolve();
  await Promise.all([logout, login]);
  assert.deepEqual(calls, ['logout:start', 'logout:end', 'login']);
});

test('serial task queue continues after a rejected mutation', async () => {
  const queue = createSerialTaskQueue();
  const calls = [];

  await assert.rejects(queue.enqueue(async () => {
    calls.push('login');
    throw new Error('invalid credentials');
  }), /invalid credentials/);

  await queue.enqueue(async () => {
    calls.push('logout');
  });
  assert.deepEqual(calls, ['login', 'logout']);
});

test('request epoch rejects stale generations and wrong account owners', () => {
  const epoch = createRequestEpoch();
  const firstAccount = epoch.capture('user-one');
  const secondAccount = epoch.advance('user-two');

  assert.equal(epoch.isGenerationCurrent(firstAccount), false);
  assert.equal(epoch.isGenerationCurrent(secondAccount), true);
  assert.equal(epoch.isCurrent(firstAccount, 'user-one'), false);
  assert.equal(epoch.isCurrent(secondAccount, 'user-one'), false);
  assert.equal(epoch.isCurrent(secondAccount, 'user-two'), true);

  epoch.invalidate();
  assert.equal(epoch.isGenerationCurrent(secondAccount), false);
  assert.equal(epoch.isCurrent(secondAccount, 'user-two'), false);
});

test('latest failed auth mutation reconciles an earlier successful cookie response', async () => {
  const queue = createSerialTaskQueue();
  const epoch = createRequestEpoch();
  let cookieUser = null;
  let committedUser = null;

  const firstToken = epoch.advance();
  const first = queue.enqueue(async () => {
    cookieUser = { user_id: 'user-one' };
    if (epoch.isGenerationCurrent(firstToken)) committedUser = cookieUser;
  });

  const secondToken = epoch.advance();
  const second = queue.enqueue(async () => {
    await reconcileLatestRequestState({
      isCurrent: () => epoch.isGenerationCurrent(secondToken),
      readCurrent: async () => cookieUser,
      applyCurrent: async user => { committedUser = user; },
      clearCurrent: () => { committedUser = null; },
    });
    throw new Error('invalid credentials');
  });

  await first;
  await assert.rejects(second, /invalid credentials/);
  assert.deepEqual(committedUser, { user_id: 'user-one' });
});

test('failed reconciliation preserves local state on network errors', async () => {
  let currentUser = { user_id: 'user-one' };

  await reconcileLatestRequestState({
    isCurrent: () => true,
    readCurrent: async () => {
      throw new TypeError('fetch failed');
    },
    applyCurrent: async user => { currentUser = user; },
    clearCurrent: () => { currentUser = null; },
  });

  assert.deepEqual(currentUser, { user_id: 'user-one' });
});

test('failed reconciliation clears local state on unauthenticated response', async () => {
  let currentUser = { user_id: 'user-one' };

  await reconcileLatestRequestState({
    isCurrent: () => true,
    readCurrent: async () => {
      const error = new Error('unauthenticated');
      error.status = 401;
      throw error;
    },
    applyCurrent: async user => { currentUser = user; },
    clearCurrent: () => { currentUser = null; },
  });

  assert.equal(currentUser, null);
});

test('stale owner callbacks do not invalidate the current request epoch', () => {
  const epoch = createRequestEpoch();
  const currentScope = epoch.advance('user-two');

  assert.equal(beginOwnedRequest(epoch, 'user-one', 'user-two'), null);
  assert.equal(epoch.isCurrent(currentScope, 'user-two'), true);
});

test('request timeout aborts a hanging auth mutation and clears its timer', async () => {
  let abortSignal = null;
  let scheduled = null;
  let cleared = null;
  const timers = {
    setTimer(callback) {
      scheduled = callback;
      return 17;
    },
    clearTimer(timerId) {
      cleared = timerId;
    },
  };

  const request = withRequestTimeout(
    signal => new Promise((resolve, reject) => {
      abortSignal = signal;
      signal.addEventListener('abort', () => reject(signal.reason));
    }),
    10_000,
    timers,
  );

  assert.equal(abortSignal.aborted, false);
  scheduled();
  await assert.rejects(request, error => error?.name === 'AbortError');
  assert.equal(abortSignal.aborted, true);
  assert.equal(cleared, 17);
});

test('failed latest logout reconciles the still-authenticated cookie state', async () => {
  let currentUser = { user_id: 'user-one' };

  const success = await completeLogoutMutation({
    isCurrent: () => true,
    sendLogout: async () => {
      throw new TypeError('fetch failed');
    },
    clearCurrent: () => { currentUser = null; },
    reconcileCurrent: async () => {
      currentUser = { user_id: 'user-one', username: 'alice' };
    },
  });

  assert.equal(success, false);
  assert.deepEqual(currentUser, { user_id: 'user-one', username: 'alice' });
});

test('successful latest logout clears local account state only after the response', async () => {
  let currentUser = { user_id: 'user-one' };
  const response = deferred();

  const logout = completeLogoutMutation({
    isCurrent: () => true,
    sendLogout: () => response.promise,
    clearCurrent: () => { currentUser = null; },
    reconcileCurrent: async () => {},
  });

  await Promise.resolve();
  assert.deepEqual(currentUser, { user_id: 'user-one' });

  response.resolve();
  await logout;
  assert.equal(currentUser, null);
});
