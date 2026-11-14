import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';

const TABS = [['documents', '文件'], ['users', '使用者'], ['eval', '成效'], ['audit', '稽核']];
const LEVEL = { public: '公開', dept: '部門', restricted: '限閱' };
const STATUS = { pending: '處理中', ready: '可用', failed: '失敗', deprecated: '已作廢' };
const ROLE = { employee: '員工', manager: '主管', it_admin: 'IT 管理員' };
const MODE = { vector: '向量', hybrid: '混合', keyword: '關鍵字' };
const KIND = { answer: '應回答', refuse: '應拒答', permission: '越權' };

const pct = (v) => `${Math.round(v * 100)}%`;
const time = (v) => (v ? new Date(v).toLocaleString('zh-TW', { hour12: false }) : '—');

export default function AdminPage({ onBack }) {
  const [tab, setTab] = useState('documents');
  const [departments, setDepartments] = useState([]);
  useEffect(() => { api.departments().then(setDepartments).catch(() => {}); }, []);

  return (
    <div className="admin">
      <header className="topbar">
        <button className="ghost" onClick={onBack}>← 對話</button>
        <h1>IT 管理</h1>
      </header>
      <nav className="admin-tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? 'tab active' : 'tab'}
            onClick={() => setTab(key)}>{label}</button>
        ))}
      </nav>
      <div className="admin-body">
        {tab === 'documents' && <DocumentsTab departments={departments} />}
        {tab === 'users' && <UsersTab departments={departments} />}
        {tab === 'eval' && <EvalTab />}
        {tab === 'audit' && <AuditTab />}
      </div>
    </div>
  );
}

// ---------------- 文件 ----------------
function DocumentsTab({ departments }) {
  const [page, setPage] = useState({ items: [], total: 0 });
  const [error, setError] = useState('');
  const deptName = (id) => departments.find((d) => d.id === id)?.name ?? id;

  const load = useCallback(() => api.listDocuments().then(setPage).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  // 有處理中的文件就每 3 秒更新一次狀態
  useEffect(() => {
    if (!page.items.some((d) => d.status === 'pending')) return undefined;
    const timer = setTimeout(load, 3000);
    return () => clearTimeout(timer);
  }, [page, load]);

  async function act(fn) {
    setError('');
    try { await fn(); await load(); } catch (e) { setError(e.message); }
  }

  return (
    <>
      <UploadForm departments={departments} onDone={load} onError={setError} />
      {error && <p className="error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>文件</th><th>版本</th><th>部門</th><th>等級</th><th>狀態</th><th>操作</th></tr></thead>
          <tbody>
            {page.items.map((d) => (
              <tr key={d.id}>
                <td>{d.title}<div className="sub">{d.chunk_mode === 'window' ? '滑動視窗' : '依條切塊'}</div></td>
                <td>{d.version}</td>
                <td>{deptName(d.dept_id)}</td>
                <td>
                  <select value={d.level} disabled={d.status === 'deprecated'} aria-label={`${d.title} 等級`}
                    onChange={(e) => act(() => api.patchDocument(d.id, { level: e.target.value }))}>
                    {Object.entries(LEVEL).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </td>
                <td><span className={`badge ${d.status}`}>{STATUS[d.status]}</span></td>
                <td className="actions">
                  {(d.status === 'ready' || d.status === 'failed') && (
                    <button onClick={() => act(() => api.reprocessDocument(d.id))}>重新處理</button>
                  )}
                  {(d.status === 'ready' || d.status === 'failed') && (
                    <button onClick={() => window.confirm(`作廢「${d.title} ${d.version}」？作廢後問答不會再引用，也不能重新處理。`)
                      && act(() => api.patchDocument(d.id, { status: 'deprecated' }))}>作廢</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">共 {page.total} 份</p>
    </>
  );
}

function UploadForm({ departments, onDone, onError }) {
  const formRef = useRef(null);
  const [file, setFile] = useState(null);
  const [title, setTitle] = useState('');
  const [dept, setDept] = useState('');
  const [level, setLevel] = useState('dept');
  const [version, setVersion] = useState('v1');
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!dept && departments[0]) setDept(departments[0].code); }, [departments, dept]);

  async function submit(e) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    onError('');
    try {
      await api.uploadDocument({ file, title: title.trim() || file.name.replace(/\.[^.]+$/, ''), dept_code: dept, level, version });
      formRef.current?.reset();
      setFile(null);
      setTitle('');
      await onDone();
    } catch (err) {
      onError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form ref={formRef} className="upload" onSubmit={submit}>
      <label>檔案（.txt .md .pdf）
        <input type="file" accept=".txt,.md,.pdf" onChange={(e) => setFile(e.target.files[0] ?? null)} required />
      </label>
      <label>名稱
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="預設用檔名" maxLength={255} />
      </label>
      <label>部門
        <select value={dept} onChange={(e) => setDept(e.target.value)}>
          {departments.map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
        </select>
      </label>
      <label>等級
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          {Object.entries(LEVEL).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
      </label>
      <label>版本
        <input value={version} onChange={(e) => setVersion(e.target.value)} maxLength={30} required />
      </label>
      <button className="primary" disabled={busy || !file}>{busy ? '上傳中…' : '上傳'}</button>
    </form>
  );
}

// ---------------- 使用者 ----------------
function UsersTab({ departments }) {
  const [page, setPage] = useState({ items: [], total: 0 });
  const [error, setError] = useState('');
  const load = useCallback(() => api.listUsers().then(setPage).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function patch(id, body) {
    setError('');
    try { await api.patchUser(id, body); await load(); } catch (e) { setError(e.message); }
  }

  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>帳號</th><th>部門</th><th>角色</th><th>狀態</th><th>最後活動</th></tr></thead>
          <tbody>
            {page.items.map((u) => (
              <tr key={u.id}>
                <td>{u.email}</td>
                <td>
                  <select value={u.department.code} aria-label={`${u.email} 部門`}
                    onChange={(e) => patch(u.id, { dept_code: e.target.value })}>
                    {departments.map((d) => <option key={d.code} value={d.code}>{d.name}</option>)}
                  </select>
                </td>
                <td>
                  <select value={u.role} aria-label={`${u.email} 角色`} onChange={(e) => patch(u.id, { role: e.target.value })}>
                    {Object.entries(ROLE).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                  </select>
                </td>
                <td>
                  <button className={u.is_active ? 'toggle on' : 'toggle'} onClick={() => patch(u.id, { is_active: !u.is_active })}>
                    {u.is_active ? '啟用中' : '已停用'}
                  </button>
                </td>
                <td className="nowrap">{time(u.last_active_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">共 {page.total} 人。停用後該帳號的登入立即失效。</p>
    </>
  );
}

// ---------------- 成效 ----------------
function EvalTab() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [results, setResults] = useState([]);
  const [mode, setMode] = useState('');
  const [failedOnly, setFailedOnly] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(() => api.listEvalRuns()
    .then((p) => {
      setRuns(p.items);
      setSelected((current) => current ?? p.items.find((r) => r.finished_at)?.id ?? null);
    })
    .catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!runs.some((r) => !r.finished_at)) return undefined;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [runs, load]);

  const run = runs.find((r) => r.id === selected);
  useEffect(() => {
    if (!run?.finished_at) { setResults([]); return; }
    api.listEvalResults(run.id, failedOnly).then(setResults).catch((e) => setError(e.message));
  }, [run?.id, run?.finished_at, failedOnly]);

  async function start() {
    setError('');
    try {
      const created = await api.createEvalRun(mode ? { mode } : {});
      setSelected(created.id);
      await load();
    } catch (e) {
      setError(e.message);
    }
  }

  const m = run?.metrics;
  return (
    <>
      <div className="toolbar">
        <select value={mode} onChange={(e) => setMode(e.target.value)} aria-label="檢索方式">
          <option value="">目前設定</option>
          {Object.entries(MODE).map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        <button className="primary" onClick={start}>執行評測</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      {run && !run.finished_at && <p className="muted">批次 #{run.id} 執行中…</p>}
      {m && (
        <div className="cards">
          <Metric label="Hit@1" value={pct(m.hit_at_1)} />
          <Metric label="Hit@3" value={pct(m.hit_at_3)} />
          <Metric label="MRR" value={m.mrr.toFixed(2)} />
          <Metric label="拒答正確率" value={pct(m.refuse_accuracy)} />
          <Metric label="誤拒率" value={pct(m.false_refusal_rate)} />
          <Metric label="越權測試" value={pct(m.permission_pass)} note={`外洩 ${m.leaks} 筆`} />
          <Metric label="p95 耗時" value={`${m.p95_ms} ms`} note={`p50 ${m.p50_ms} ms`} />
        </div>
      )}

      <h2 className="section">評測紀錄</h2>
      <div className="table-wrap">
        <table className="data clickable">
          <thead><tr><th>#</th><th>時間</th><th>方式</th><th>門檻</th><th>Hit@1</th><th>Hit@3</th><th>拒答</th><th>越權</th><th>p95</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className={r.id === selected ? 'selected' : ''} onClick={() => setSelected(r.id)}>
                <td>{r.id}</td>
                <td className="nowrap">{time(r.started_at)}</td>
                <td>{MODE[r.config?.mode] ?? r.config?.mode}{r.config?.mode === 'hybrid' ? ` ${r.config.keyword_weight}` : ''}</td>
                <td>{r.config?.threshold}</td>
                {r.metrics ? (
                  <>
                    <td>{pct(r.metrics.hit_at_1)}</td><td>{pct(r.metrics.hit_at_3)}</td>
                    <td>{pct(r.metrics.refuse_accuracy)}</td><td>{pct(r.metrics.permission_pass)}</td>
                    <td>{r.metrics.p95_ms} ms</td>
                  </>
                ) : <td colSpan={5}>執行中…</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {run?.finished_at && (
        <>
          <h2 className="section">
            {failedOnly ? '失敗案例' : '全部題目'}（批次 #{run.id}）
            <label className="inline"><input type="checkbox" checked={failedOnly} onChange={(e) => setFailedOnly(e.target.checked)} /> 只看失敗</label>
          </h2>
          {results.length === 0 ? <p className="muted">沒有失敗案例。</p> : (
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>題目</th><th>類型</th><th>身分</th><th>應為</th><th>實際第一名</th><th>名次</th><th>拒答</th></tr></thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.case_id}>
                      <td>{r.question}</td>
                      <td>{KIND[r.kind]}</td>
                      <td className="nowrap">{r.as_dept}・{ROLE[r.as_role] ?? r.as_role}</td>
                      <td>{r.expected ?? '—'}</td>
                      <td>{r.top_hit ?? '—'}</td>
                      <td>{r.hit_rank ?? '—'}</td>
                      <td>{r.refused ? '是' : '否'}{r.leaked ? '・外洩' : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </>
  );
}

function Metric({ label, value, note }) {
  return (
    <div className="card">
      <div className="card-label">{label}</div>
      <div className="card-value">{value}</div>
      {note && <div className="card-note">{note}</div>}
    </div>
  );
}

// ---------------- 稽核 ----------------
function AuditTab() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState('');

  const loadMore = useCallback((offset) => api.listAuditLogs(offset)
    .then((p) => { setItems((list) => (offset === 0 ? p.items : [...list, ...p.items])); setTotal(p.total); })
    .catch((e) => setError(e.message)), []);
  useEffect(() => { loadMore(0); }, [loadMore]);

  return (
    <>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>時間</th><th>使用者</th><th>動作</th><th>對象</th><th>IP</th></tr></thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td className="nowrap">{time(a.created_at)}</td>
                <td>{a.user_id ?? '系統'}</td>
                <td>{a.action}</td>
                <td>{a.target ?? '—'}</td>
                <td>{a.ip ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="toolbar">
        <span className="muted">顯示 {items.length} / {total} 筆。紀錄只增不改，不含提問與文件內容。</span>
        {items.length < total && <button onClick={() => loadMore(items.length)}>載入更多</button>}
      </div>
    </>
  );
}
