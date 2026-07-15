export function createTimeoutController(
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
) {
  let timerId = null;

  return {
    schedule(callback, delay) {
      if (timerId != null) clearTimer(timerId);
      timerId = setTimer(() => {
        timerId = null;
        callback();
      }, delay);
      return timerId;
    },
    cancel() {
      if (timerId == null) return;
      clearTimer(timerId);
      timerId = null;
    },
  };
}
