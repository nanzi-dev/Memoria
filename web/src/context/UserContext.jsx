import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { userApi } from '../api/memoria';

const UserContext = createContext(null);
const CLOCK_REFRESH_MS = 60_000;
const INBOX_REFRESH_MS = 20_000;

export function useUser() {
  return useContext(UserContext);
}

export function UserProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem('memoria-token'));
  const [loading, setLoading] = useState(true);
  const [worldClock, setWorldClock] = useState(null);
  const [eventInbox, setEventInbox] = useState([]);
  const timezoneReportedForRef = useRef(null);

  const applyClock = useCallback((clock) => {
    if (!clock) return;
    setWorldClock(clock);
    setUser(current => current ? { ...current, ...clock } : current);
  }, []);

  const initializeClock = useCallback(async (baseUser) => {
    if (!baseUser) return;
    applyClock(baseUser);
    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const reportKey = `${baseUser.user_id}:${browserTimezone}`;
    if (
      browserTimezone
      && browserTimezone !== baseUser.timezone
      && timezoneReportedForRef.current !== reportKey
    ) {
      timezoneReportedForRef.current = reportKey;
      try {
        applyClock(await userApi.updateWorldClock({ timezone: browserTimezone }));
      } catch {
        timezoneReportedForRef.current = null;
      }
    }
  }, [applyClock]);

  useEffect(() => {
    let cancelled = false;
    userApi.getMe()
      .then(u => {
        if (cancelled) return;
        setUser(u);
        initializeClock(u);
      })
      .catch(() => {
        if (cancelled) return;
        localStorage.removeItem('memoria-token');
        setToken(null);
        setUser(null);
        setWorldClock(null);
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
      userApi.getWorldClock()
        .then(clock => {
          if (!cancelled) initializeClock({ ...clock, user_id: user.user_id });
        })
        .catch(() => {});
    };
    const refreshInbox = () => {
      userApi.getEventInbox(true, 50)
        .then(items => { if (!cancelled) setEventInbox(items); })
        .catch(() => {});
    };

    refreshInbox();
    const clockTimer = setInterval(refreshClockSnapshot, CLOCK_REFRESH_MS);
    const inboxTimer = setInterval(refreshInbox, INBOX_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(clockTimer);
      clearInterval(inboxTimer);
    };
  }, [user?.user_id, initializeClock]);

  const login = useCallback(async (username, password) => {
    const res = await userApi.login(username, password);
    localStorage.setItem('memoria-token', res.token);
    setToken(res.token);
    setUser(res.user);
    await initializeClock(res.user);
    return res.user;
  }, [initializeClock]);

  const register = useCallback(async (username, password, gender) => {
    const res = await userApi.register(username, password, gender);
    localStorage.setItem('memoria-token', res.token);
    setToken(res.token);
    setUser(res.user);
    await initializeClock(res.user);
    return res.user;
  }, [initializeClock]);

  const logout = useCallback(() => {
    localStorage.removeItem('memoria-token');
    setToken(null);
    setUser(null);
    setWorldClock(null);
    setEventInbox([]);
    timezoneReportedForRef.current = null;
    userApi.logout().catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    try {
      const u = await userApi.getMe();
      setUser(u);
      await initializeClock(u);
    } catch {}
  }, [initializeClock]);

  const updateWorldClock = useCallback(async (updates) => {
    const clock = await userApi.updateWorldClock(updates);
    applyClock(clock);
    return clock;
  }, [applyClock]);

  const syncWorldClock = useCallback(async () => {
    const clock = await userApi.syncWorldClock();
    applyClock(clock);
    return clock;
  }, [applyClock]);

  const refreshEventInbox = useCallback(async () => {
    const items = await userApi.getEventInbox(true, 50);
    setEventInbox(items);
    return items;
  }, []);

  const markEventRead = useCallback(async (inboxId) => {
    await userApi.markEventRead(inboxId);
    setEventInbox(items => items.filter(item => item.id !== inboxId));
  }, []);

  return (
    <UserContext.Provider value={{
      user,
      token,
      loading,
      worldClock,
      eventInbox,
      login,
      register,
      logout,
      refresh,
      updateWorldClock,
      syncWorldClock,
      refreshEventInbox,
      markEventRead,
    }}>
      {children}
    </UserContext.Provider>
  );
}
