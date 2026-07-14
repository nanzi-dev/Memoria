import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { userApi } from '../api/memoria';
import { shouldApplyClockRevision } from './worldClockState';

const UserContext = createContext(null);
const CLOCK_REFRESH_MS = 60_000;
const CLOCK_STALE_MS = 90_000;
const INBOX_REFRESH_MS = 20_000;

function nowPerformance() {
  return typeof performance === 'undefined' ? 0 : performance.now();
}

export function useUser() {
  return useContext(UserContext);
}

export function UserProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [worldClock, setWorldClockState] = useState(null);
  const [clockStatus, setClockStatus] = useState({
    state: 'idle',
    message: '',
    lastSyncedAt: null,
  });
  const [eventInbox, setEventInbox] = useState([]);
  const clockAnchorRef = useRef(null);
  const clockRevisionRef = useRef(null);
  const clockRefreshPromiseRef = useRef(null);
  const lastClockSyncPerformanceRef = useRef(null);
  const timezoneReportedForRef = useRef(null);

  const applyClock = useCallback((clock, timing = {}) => {
    if (!clock?.world_now) return;
    if (!shouldApplyClockRevision(
      clockRevisionRef.current,
      clock.clock_revision,
    )) return;
    const worldMilliseconds = Date.parse(clock.world_now);
    if (!Number.isFinite(worldMilliseconds)) return;

    const requestStart = Number.isFinite(timing.requestStart)
      ? timing.requestStart
      : nowPerformance();
    const requestEnd = Number.isFinite(timing.requestEnd)
      ? timing.requestEnd
      : requestStart;
    const anchorPerformance = requestStart + Math.max(0, requestEnd - requestStart) / 2;

    clockAnchorRef.current = {
      worldMilliseconds,
      anchorPerformance,
      timeScale: Number(clock.time_scale) || 0,
    };
    clockRevisionRef.current = clock.clock_revision;
    lastClockSyncPerformanceRef.current = requestEnd;
    setWorldClockState(clock);
    setUser(current => current ? { ...current, ...clock } : current);
    setClockStatus({ state: 'synced', message: '', lastSyncedAt: Date.now() });
  }, []);

  const getWorldNow = useCallback(() => {
    const anchor = clockAnchorRef.current;
    if (!anchor) return null;
    const elapsed = Math.max(0, nowPerformance() - anchor.anchorPerformance);
    return new Date(anchor.worldMilliseconds + elapsed * anchor.timeScale);
  }, []);

  const refreshWorldClock = useCallback(async ({ showLoading = false } = {}) => {
    if (clockRefreshPromiseRef.current) return clockRefreshPromiseRef.current;

    if (showLoading) {
      setClockStatus(current => ({ ...current, state: 'refreshing', message: '正在校准世界时间' }));
    }
    const requestStart = nowPerformance();
    const request = userApi.getWorldClock()
      .then(clock => {
        applyClock(clock, { requestStart, requestEnd: nowPerformance() });
        return clock;
      })
      .catch(error => {
        const offline = typeof navigator !== 'undefined' && !navigator.onLine;
        setClockStatus(current => ({
          ...current,
          state: offline ? 'offline' : 'error',
          message: offline ? '当前离线，世界时间可能已过期' : '世界时间校准失败，显示可能已过期',
        }));
        throw error;
      })
      .finally(() => {
        clockRefreshPromiseRef.current = null;
      });
    clockRefreshPromiseRef.current = request;
    return request;
  }, [applyClock]);

  const runClockWrite = useCallback(async (operation) => {
    const expectedRevision = clockRevisionRef.current;
    if (!Number.isInteger(expectedRevision)) {
      throw new Error('世界时钟尚未加载，请稍后重试');
    }

    setClockStatus(current => ({ ...current, state: 'refreshing', message: '正在更新世界时间' }));
    const requestStart = nowPerformance();
    try {
      const clock = await operation(expectedRevision);
      applyClock(clock, { requestStart, requestEnd: nowPerformance() });
      return clock;
    } catch (error) {
      if (error.status === 409) {
        try {
          await refreshWorldClock();
        } catch {
          // The conflict remains actionable even if the recovery refresh also fails.
        }
        setClockStatus(current => ({
          ...current,
          state: 'conflict',
          message: '检测到其他页面修改，已重新加载最新世界时间',
        }));
        error.clockRecovered = true;
      } else {
        const offline = typeof navigator !== 'undefined' && !navigator.onLine;
        setClockStatus(current => ({
          ...current,
          state: offline ? 'offline' : 'error',
          message: offline ? '当前离线，无法更新时间' : (error.message || '世界时间更新失败'),
        }));
      }
      throw error;
    }
  }, [applyClock, refreshWorldClock]);

  const updateWorldClock = useCallback((updates) => (
    runClockWrite(expectedRevision => userApi.updateWorldClock({
      ...updates,
      expectedRevision,
    }))
  ), [runClockWrite]);

  const syncWorldClock = useCallback(() => (
    runClockWrite(expectedRevision => userApi.syncWorldClock(expectedRevision))
  ), [runClockWrite]);

  const setWorldClock = useCallback((worldNow) => (
    runClockWrite(expectedRevision => userApi.setWorldClock(worldNow, expectedRevision))
  ), [runClockWrite]);

  const advanceWorldClock = useCallback((seconds) => (
    runClockWrite(expectedRevision => userApi.advanceWorldClock(seconds, expectedRevision))
  ), [runClockWrite]);

  const initializeClock = useCallback(async (baseUser, timing = {}) => {
    if (!baseUser) return;
    applyClock(baseUser, timing);

    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const reportKey = `${baseUser.user_id}:${browserTimezone}:device`;
    if (
      browserTimezone
      && (
        baseUser.timezone_mode !== 'device'
        || browserTimezone !== baseUser.timezone
      )
      && timezoneReportedForRef.current !== reportKey
    ) {
      timezoneReportedForRef.current = reportKey;
      try {
        await updateWorldClock({ timezone: browserTimezone, timezoneMode: 'device' });
      } catch {
        timezoneReportedForRef.current = null;
      }
    }
  }, [applyClock, updateWorldClock]);

  useEffect(() => {
    let cancelled = false;
    localStorage.removeItem('memoria-token');
    const requestStart = nowPerformance();
    userApi.getMe()
      .then(async nextUser => {
        if (cancelled) return;
        setUser(nextUser);
        await initializeClock(nextUser, { requestStart, requestEnd: nowPerformance() });
      })
      .catch(() => {
        if (cancelled) return;
        setUser(null);
        setWorldClockState(null);
        clockAnchorRef.current = null;
        clockRevisionRef.current = null;
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [initializeClock]);

  useEffect(() => {
    if (!user) {
      setEventInbox([]);
      return undefined;
    }
    let cancelled = false;

    const refreshClockSnapshot = () => {
      refreshWorldClock().catch(() => {});
    };
    const refreshInbox = () => {
      userApi.getEventInbox(true, 50)
        .then(items => { if (!cancelled) setEventInbox(items); })
        .catch(() => {});
    };
    const handleFocus = () => refreshClockSnapshot();
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') refreshClockSnapshot();
    };
    const handleOnline = () => refreshClockSnapshot();
    const handleOffline = () => {
      setClockStatus(current => ({
        ...current,
        state: 'offline',
        message: '当前离线，世界时间可能已过期',
      }));
    };

    refreshInbox();
    const clockTimer = setInterval(refreshClockSnapshot, CLOCK_REFRESH_MS);
    const inboxTimer = setInterval(refreshInbox, INBOX_REFRESH_MS);
    const staleTimer = setInterval(() => {
      const lastSync = lastClockSyncPerformanceRef.current;
      if (lastSync == null || nowPerformance() - lastSync <= CLOCK_STALE_MS) return;
      setClockStatus(current => {
        if (!['synced', 'idle'].includes(current.state)) return current;
        return { ...current, state: 'stale', message: '世界时间快照已过期，正在等待重新校准' };
      });
    }, 15_000);

    window.addEventListener('focus', handleFocus);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      cancelled = true;
      clearInterval(clockTimer);
      clearInterval(inboxTimer);
      clearInterval(staleTimer);
      window.removeEventListener('focus', handleFocus);
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, [user?.user_id, refreshWorldClock]);

  const login = useCallback(async (username, password) => {
    const requestStart = nowPerformance();
    const response = await userApi.login(username, password);
    setUser(response.user);
    await initializeClock(response.user, { requestStart, requestEnd: nowPerformance() });
    return response.user;
  }, [initializeClock]);

  const register = useCallback(async (username, password, gender) => {
    const requestStart = nowPerformance();
    const response = await userApi.register(username, password, gender);
    setUser(response.user);
    await initializeClock(response.user, { requestStart, requestEnd: nowPerformance() });
    return response.user;
  }, [initializeClock]);

  const logout = useCallback(() => {
    userApi.logout().catch(() => {});
    setUser(null);
    setWorldClockState(null);
    setClockStatus({ state: 'idle', message: '', lastSyncedAt: null });
    setEventInbox([]);
    clockAnchorRef.current = null;
    clockRevisionRef.current = null;
    lastClockSyncPerformanceRef.current = null;
    timezoneReportedForRef.current = null;
  }, []);

  const refresh = useCallback(async () => {
    const requestStart = nowPerformance();
    try {
      const nextUser = await userApi.getMe();
      setUser(nextUser);
      await initializeClock(nextUser, { requestStart, requestEnd: nowPerformance() });
      return nextUser;
    } catch {
      return null;
    }
  }, [initializeClock]);

  const refreshEventInbox = useCallback(async () => {
    const items = await userApi.getEventInbox(true, 50);
    setEventInbox(items);
    return items;
  }, []);

  const markEventRead = useCallback(async (inboxId) => {
    await userApi.markEventRead(inboxId);
    setEventInbox(items => items.filter(item => item.id !== inboxId));
  }, []);

  const contextValue = useMemo(() => ({
    user,
    loading,
    worldClock,
    clockStatus,
    eventInbox,
    login,
    register,
    logout,
    refresh,
    refreshWorldClock,
    getWorldNow,
    updateWorldClock,
    syncWorldClock,
    setWorldClock,
    advanceWorldClock,
    refreshEventInbox,
    markEventRead,
  }), [
    user,
    loading,
    worldClock,
    clockStatus,
    eventInbox,
    login,
    register,
    logout,
    refresh,
    refreshWorldClock,
    getWorldNow,
    updateWorldClock,
    syncWorldClock,
    setWorldClock,
    advanceWorldClock,
    refreshEventInbox,
    markEventRead,
  ]);

  return (
    <UserContext.Provider value={contextValue}>
      {children}
    </UserContext.Provider>
  );
}
