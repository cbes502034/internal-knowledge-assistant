import { useState } from 'react';
import { useAuth } from './auth/AuthContext.jsx';
import { useIdleLogout } from './hooks/useIdleLogout.js';
import AdminPage from './pages/AdminPage.jsx';
import AuthPage from './pages/AuthPage.jsx';
import ChatPage from './pages/ChatPage.jsx';

const IDLE_MINUTES = 15;

// 單頁應用：沒登入顯示登入／註冊；登入後是對話主畫面，IT 管理員可切換到管理面板
export default function App() {
  const { user, booting, logout } = useAuth();
  const [view, setView] = useState('chat');
  useIdleLogout(IDLE_MINUTES, logout, Boolean(user));

  if (booting) return <div className="boot">載入中…</div>;
  if (!user) return <AuthPage />;
  if (view === 'admin' && user.role === 'it_admin') return <AdminPage onBack={() => setView('chat')} />;
  return <ChatPage onOpenAdmin={() => setView('admin')} />;
}
