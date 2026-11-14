import { useEffect, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';

export default function AuthPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState('login'); // login | register
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [deptCode, setDeptCode] = useState('');
  const [departments, setDepartments] = useState([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (mode !== 'register' || departments.length) return;
    api.departments()
      .then((list) => { setDepartments(list); setDeptCode(list[0]?.code ?? ''); })
      .catch((e) => setError(`無法載入部門：${e.message}`));
  }, [mode, departments.length]);

  async function submit(e) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (mode === 'login') await login(email, password);
      else await register(email, password, deptCode);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <form className="auth-card" onSubmit={submit}>
        <h1>內部知識助理</h1>
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={mode === 'login'}
            className={mode === 'login' ? 'tab active' : 'tab'} onClick={() => setMode('login')}>登入</button>
          <button type="button" role="tab" aria-selected={mode === 'register'}
            className={mode === 'register' ? 'tab active' : 'tab'} onClick={() => setMode('register')}>註冊</button>
        </div>

        <label>Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            autoComplete="username" required />
        </label>
        <label>密碼
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required />
        </label>
        {mode === 'register' && (
          <label>部門
            <select value={deptCode} onChange={(e) => setDeptCode(e.target.value)} required>
              {departments.map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
            </select>
          </label>
        )}

        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" disabled={busy}>
          {busy ? '處理中…' : mode === 'login' ? '登入' : '建立帳號'}
        </button>
      </form>
    </main>
  );
}
