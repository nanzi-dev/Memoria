export function createSerialTaskQueue() {
  let tail = Promise.resolve();

  return {
    enqueue(task) {
      const result = tail.then(task, task);
      tail = result.catch(() => {});
      return result;
    },
  };
}

export function createRequestEpoch() {
  let generation = 0;

  return {
    capture(ownerId = null) {
      return { generation, ownerId };
    },
    advance(ownerId = null) {
      generation += 1;
      return { generation, ownerId };
    },
    invalidate() {
      generation += 1;
    },
    isGenerationCurrent(token) {
      return token?.generation === generation;
    },
    isCurrent(token, ownerId = token?.ownerId ?? null) {
      return token?.generation === generation && token?.ownerId === ownerId;
    },
  };
}

export function beginOwnedRequest(epoch, ownerId, currentOwnerId) {
  if (!ownerId || ownerId !== currentOwnerId) return null;
  return epoch.advance(ownerId);
}

export async function withRequestTimeout(
  requestFactory,
  timeoutMs,
  {
    setTimer = globalThis.setTimeout,
    clearTimer = globalThis.clearTimeout,
  } = {},
) {
  const controller = new AbortController();
  const timerId = setTimer(() => {
    controller.abort(new DOMException('Request timed out', 'AbortError'));
  }, timeoutMs);
  try {
    return await requestFactory(controller.signal);
  } finally {
    clearTimer(timerId);
  }
}

export async function completeLogoutMutation({
  isCurrent,
  sendLogout,
  clearCurrent,
  reconcileCurrent,
}) {
  try {
    await sendLogout();
    if (isCurrent()) clearCurrent();
    return true;
  } catch {
    if (isCurrent()) await reconcileCurrent();
    return false;
  }
}

export async function reconcileLatestRequestState({
  isCurrent,
  readCurrent,
  applyCurrent,
  clearCurrent,
}) {
  if (!isCurrent()) return false;

  try {
    const current = await readCurrent();
    if (!isCurrent()) return false;
    await applyCurrent(current);
    return isCurrent();
  } catch (error) {
    if (isCurrent() && (error?.status === 401 || error?.status === 403)) {
      clearCurrent();
    }
    return false;
  }
}
