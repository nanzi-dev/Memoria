import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { userApi } from '../api/memoria';

const UserContext = createContext(null);

export function useUser() {
  return useContext(UserContext);
}

export function UserProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem('memoria-token'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    userApi.getMe()
      .then(u => {
        if (cancelled) return;
        setUser(u);
      })
      .catch(() => {
        if (cancelled) return;
        localStorage.removeItem('memoria-token');
        setToken(null);
        setUser(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, []);

  const login = useCallback(async (username, password) => {
    const res = await userApi.login(username, password);
    localStorage.setItem('memoria-token', res.token);
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const register = useCallback(async (username, password, gender) => {
    const res = await userApi.register(username, password, gender);
    localStorage.setItem('memoria-token', res.token);
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem('memoria-token');
    setToken(null);
    setUser(null);
    userApi.logout().catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    try {
      const u = await userApi.getMe();
      setUser(u);
    } catch {}
  }, []);

  return (
    <UserContext.Provider value={{ user, token, loading, login, register, logout, refresh }}>
      {children}
    </UserContext.Provider>
  );
}
