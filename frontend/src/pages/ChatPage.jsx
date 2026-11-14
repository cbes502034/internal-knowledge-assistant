import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useIdleLogout } from '../hooks/useIdleLogout.js';

const IDLE_MINUTES = 15;

export default function ChatPage() {
  const { user, logout } = useAuth();
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const bottomRef = useRef(null);

  useIdleLogout(IDLE_MINUTES, logout);

  useEffect(() => {
    api.listConversations()
      .then((page) => { setConversations(page.items); setActiveId(page.items[0]?.id ?? null); })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!activeId) { setMessages([]); return; }
    api.listMessages(activeId).then(setMessages).catch((e) => setError(e.message));
  }, [activeId]);

  useEffect(() => { bottomRef.current?.scrollIntoView({ block: 'end' }); }, [messages, pending]);

  const newConversation = useCallback(async () => {
    setError('');
    try {
      const c = await api.createConversation(null);
      setConversations((list) => [c, ...list]);
      setActiveId(c.id);
      setDrawerOpen(false);
      return c.id;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }, []);

  async function send(e) {
    e.preventDefault();
    const content = draft.trim();
    if (!content || pending) return;
    setError('');
    setPending(true);
    try {
      const id = activeId ?? (await newConversation());
      if (!id) return;
      setDraft('');
      setMessages((list) => [...list, { id: `tmp-${Date.now()}`, role: 'user', content, citations: [] }]);
      const reply = await api.ask(id, content);
      setMessages((list) => [...list, reply]);
    } catch (err) {
      setError(err.message);
    } finally {
      setPending(false);
    }
  }

  async function feedback(message, value) {
    try {
      const updated = await api.setFeedback(message.id, message.feedback === value ? null : value);
      setMessages((list) => list.map((m) => (m.id === updated.id ? updated : m)));
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div className="chat">
      <aside className={drawerOpen ? 'sidebar open' : 'sidebar'}>
        <button className="primary" onClick={newConversation}>新對話</button>
        <nav className="conv-list">
          {conversations.map((c) => (
            <button key={c.id} className={c.id === activeId ? 'conv active' : 'conv'}
              onClick={() => { setActiveId(c.id); setDrawerOpen(false); }}>{c.title}</button>
          ))}
        </nav>
        <div className="me">
          <div className="me-email">{user.email}</div>
          <div className="me-dept">{user.department.name}</div>
          <button className="ghost" onClick={logout}>登出</button>
        </div>
      </aside>
      {drawerOpen && <div className="scrim" onClick={() => setDrawerOpen(false)} />}

      <section className="main">
        <header className="topbar">
          <button className="ghost menu" aria-label="對話列表" onClick={() => setDrawerOpen(true)}>☰</button>
          <h1>內部知識助理</h1>
        </header>

        <div className="messages">
          {messages.length === 0 && !pending && <p className="empty">輸入問題開始查詢法規與 SOP</p>}
          {messages.map((m) => <MessageBubble key={m.id} message={m} onFeedback={feedback} />)}
          {pending && <div className="bubble assistant"><p className="thinking">查詢中…</p></div>}
          <div ref={bottomRef} />
        </div>

        {error && <p className="error bar" role="alert">{error}</p>}
        <form className="composer" onSubmit={send}>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="輸入問題"
            maxLength={2000} aria-label="問題" />
          <button className="primary" disabled={pending || !draft.trim()}>送出</button>
        </form>
      </section>
    </div>
  );
}

function MessageBubble({ message, onFeedback }) {
  const isAssistant = message.role === 'assistant';
  return (
    <div className={`bubble ${message.role}${message.refused ? ' refused' : ''}`}>
      <p>{message.content}</p>
      {isAssistant && message.citations?.length > 0 && (
        <ul className="citations">
          {message.citations.map((c) => (
            <li key={c.rank}>
              <span className="cite-rank">[{c.rank}]</span>
              <span className="cite-title">{c.doc_title} 第{c.article_no}條</span>
              <span className="cite-meta">{c.version}　相似度 {c.score?.toFixed(2)}</span>
            </li>
          ))}
        </ul>
      )}
      {isAssistant && typeof message.id === 'number' && (
        <div className="bubble-foot">
          {message.latency_ms != null && <span>{(message.latency_ms / 1000).toFixed(1)} 秒</span>}
          <button className={message.feedback === 'up' ? 'fb on' : 'fb'} onClick={() => onFeedback(message, 'up')}>有用</button>
          <button className={message.feedback === 'down' ? 'fb on' : 'fb'} onClick={() => onFeedback(message, 'down')}>沒用</button>
        </div>
      )}
    </div>
  );
}
