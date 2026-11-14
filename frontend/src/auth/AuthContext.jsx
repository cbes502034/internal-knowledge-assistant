import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { api, DEMO } from '../api/client.js';

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(true);

  // 重新整理頁面後 access JWT 不見了（只存在記憶體），用 refresh cookie 換回來
  useEffect(() => {
    (async () => {
      try {
        if (!DEMO) await api.refresh();
        setUser(await api.me());
      } catch {
        setUser(null);
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  // client.js 在 refresh 失敗時發出這個事件
  useEffect(() => {
    const onExpired = () => setUser(null);
    window.addEventListener('auth:expired', onExpired);
    return () => window.removeEventListener('auth:expired', onExpired);
  }, []);

  const login = useCallback(async (email, password) => {
    await api.login(email, password);
    setUser(await api.me());
  }, []);

  const register = useCallback(async (email, password, deptCode) => {
    await api.register(email, password, deptCode);
    await api.login(email, password);
    setUser(await api.me());
  }, []);

  const logout = useCallback(async () => {
    try { await api.logout(); } finally { setUser(null); }
  }, []);

  return (
    <AuthContext.Provider value={{ user, booting, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
