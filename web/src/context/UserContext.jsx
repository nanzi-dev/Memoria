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
import {
  completeLogoutMutation,
  createRequestEpoch,
  createSerialTaskQueue,
  reconcileLatestRequestState,
  withRequestTimeout,
} from '../utils/asyncRequestState';
import { shouldApplyClockRevision } from './worldClockState';

const UserContext = createContext(null);
const CLOCK_REFRESH_MS = 60_000;
const CLOCK_STALE_MS = 90_000;
const INBOX_REFRESH_MS = 20_000;
const AUTH_REQUEST_TIMEOUT_MS = 15_000;

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
  const activeUserIdRef = useRef(null);
  const authEpochRef = useRef(null);
  const authMutationQueueRef = useRef(null);
  if (!authEpochRef.current) authEpochRef.current = createRequestEpoch();
  if (!authMutationQueueRef.current) authMutationQueueRef.current = createSerialTaskQueue();

  const isRequestCurrent = useCallback((scope) => (
    authEpochRef.current.isCurrent(scope, activeUserIdRef.current)
  ), []);

  const clearAccountState = useCallback(() => {
    activeUserIdRef.current = null;
    setUser(null);
    setWorldClockState(null);
    setClockStatus({ state: 'idle', message: '', lastSyncedAt: null });
    setEventInbox([]);
    clockAnchorRef.current = null;
    clockRevisionRef.current = null;
    clockRefreshPromiseRef.current = null;
    lastClockSyncPerformanceRef.current = null;
    timezoneReportedForRef.current = null;
  }, []);

  const applyClock = useCallback((clock, timing = {}, requestScope = null) => {
    const scope = requestScope || authEpochRef.current.capture(activeUserIdRef.current);
    if (!isRequestCurrent(scope) || !clock?.world_now) return false;
    if (!shouldApplyClockRevision(
      clockRevisionRef.current,
      clock.clock_revision,
    )) return false;
    const worldMilliseconds = Date.parse(clock.world_now);
    if (!Number.isFinite(worldMilliseconds)) return false;

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
    setUser(current => (
      current?.user_id === scope.ownerId
        ? { ...current, ...clock }
        : current
    ));
    setClockStatus({ state: 'synced', message: '', lastSyncedAt: Date.now() });
    return true;
  }, [isRequestCurrent]);

  const getWorldNow = useCallback(() => {
    const anchor = clockAnchorRef.current;
    if (!anchor) return null;
    const elapsed = Math.max(0, nowPerformance() - anchor.anchorPerformance);
    return new Date(anchor.worldMilliseconds + elapsed * anchor.timeScale);
  }, []);

  const refreshWorldClock = useCallback(async ({ showLoading = false } = {}) => {
    const requestScope = authEpochRef.current.capture(activeUserIdRef.current);
    if (!requestScope.ownerId) throw new Error('请先登录后使用世界时钟');

    const inFlight = clockRefreshPromiseRef.current;
    if (
      inFlight
      && authEpochRef.current.isCurrent(inFlight.scope, activeUserIdRef.current)
    ) {
      return inFlight.promise;
    }

    if (showLoading && isRequestCurrent(requestScope)) {
      setClockStatus(current => ({ ...current, state: 'refreshing', message: '正在校准世界时间' }));
    }
    const requestStart = nowPerformance();
    const request = userApi.getWorldClock()
      .then(clock => {
        applyClock(
          clock,
          { requestStart, requestEnd: nowPerformance() },
          requestScope,
        );
        return clock;
      })
      .catch(error => {
        if (isRequestCurrent(requestScope)) {
          const offline = typeof navigator !== 'undefined' && !navigator.onLine;
          setClockStatus(current => ({
            ...current,
            state: offline ? 'offline' : 'error',
            message: offline ? '当前离线，世界时间可能已过期' : '世界时间校准失败，显示可能已过期',
          }));
        }
        throw error;
      })
      .finally(() => {
        if (clockRefreshPromiseRef.current?.promise === request) {
          clockRefreshPromiseRef.current = null;
        }
      });
    clockRefreshPromiseRef.current = { scope: requestScope, promise: request };
    return request;
  }, [applyClock, isRequestCurrent]);

  const runClockWrite = useCallback(async (operation) => {
    const requestScope = authEpochRef.current.capture(activeUserIdRef.current);
    if (!requestScope.ownerId) {
      throw new Error('请先登录后使用世界时钟');
    }
    const expectedRevision = clockRevisionRef.current;
    if (!Number.isInteger(expectedRevision)) {
      throw new Error('世界时钟尚未加载，请稍后重试');
    }

    if (isRequestCurrent(requestScope)) {
      setClockStatus(current => ({ ...current, state: 'refreshing', message: '正在更新世界时间' }));
    }
    const requestStart = nowPerformance();
    try {
      const clock = await operation(expectedRevision);
      applyClock(
        clock,
        { requestStart, requestEnd: nowPerformance() },
        requestScope,
      );
      return clock;
    } catch (error) {
      if (!isRequestCurrent(requestScope)) throw error;
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
  }, [applyClock, isRequestCurrent, refreshWorldClock]);

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

  const initializeClock = useCallback(async (baseUser, timing = {}, requestScope = null) => {
    if (!baseUser) return;
    const scope = requestScope || authEpochRef.current.capture(baseUser.user_id);
    if (!isRequestCurrent(scope)) return;
    applyClock(baseUser, timing, scope);

    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const reportKey = `${baseUser.user_id}:${browserTimezone}:device`;
    if (
      browserTimezone
      && (
        baseUser.timezone_mode !== 'device'
        || browserTimezone !== baseUser.timezone
      )
      && timezoneReportedForRef.current !== reportKey
      && isRequestCurrent(scope)
    ) {
      timezoneReportedForRef.current = reportKey;
      try {
        await updateWorldClock({ timezone: browserTimezone, timezoneMode: 'device' });
      } catch {
        if (isRequestCurrent(scope) && timezoneReportedForRef.current === reportKey) {
          timezoneReportedForRef.current = null;
        }
      }
    }
  }, [applyClock, isRequestCurrent, updateWorldClock]);

  const commitAuthenticatedUser = useCallback(async (nextUser, timing, authToken) => {
    if (!nextUser || !authEpochRef.current.isGenerationCurrent(authToken)) return false;

    clearAccountState();
    const requestScope = {
      generation: authToken.generation,
      ownerId: nextUser.user_id,
    };
    activeUserIdRef.current = nextUser.user_id;
    setUser(nextUser);
    setLoading(false);
    await initializeClock(nextUser, timing, requestScope);
    return isRequestCurrent(requestScope);
  }, [clearAccountState, initializeClock, isRequestCurrent]);

  const reconcileAuthState = useCallback((authToken, requestStart) => (
    reconcileLatestRequestState({
      isCurrent: () => authEpochRef.current.isGenerationCurrent(authToken),
      readCurrent: () => withRequestTimeout(
        signal => userApi.getMe({ signal }),
        AUTH_REQUEST_TIMEOUT_MS,
      ),
      applyCurrent: nextUser => commitAuthenticatedUser(
        nextUser,
        { requestStart, requestEnd: nowPerformance() },
        authToken,
      ),
      clearCurrent: clearAccountState,
    })
  ), [clearAccountState, commitAuthenticatedUser]);

  useEffect(() => {
    let cancelled = false;
    localStorage.removeItem('memoria-token');
    const authToken = authEpochRef.current.capture();
    const requestStart = nowPerformance();
    userApi.getMe()
      .then(async nextUser => {
        if (cancelled || !authEpochRef.current.isGenerationCurrent(authToken)) return;
        await commitAuthenticatedUser(
          nextUser,
          { requestStart, requestEnd: nowPerformance() },
          authToken,
        );
      })
      .catch(() => {
        if (cancelled || !authEpochRef.current.isGenerationCurrent(authToken)) return;
        clearAccountState();
      })
      .finally(() => {
        if (!cancelled && authEpochRef.current.isGenerationCurrent(authToken)) {
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [clearAccountState, commitAuthenticatedUser]);

  useEffect(() => {
    if (!user) {
      setEventInbox([]);
      return undefined;
    }
    let cancelled = false;
    const requestScope = authEpochRef.current.capture(user.user_id);

    const refreshClockSnapshot = () => {
      refreshWorldClock().catch(() => {});
    };
    const refreshInbox = () => {
      userApi.getEventInbox(true, 50)
        .then(items => {
          if (!cancelled && isRequestCurrent(requestScope)) setEventInbox(items);
        })
        .catch(() => {});
    };
    const handleFocus = () => refreshClockSnapshot();
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') refreshClockSnapshot();
    };
    const handleOnline = () => refreshClockSnapshot();
    const handleOffline = () => {
      if (!isRequestCurrent(requestScope)) return;
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
      if (!isRequestCurrent(requestScope)) return;
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
  }, [user?.user_id, isRequestCurrent, refreshWorldClock]);

  const login = useCallback(async (username, password) => {
    const authToken = authEpochRef.current.advance();
    setLoading(false);
    return authMutationQueueRef.current.enqueue(async () => {
      const requestStart = nowPerformance();
      try {
        const response = await withRequestTimeout(
          signal => userApi.login(username, password, { signal }),
          AUTH_REQUEST_TIMEOUT_MS,
        );
        await commitAuthenticatedUser(
          response.user,
          { requestStart, requestEnd: nowPerformance() },
          authToken,
        );
        return response.user;
      } catch (error) {
        await reconcileAuthState(authToken, requestStart);
        throw error;
      }
    });
  }, [commitAuthenticatedUser, reconcileAuthState]);

  const register = useCallback(async (username, password, gender) => {
    const authToken = authEpochRef.current.advance();
    setLoading(false);
    return authMutationQueueRef.current.enqueue(async () => {
      const requestStart = nowPerformance();
      try {
        const response = await withRequestTimeout(
          signal => userApi.register(username, password, gender, { signal }),
          AUTH_REQUEST_TIMEOUT_MS,
        );
        await commitAuthenticatedUser(
          response.user,
          { requestStart, requestEnd: nowPerformance() },
          authToken,
        );
        return response.user;
      } catch (error) {
        await reconcileAuthState(authToken, requestStart);
        throw error;
      }
    });
  }, [commitAuthenticatedUser, reconcileAuthState]);

  const logout = useCallback(() => {
    const authToken = authEpochRef.current.advance();
    setLoading(false);
    const requestStart = nowPerformance();
    return authMutationQueueRef.current.enqueue(() => completeLogoutMutation({
      isCurrent: () => authEpochRef.current.isGenerationCurrent(authToken),
      sendLogout: () => withRequestTimeout(
        signal => userApi.logout({ signal }),
        AUTH_REQUEST_TIMEOUT_MS,
      ),
      clearCurrent: clearAccountState,
      reconcileCurrent: () => reconcileAuthState(authToken, requestStart),
    }));
  }, [clearAccountState, reconcileAuthState]);

  const refresh = useCallback(async () => {
    const authToken = authEpochRef.current.capture();
    const requestStart = nowPerformance();
    try {
      const nextUser = await userApi.getMe();
      if (!authEpochRef.current.isGenerationCurrent(authToken)) return null;
      await commitAuthenticatedUser(
        nextUser,
        { requestStart, requestEnd: nowPerformance() },
        authToken,
      );
      return nextUser;
    } catch {
      return null;
    }
  }, [commitAuthenticatedUser]);

  const refreshEventInbox = useCallback(async () => {
    const requestScope = authEpochRef.current.capture(activeUserIdRef.current);
    if (!requestScope.ownerId) return [];
    const items = await userApi.getEventInbox(true, 50);
    if (isRequestCurrent(requestScope)) setEventInbox(items);
    return items;
  }, [isRequestCurrent]);

  const markEventRead = useCallback(async (inboxId) => {
    const requestScope = authEpochRef.current.capture(activeUserIdRef.current);
    if (!requestScope.ownerId) return;
    await userApi.markEventRead(inboxId);
    if (isRequestCurrent(requestScope)) {
      setEventInbox(items => items.filter(item => item.id !== inboxId));
    }
  }, [isRequestCurrent]);

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
