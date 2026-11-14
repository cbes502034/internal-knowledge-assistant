import { useAuth } from './auth/AuthContext.jsx';
import AuthPage from './pages/AuthPage.jsx';
import ChatPage from './pages/ChatPage.jsx';

// 單頁應用：沒登入顯示登入／註冊，登入後顯示對話主畫面
export default function App() {
  const { user, booting } = useAuth();
  if (booting) return <div className="boot">載入中…</div>;
  return user ? <ChatPage /> : <AuthPage />;
}
