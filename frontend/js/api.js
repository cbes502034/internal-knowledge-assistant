export class ApiClient {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.accessToken = null;
    this.refreshing = null;
  }

  setToken(token) { this.accessToken = token; }
  clearToken() { this.accessToken = null; }

  async request(path, options = {}, retry = true) {
    const headers = new Headers(options.headers || {});
    if (this.accessToken) headers.set("Authorization", `Bearer ${this.accessToken}`);
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options, headers, credentials: "include"
    });
    if (response.status === 401 && retry && path !== "/auth/token" && path !== "/auth/revoke") {
      const refreshed = await this.refresh();
      if (refreshed) return this.request(path, options, false);
    }
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch {}
      const error = new Error(payload.message || `API request failed (${response.status})`);
      error.status = response.status;
      error.code = payload.code || "request_failed";
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async login(email, password) {
    const body = new URLSearchParams({grant_type:"password", username:email, password});
    const data = await this.request("/auth/token", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body}, false);
    this.setToken(data.access_token);
    return data;
  }

  async register(email, password, dept_code) {
    return this.request("/users", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email,password,dept_code})}, false);
  }

  async refresh() {
    if (this.refreshing) return this.refreshing;
    this.refreshing = (async () => {
      try {
        const body = new URLSearchParams({grant_type:"refresh_token"});
        const data = await this.request("/auth/token", {method:"POST", headers:{"Content-Type":"application/x-www-form-urlencoded"}, body}, false);
        this.setToken(data.access_token);
        return true;
      } catch { this.clearToken(); return false; }
      finally { this.refreshing = null; }
    })();
    return this.refreshing;
  }

  async logout() {
    try { await this.request("/auth/revoke", {method:"POST"}, false); }
    finally { this.clearToken(); }
  }

  get(path) { return this.request(path); }
  post(path, body) { return this.request(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); }
  patch(path, body) { return this.request(path,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); }
  put(path, body) { return this.request(path,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); }
  delete(path) { return this.request(path,{method:"DELETE"}); }
}
