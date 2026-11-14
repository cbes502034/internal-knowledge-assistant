// 後端 API 的唯一入口。路徑與格式對應 backend/app/routers 與企劃書第 7 章。
// 展示模式：網址加上 ?demo 可在沒有後端時預覽對話畫面（只在開發模式有效）。
import { mockApi } from './mock.js';

const BASE = '/api/v1';
export const DEMO = import.meta.env.DEV && new URLSearchParams(location.search).has('demo');

let accessToken = null; // access JWT 只放記憶體；refresh token 在 httpOnly cookie，JavaScript 讀不到
export const setAccessToken = (t) => { accessToken = t; };

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request(method, path, { json, form, multipart, auth = true, retry = true } = {}) {
  const headers = {};
  let body;
  if (json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(json); }
  if (form !== undefined) { body = new URLSearchParams(form); }
  if (multipart !== undefined) { body = multipart; } // 瀏覽器會自己加上 multipart 的 Content-Type 與 boundary
  if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`;

  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body, credentials: 'include' });
  } catch {
    throw new ApiError(0, 'network_error', '無法連線到伺服器');
  }

  // access JWT 過期：用 refresh cookie 換一個新的，再重送一次
  if (res.status === 401 && auth && retry && accessToken) {
    try {
      await api.refresh();
    } catch {
      setAccessToken(null);
      window.dispatchEvent(new Event('auth:expired'));
      throw new ApiError(401, 'unauthorized', '登入已逾時，請重新登入');
    }
    return request(method, path, { json, form, multipart, auth, retry: false });
  }

  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, data?.code ?? `http_${res.status}`, data?.message ?? '發生錯誤');
  }
  return data;
}

// 同時有好幾個請求遇到 401 時，只送一次 refresh：
// 後端每個 refresh token 只能用一次（輪替），重複送出會被當成權杖外洩而撤銷全部登入。
let refreshing = null;
function refreshOnce() {
  refreshing ??= request('POST', '/auth/token', { form: { grant_type: 'refresh_token' }, auth: false })
    .then((t) => setAccessToken(t.access_token))
    .finally(() => { refreshing = null; });
  return refreshing;
}

const query = (params) => new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== '')).toString();

const realApi = {
  async login(email, password) {
    const t = await request('POST', '/auth/token',
      { form: { grant_type: 'password', username: email, password }, auth: false });
    setAccessToken(t.access_token);
  },
  refresh: refreshOnce,
  async logout() {
    try { await request('POST', '/auth/revoke', { retry: false }); } finally { setAccessToken(null); }
  },
  register: (email, password, deptCode) =>
    request('POST', '/users', { json: { email, password, dept_code: deptCode }, auth: false }),
  me: () => request('GET', '/me'),
  departments: () => request('GET', '/departments', { auth: false }),

  listConversations: () => request('GET', '/conversations?limit=50'),
  createConversation: (title) => request('POST', '/conversations', { json: { title } }),
  deleteConversation: (id) => request('DELETE', `/conversations/${id}`),
  listMessages: (id) => request('GET', `/conversations/${id}/messages`),
  ask: (id, content) => request('POST', `/conversations/${id}/messages`, { json: { content } }),
  setFeedback: (messageId, value) => request('PUT', `/messages/${messageId}/feedback`, { json: { value } }),

  // ---- IT 管理 ----
  listDocuments: () => request('GET', '/documents?limit=100'),
  uploadDocument: ({ file, ...fields }) => {
    const data = new FormData();
    data.append('file', file);
    Object.entries(fields).forEach(([k, v]) => { if (v != null && v !== '') data.append(k, v); });
    return request('POST', '/documents', { multipart: data });
  },
  patchDocument: (id, body) => request('PATCH', `/documents/${id}`, { json: body }),
  reprocessDocument: (id) => request('POST', `/documents/${id}/processing-jobs`),
  listUsers: () => request('GET', '/users?limit=100'),
  patchUser: (id, body) => request('PATCH', `/users/${id}`, { json: body }),
  listEvalRuns: () => request('GET', '/eval-runs?limit=50'),
  createEvalRun: (body) => request('POST', '/eval-runs', { json: body }),
  listEvalResults: (id, failedOnly) => request('GET', `/eval-runs/${id}/results?${query({ failed_only: failedOnly })}`),
  listAuditLogs: (offset = 0) => request('GET', `/audit-logs?${query({ limit: 50, offset })}`),
};

export const api = DEMO ? mockApi : realApi;
