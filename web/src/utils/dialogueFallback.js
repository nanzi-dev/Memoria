const DEFAULT_MAX_ATTEMPTS = 124;
const DEFAULT_INITIAL_DELAY_MS = 250;
const DEFAULT_MAX_DELAY_MS = 2000;

const defaultSleep = delay => new Promise(resolve => {
  setTimeout(resolve, delay);
});

export function isDialogueTurnProcessingConflict(error) {
  if (error?.status !== 409) return false;
  const detail = typeof error?.body?.detail === 'string'
    ? error.body.detail
    : error?.message;
  return String(detail || '').includes('该请求正在处理中');
}

export async function retryDialogueTurnConflict(
  sendLegacyRequest,
  {
    maxAttempts = DEFAULT_MAX_ATTEMPTS,
    initialDelayMs = DEFAULT_INITIAL_DELAY_MS,
    maxDelayMs = DEFAULT_MAX_DELAY_MS,
    sleep = defaultSleep,
    shouldRetry = () => true,
  } = {},
) {
  const attempts = Math.max(1, Math.floor(maxAttempts));
  const initialDelay = Math.max(0, Number(initialDelayMs) || 0);
  const maximumDelay = Math.max(initialDelay, Number(maxDelayMs) || 0);

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await sendLegacyRequest();
    } catch (error) {
      const canRetry = (
        attempt < attempts - 1
        && shouldRetry()
        && isDialogueTurnProcessingConflict(error)
      );
      if (!canRetry) throw error;
      const delay = Math.min(initialDelay * (2 ** attempt), maximumDelay);
      await sleep(delay);
      if (!shouldRetry()) throw error;
    }
  }

  throw new Error('Dialogue fallback retry budget exhausted');
}
