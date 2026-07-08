import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { userApi } from '../api/memoria';

const UserContext = createContext(null);

export function useUser() {
  return useContext(UserContext);
}

export function UserProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem('memoria-token'));
  const [loading, setLoading] = useState(!!token);

  useEffect(() => {
    if (!token) { setLoading(false); return; }
    userApi.getMe().then(u => { setUser(u); setLoading(false); }).catch(() => {
      localStorage.removeItem('memoria-token');
      setToken(null);
      setUser(null);
      setLoading(false);
    });
  }, [token]);

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
  }, []);

  const refresh = useCallback(async () => {
    if (!token) return;
    try {
      const u = await userApi.getMe();
      setUser(u);
    } catch {}
  }, [token]);

  return (
    <UserContext.Provider value={{ user, token, loading, login, register, logout, refresh }}>
      {children}
    </UserContext.Provider>
  );
}
