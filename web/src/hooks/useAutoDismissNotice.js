import { useCallback, useEffect, useRef, useState } from 'react';

const DEFAULT_DURATION_MS = 1800;

/**
 * 管理会自动消失的提示文案，并保证组件卸载后清理定时器，
 * 避免 setTimeout(() => setState(...)) 在卸载后继续执行。
 */
export default function useAutoDismissNotice(durationMs = DEFAULT_DURATION_MS) {
  const [notice, setNoticeState] = useState('');
  const timerRef = useRef(null);

  const clearNotice = useCallback(() => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setNoticeState('');
  }, []);

  const setNotice = useCallback((text) => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setNoticeState(text);
    if (!text) return;
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setNoticeState('');
    }, durationMs);
  }, [durationMs]);

  useEffect(() => () => {
    if (timerRef.current != null) clearTimeout(timerRef.current);
  }, []);

  return [notice, setNotice, clearNotice];
}
