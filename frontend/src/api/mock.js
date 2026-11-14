// 展示模式用的假資料（網址加 ?demo）。內容為模擬資料，只用來預覽畫面。
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let seq = 100;
const now = () => new Date().toISOString();

const conversations = [{ id: 'demo-1', title: '廢溶劑處理期限', created_at: now() }];
const messages = {
  'demo-1': [
    { id: 1, role: 'user', content: '廢溶劑放多久要處理？', refused: false, citations: [], feedback: null, latency_ms: null, created_at: now() },
    {
      id: 2, role: 'assistant', refused: false, feedback: null, latency_ms: 3180, created_at: now(),
      content: '廢溶劑暫存超過 90 天，須聯絡合格清運廠商處理。[1]',
      citations: [
        { rank: 1, doc_title: '廢棄物處理SOP（模擬）', version: 'v2', article_no: 2, score: 0.82 },
        { rank: 2, doc_title: '廢棄物處理SOP（模擬）', version: 'v2', article_no: 3, score: 0.61 },
      ],
    },
  ],
};

export const mockApi = {
  login: async () => {},
  refresh: async () => {},
  logout: async () => {},
  register: async () => ({}),
  me: async () => ({ id: 1, email: 'demo@example.com', role: 'employee', is_active: true,
    department: { id: 4, code: 'ops', name: '運營單位' } }),
  departments: async () => [
    { id: 1, code: 'sales', name: '業務體系' }, { id: 2, code: 'product', name: '產品發展體系' },
    { id: 3, code: 'rd', name: '研發單位' }, { id: 4, code: 'ops', name: '運營單位' },
    { id: 5, code: 'finance', name: '財務單位' }, { id: 6, code: 'gm_office', name: '總經理室' },
  ],
  listConversations: async () => ({ items: conversations, total: conversations.length, limit: 50, offset: 0 }),
  createConversation: async (title) => {
    const c = { id: `demo-${++seq}`, title: title || '新對話', created_at: now() };
    conversations.unshift(c);
    messages[c.id] = [];
    return c;
  },
  deleteConversation: async (id) => {
    conversations.splice(conversations.findIndex((c) => c.id === id), 1);
  },
  listMessages: async (id) => messages[id] ?? [],
  ask: async (id, content) => {
    await wait(900);
    messages[id].push({ id: ++seq, role: 'user', content, refused: false, citations: [], feedback: null, latency_ms: null, created_at: now() });
    const reply = { id: ++seq, role: 'assistant', content: '找不到相關規定。', refused: true, citations: [], feedback: null, latency_ms: 900, created_at: now() };
    messages[id].push(reply);
    return reply;
  },
  setFeedback: async (messageId, value) => {
    const m = Object.values(messages).flat().find((x) => x.id === messageId);
    m.feedback = value;
    return m;
  },
};
