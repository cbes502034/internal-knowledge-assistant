import { ApiClient } from "./api.js";

const API_BASE_URL = "http://127.0.0.1:7999/api/v1";
const DEMO_MODE = new URLSearchParams(location.search).has("demo");
const IDLE_LIMIT = 15 * 60 * 1000;
const api = new ApiClient(API_BASE_URL);

const $ = (selector) => document.querySelector(selector);
const state = { user:null, departments:[], conversations:[], conversationId:null, messages:[], authMode:"login", adminTab:"documents", idleTimer:null, busy:false };

const demoData = {
  departments:[
    {id:1,code:"sales",name:"業務"},{id:2,code:"product",name:"產品發展"},{id:3,code:"rd",name:"研發"},
    {id:4,code:"ops",name:"運營"},{id:5,code:"finance",name:"財務"},{id:6,code:"gm_office",name:"總經理室"}
  ],
  conversations:[
    {id:"demo-1",title:"廢溶劑暫存期限與處理流程",created_at:new Date().toISOString()},
    {id:"demo-2",title:"文件版本控管原則",created_at:new Date(Date.now()-86400000).toISOString()},
    {id:"demo-3",title:"新產品開發流程",created_at:new Date(Date.now()-172800000).toISOString()}
  ],
  docs:[
    {id:12,title:"廢棄物處理 SOP",version:"v2.1",level:"dept",status:"ready",source:"環安衛 / SOP-OPS-004",effective_date:"2026-09-01",dept_id:4,created_at:"2026-09-01T09:00:00Z"},
    {id:11,title:"職業安全衛生管理辦法",version:"2025 修訂版",level:"public",status:"ready",source:"全國法規資料庫",effective_date:"2025-07-01",dept_id:4,created_at:"2025-07-01T09:00:00Z"},
    {id:10,title:"化學品管理作業程序",version:"v1.3",level:"restricted",status:"pending",source:"環安衛 / SOP-OPS-009",effective_date:"2026-11-01",dept_id:4,created_at:"2026-11-12T09:00:00Z"},
    {id:9,title:"供應商評鑑流程",version:"v1.0",level:"dept",status:"failed",source:"採購 / PROC-003",effective_date:"2026-04-01",dept_id:1,created_at:"2026-04-01T09:00:00Z"},
    {id:8,title:"舊版廠區安全巡檢表",version:"v1.0",level:"public",status:"deprecated",source:"環安衛 / FORM-011",effective_date:"2024-01-01",dept_id:4,created_at:"2024-01-01T09:00:00Z"}
  ],
  users:[
    {id:1,email:"it.admin@company.test",role:"it_admin",is_active:true,department:{name:"IT",code:"it"}},
    {id:2,email:"alex.chen@company.test",role:"employee",is_active:true,department:{name:"運營",code:"ops"}},
    {id:3,email:"jane.wu@company.test",role:"manager",is_active:true,department:{name:"研發",code:"rd"}},
    {id:4,email:"sam.lin@company.test",role:"employee",is_active:false,department:{name:"業務",code:"sales"}}
  ],
  audits:[
    {id:901,user_id:2,action:"login",target:"user:2",ip:"10.20.1.15",created_at:new Date(Date.now()-1800000).toISOString()},
    {id:900,user_id:1,action:"document.upload",target:"document:12",ip:"10.20.1.8",created_at:new Date(Date.now()-3600000).toISOString()},
    {id:899,user_id:2,action:"ask",target:"conversation:demo-1",ip:"10.20.1.15",created_at:new Date(Date.now()-7200000).toISOString()},
    {id:898,user_id:1,action:"user.update",target:"user:4",ip:"10.20.1.8",created_at:new Date(Date.now()-86400000).toISOString()}
  ],
  runs:[
    {id:21,embed_model:"BAAI/bge-m3",started_at:"2026-11-14T09:30:00Z",finished_at:"2026-11-14T09:31:20Z",metrics:{hit_at_1:.72,hit_at_3:.88,mrr:.81,refuse_accuracy:.92,p50_ms:4200,p95_ms:8900}},
    {id:20,embed_model:"intfloat/multilingual-e5-large",started_at:"2026-11-13T09:30:00Z",finished_at:"2026-11-13T09:31:26Z",metrics:{hit_at_1:.66,hit_at_3:.82,mrr:.75,refuse_accuracy:.9,p50_ms:4600,p95_ms:9600}}
  ]
};

function toast(message, type="") {
  const node=document.createElement("div"); node.className=`toast ${type}`; node.textContent=message;
  $("#toastRegion").append(node); setTimeout(()=>node.remove(),3800);
}
function showAuth(error="") {
  $("#workspace").hidden=true; $("#authView").hidden=false;
  $("#authError").hidden=!error; $("#authError").textContent=error;
}
function showWorkspace() { $("#authView").hidden=true; $("#workspace").hidden=false; }
function escapeHtml(value="") {
  return String(value).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function formatDate(value) { if(!value) return "—"; const d=new Date(value); return Number.isNaN(d.getTime())?"—":d.toLocaleString("zh-TW",{year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}); }
function roleLabel(role) { return ({employee:"員工",manager:"部門主管",it_admin:"IT 管理員"})[role]||role||"—"; }
function statusLabel(status) { return ({ready:"可用",pending:"處理中",failed:"失敗",deprecated:"已作廢",active:"啟用",inactive:"停用"})[status]||status; }
function levelLabel(level) { return ({public:"公開",dept:"部門",restricted:"限閱"})[level]||level; }
function statusClass(status) { return ["ready","pending","failed","deprecated","active","inactive","public","dept","restricted"].includes(status)?status:""; }
function badge(status,label=statusLabel(status)) { return `<span class="status ${statusClass(status)}">${escapeHtml(label)}</span>`; }
function markActivity() {
  if (!api.accessToken || !state.user) return;
  clearTimeout(state.idleTimer);
  state.idleTimer=setTimeout(async()=>{ await doLogout(true); },IDLE_LIMIT);
}
function startIdleTracking() {
  ["keydown","mousemove","mousedown","touchstart","scroll"].forEach(event=>document.addEventListener(event,markActivity,{passive:true}));
  markActivity();
}
async function doLogout(idle=false) {
  clearTimeout(state.idleTimer);
  if(!DEMO_MODE){ try{await api.logout();}catch{} }
  state.user=null; state.conversationId=null; state.messages=[];
  showAuth();
  if(idle) toast("已閒置 15 分鐘，系統已登出。");
}
function setUser(user) {
  state.user=user;
  $("#userName").textContent=user.email;
  $("#userRole").textContent=roleLabel(user.role).toUpperCase();
  $("#userAvatar").textContent=(user.email||"U").slice(0,1).toUpperCase();
  $("#scopeText").textContent=`${user.department?.name||"所屬部門"} · 依權限檢索`;
  const admin=user.role==="it_admin";
  $("#adminNav")?.remove();
  if(admin){
    const btn=document.createElement("button"); btn.id="adminNav"; btn.className="button button-new"; btn.style.marginTop="8px";
    btn.innerHTML="<span>▦</span> 管理中心"; btn.addEventListener("click",()=>showAdmin()); $("#sidebar").insertBefore(btn,$("#sidebar").children[2]);
  }
  startIdleTracking();
}
async function loadDepartments() {
  const departments=DEMO_MODE?demoData.departments:await api.get("/departments");
  state.departments=departments;
  $("#department").innerHTML=departments.map(d=>`<option value="${escapeHtml(d.code)}">${escapeHtml(d.name)}</option>`).join("");
}
function toggleAuthMode() {
  state.authMode=state.authMode==="login"?"register":"login";
  const register=state.authMode==="register";
  $("#authTitle").textContent=register?"建立工作空間帳號":"登入工作空間";
  $("#authSubtitle").textContent=register?"建立帳號後即可依所屬部門存取知識文件。":"使用公司帳號存取內部知識與作業規範。";
  $("#departmentField").hidden=!register;
  $("#authSubmit").textContent=register?"建立帳號":"登入";
  $("#authSwitchText").textContent=register?"已經有帳號？":"還沒有帳號？";
  $("#authSwitch").textContent=register?"返回登入":"建立帳號";
  $("#password").autocomplete=register?"new-password":"current-password";
  $("#authError").hidden=true;
}
async function handleAuth(event) {
  event.preventDefault();
  const email=$("#email").value.trim(), password=$("#password").value;
  $("#authSubmit").disabled=true; $("#authError").hidden=true;
  try {
    if(state.authMode==="register"){
      const dept_code=$("#department").value;
      if(DEMO_MODE) { toast("展示模式不會建立真實帳號。"); toggleAuthMode(); return; }
      await api.register(email,password,dept_code);
      toast("帳號建立成功，請登入。"); state.authMode="login"; toggleAuthMode();
      $("#email").value=email; $("#password").value=""; return;
    }
    if(DEMO_MODE){
      state.user={id:1,email,role:email.toLowerCase().includes("admin")?"it_admin":"employee",is_active:true,department:{name:"運營",code:"ops"}};
    } else {
      await api.login(email,password);
      state.user=await api.get("/me");
    }
    setUser(state.user); showWorkspace(); await loadConversations();
    $("#connectionLabel").textContent=DEMO_MODE?"展示資料":"API 已連線";
    $("#connectionDot").style.background="#2caa79";
    if(state.user.role==="it_admin") renderAdmin();
  } catch(error) { showAuth(error.message); }
  finally { $("#authSubmit").disabled=false; }
}
async function loadConversations() {
  const data=DEMO_MODE?{items:demoData.conversations}:await api.get("/conversations?limit=20&offset=0");
  state.conversations=data.items||[];
  renderConversationList();
  if(state.conversations.length) await selectConversation(state.conversations[0].id);
  else await createConversation();
}
function renderConversationList() {
  $("#conversationList").innerHTML=state.conversations.map(c=>`<button class="conversation-item ${c.id===state.conversationId?"active":""}" data-id="${escapeHtml(c.id)}" title="${escapeHtml(c.title)}">${escapeHtml(c.title||"新對話")}</button>`).join("");
  $("#conversationList").querySelectorAll("button").forEach(b=>b.addEventListener("click",()=>selectConversation(b.dataset.id)));
}
async function createConversation() {
  const c=DEMO_MODE?{id:`demo-${Date.now()}`,title:"新對話",created_at:new Date().toISOString()}:await api.post("/conversations",{title:null});
  state.conversations.unshift(c); await selectConversation(c.id); renderConversationList();
}
async function selectConversation(id) {
  showChat(); state.conversationId=id; renderConversationList();
  state.messages=DEMO_MODE?(id==="demo-1"?[{
    id:700,role:"user",content:"廢溶劑暫存期限與處理流程是什麼？",created_at:new Date(Date.now()-120000).toISOString()
  },{
    id:701,role:"assistant",content:"依展示資料，廢溶劑應依廢棄物分類與暫存規範管理，並在達到規定期限前聯繫合格清運業者。實際期限與處理方式應以現行核准文件及適用法規為準。",refused:false,latency_ms:3180,feedback:null,created_at:new Date(Date.now()-110000).toISOString(),
    citations:[{rank:1,doc_title:"廢棄物處理 SOP",version:"v2.1",article_no:"第2條",score:.82,preview:"本段為展示資料，並非正式法規原文。請以公司核准版本及主管機關公告為準。"},{rank:2,doc_title:"職業安全衛生管理辦法",version:"2025 修訂版",article_no:"第8條",score:.74,preview:"本段為展示資料，僅用於介面預覽。"}]
  }]:[]):[];
  if(!DEMO_MODE) state.messages=await api.get(`/conversations/${id}/messages`);
  renderMessages();
}
function renderMessages() {
  const root=$("#chatMessages");
  if(!state.messages.length){root.innerHTML=$("#welcomePanel")?.outerHTML||""; bindSuggestions(); return;}
  root.innerHTML=state.messages.map(m=>renderMessage(m)).join("");
  root.scrollTop=root.scrollHeight;
  bindMessageActions();
}
function renderMessage(m) {
  const user=m.role==="user";
  const citations=!user&&m.citations?.length?`<div class="citation-list">${m.citations.map((c,i)=>`<div class="citation-card">
    <div class="citation-head"><div><div class="citation-title">${escapeHtml(c.doc_title)}</div><div class="citation-meta">版本 ${escapeHtml(c.version||"未提供")} · ${escapeHtml(c.article_no||"未標條號")} · 排名 ${escapeHtml(c.rank)}</div></div><span class="citation-score">${c.score==null?"相似度未提供":`相似度 ${(c.score*100).toFixed(0)}%`}</span></div>
    <button class="citation-expand" data-citation="${m.id}-${i}">展開原文／出處資訊　＋</button>
    <div class="citation-detail" id="citation-${m.id}-${i}" hidden>${c.preview?escapeHtml(c.preview):(DEMO_MODE?"展示內容":"原文目前無法顯示（文件已作廢、已刪除，或你已沒有閱讀權限）。")}</div>
  </div>`).join("")}</div>`:"";
  const feedback=!user&&m.id?`<div class="message-actions"><span>${m.latency_ms!=null?`回應時間 ${(m.latency_ms/1000).toFixed(2)} 秒`:""}</span><span>這個回答有幫助嗎？</span><button class="feedback-button ${m.feedback==="up"?"selected":""}" data-feedback="up" data-id="${m.id}">有用</button><button class="feedback-button ${m.feedback==="down"?"selected":""}" data-feedback="down" data-id="${m.id}">沒用</button></div>`:"";
  return `<article class="message-row ${user?"user":"assistant"}"><div class="message-avatar">${user?"U":"K"}</div><div class="message-body"><div class="message-meta">${user?"你":"知識助理"} · ${formatDate(m.created_at)}</div><div class="message-bubble">${escapeHtml(m.content)}</div>${m.refused?'<div class="message-actions"><span class="message-status">未找到足夠依據</span></div>':""}${citations}${feedback}</div></article>`;
}
function bindMessageActions() {
  document.querySelectorAll(".citation-expand").forEach(b=>b.addEventListener("click",()=>{
    const panel=$(`#citation-${b.dataset.citation}`); panel.hidden=!panel.hidden; b.textContent=panel.hidden?"展開原文／出處資訊　＋":"收合出處資訊　−";
  }));
  document.querySelectorAll("[data-feedback]").forEach(b=>b.addEventListener("click",async()=>{
    const value=b.dataset.feedback, id=b.dataset.id;
    try{
      if(!DEMO_MODE) await api.put(`/messages/${id}/feedback`,{value});
      const m=state.messages.find(x=>String(x.id)===String(id)); if(m)m.feedback=m.feedback===value?null:value;
      renderMessages();
    }catch(e){toast(e.message,"error");}
  }));
}
function bindSuggestions() {
  document.querySelectorAll("[data-prompt]").forEach(b=>b.addEventListener("click",()=>{$("#chatInput").value=b.dataset.prompt;$("#chatInput").focus();}));
}
async function handleAsk(event) {
  event.preventDefault();
  const content=$("#chatInput").value.trim();
  if(!content||state.busy)return;
  if(!state.conversationId){await createConversation();}
  state.busy=true; $("#sendButton").disabled=true;
  state.messages.push({id:`local-${Date.now()}`,role:"user",content,created_at:new Date().toISOString()});
  $("#chatInput").value=""; renderMessages();
  const loading=document.createElement("div"); loading.className="typing"; loading.id="typing"; loading.textContent="正在檢索知識文件並整理回答…"; $("#chatMessages").append(loading);
  try{
    let answer;
    if(DEMO_MODE){
      await new Promise(r=>setTimeout(r,650));
      answer={id:Date.now(),role:"assistant",content:"這是展示模式的示意回答。正式模式會呼叫 FastAPI，依目前使用者的部門、角色與文件等級執行混合檢索，並回傳答案與引用條文。",refused:false,latency_ms:1240,feedback:null,created_at:new Date().toISOString(),citations:[{rank:1,doc_title:"公司內部作業規範（展示）",version:"v1.0",article_no:"第3條",score:.86,preview:"展示用假資料，並非正式文件內容。"}]};
    }else{
      answer=await api.post(`/conversations/${state.conversationId}/messages`,{content});
    }
    state.messages.push(answer);
    const convo=state.conversations.find(c=>c.id===state.conversationId);
    if(convo&&(!convo.title||convo.title==="新對話"))convo.title=content.slice(0,28);
    renderConversationList();
  }catch(error){
    toast(error.message,"error");
    state.messages.push({role:"assistant",content:error.status===503?"AI 服務暫時無法使用，請稍後再試。":error.status===403?"目前帳號沒有權限執行此操作。":`目前無法取得回答：${error.message}`,refused:true,created_at:new Date().toISOString(),citations:[]});
  }finally{state.busy=false;$("#sendButton").disabled=false;renderMessages();}
}
function showAdmin() {
  if(state.user?.role!=="it_admin"){toast("此功能僅供 IT 管理員使用。","error");return;}
  $("#chatPage").hidden=true;$("#adminPage").hidden=false;$("#pageHeading").textContent="管理中心";$("#adminNav")?.classList.add("active");renderAdmin();
}
function showChat() {$("#adminPage").hidden=true;$("#chatPage").hidden=false;$("#pageHeading").textContent="AI 知識助理";$("#adminNav")?.classList.remove("active");$("#chatNav")?.classList.add("active");}
async function renderAdmin() {
  if(state.user?.role!=="it_admin")return;
  document.querySelectorAll(".admin-tab").forEach(b=>{b.classList.toggle("active",b.dataset.tab===state.adminTab);b.onclick=()=>{state.adminTab=b.dataset.tab;renderAdmin();};});
  const root=$("#adminContent");
  root.innerHTML='<div class="empty-state">載入管理資料…</div>';
  try{
    if(state.adminTab==="documents")await renderDocuments(root);
    if(state.adminTab==="users")await renderUsers(root);
    if(state.adminTab==="audit")await renderAudit(root);
    if(state.adminTab==="evaluation")await renderEvaluation(root);
  }catch(e){root.innerHTML=`<div class="panel empty-state">無法載入資料：${escapeHtml(e.message)}</div>`;}
}
async function renderDocuments(root) {
  const data=DEMO_MODE?{items:demoData.docs,total:demoData.docs.length}:await api.get("/documents?limit=50&offset=0");
  root.innerHTML=`<div class="panel"><div class="panel-header"><div><h2>知識文件庫</h2><p>管理文件版本、存取等級與向量化處理狀態。</p></div><div class="panel-tools"><select class="filter-select" id="docStatusFilter"><option value="">全部狀態</option><option value="ready">可用</option><option value="pending">處理中</option><option value="failed">失敗</option><option value="deprecated">已作廢</option></select><button class="button button-primary button-small" id="uploadDocument">＋ 上傳文件</button></div></div>
  <div class="table-wrap"><table><thead><tr><th>文件名稱</th><th>版本</th><th>所屬部門 ID</th><th>存取等級</th><th>狀態</th><th>生效日期</th><th>操作</th></tr></thead><tbody id="documentRows">${data.items.map(d=>`<tr data-status="${d.status}"><td><strong>${escapeHtml(d.title)}</strong><div class="citation-meta">${escapeHtml(d.source||"來源未提供")}</div></td><td>${escapeHtml(d.version)}</td><td>${escapeHtml(d.dept_id)}</td><td>${badge(d.level,levelLabel(d.level))}</td><td>${badge(d.status)}</td><td>${escapeHtml(d.effective_date||"—")}</td><td><button class="table-action" data-reprocess="${d.id}">重新處理</button>${d.status!=="deprecated"?`<button class="table-action" data-deprecate="${d.id}">作廢</button>`:""}</td></tr>`).join("")}</tbody></table></div><div class="pagination"><span>共 ${data.total} 筆文件</span><span>每頁 50 筆</span></div></div>`;
  $("#docStatusFilter").onchange=e=>document.querySelectorAll("#documentRows tr").forEach(r=>r.hidden=!!e.target.value&&r.dataset.status!==e.target.value);
  $("#uploadDocument").onclick=()=>showUploadModal();
  root.querySelectorAll("[data-reprocess]").forEach(b=>b.onclick=async()=>{try{if(!DEMO_MODE)await api.post(`/documents/${b.dataset.reprocess}/processing-jobs`,{});toast("已送出重新處理要求。");}catch(e){toast(e.message,"error");}});
  root.querySelectorAll("[data-deprecate]").forEach(b=>b.onclick=async()=>{if(!confirm("確定將此文件標記為作廢？"))return;try{if(!DEMO_MODE)await api.patch(`/documents/${b.dataset.deprecate}`,{status:"deprecated"});toast("文件已標記為作廢。");await renderAdmin();}catch(e){toast(e.message,"error");}});
}
function showUploadModal() {
  const modal=document.createElement("div");modal.className="upload-modal";modal.innerHTML=`<form class="modal-card" id="uploadForm"><h2>上傳知識文件</h2><p>文件上傳後會進入背景解析與向量化流程。</p>
  <div class="modal-field"><label>文件檔案</label><input type="file" name="file" accept=".txt,.md" required></div>
  <div class="modal-field"><label>文件名稱</label><input name="title" required maxlength="255" placeholder="例如：環安衛作業程序"></div>
  <div class="modal-grid"><div class="modal-field"><label>所屬部門</label><select name="dept_code">${state.departments.map(d=>`<option value="${escapeHtml(d.code)}">${escapeHtml(d.name)}</option>`).join("")}</select></div><div class="modal-field"><label>文件等級</label><select name="level"><option value="public">公開</option><option value="dept">部門</option><option value="restricted">限閱</option></select></div></div>
  <div class="modal-grid"><div class="modal-field"><label>版本</label><input name="version" value="v1"></div><div class="modal-field"><label>生效日期</label><input name="effective_date" type="date"></div></div>
  <div class="modal-actions"><button class="button button-small" type="button" id="cancelUpload">取消</button><button class="button button-primary button-small" type="submit">上傳文件</button></div></form>`;
  document.body.append(modal);$("#cancelUpload").onclick=()=>modal.remove();
  $("#uploadForm").onsubmit=async e=>{e.preventDefault();if(DEMO_MODE){toast("展示模式不會上傳實際文件。");modal.remove();return;}
    const form=new FormData(e.currentTarget);
    try{const r=await fetch(`${API_BASE_URL}/documents`,{method:"POST",body:form,credentials:"include",headers:api.accessToken?{Authorization:`Bearer ${api.accessToken}`}:{}});if(!r.ok){const x=await r.json();throw new Error(x.message||"上傳失敗");}toast("文件已受理，正在處理。");modal.remove();await renderAdmin();}catch(err){toast(err.message,"error");}
  };
}
async function renderUsers(root) {
  const data=DEMO_MODE?{items:demoData.users,total:demoData.users.length}:await api.get("/users?limit=50&offset=0");
  root.innerHTML=`<div class="panel"><div class="panel-header"><div><h2>使用者與角色</h2><p>檢視帳號所屬部門、角色與啟用狀態。</p></div><div class="panel-tools"><span class="muted">共 ${data.total} 位使用者</span></div></div><div class="table-wrap"><table><thead><tr><th>帳號</th><th>部門</th><th>角色</th><th>狀態</th><th>操作</th></tr></thead><tbody>${data.items.map(u=>`<tr><td><strong>${escapeHtml(u.email)}</strong><div class="citation-meta">ID ${u.id}</div></td><td>${escapeHtml(u.department?.name||"—")}</td><td>${escapeHtml(roleLabel(u.role))}</td><td>${badge(u.is_active?"active":"inactive",u.is_active?"啟用":"停用")}</td><td><button class="table-action" data-edit-user="${u.id}" data-role="${u.role}" data-active="${u.is_active}">修改角色／狀態</button></td></tr>`).join("")}</tbody></table></div><div class="pagination"><span>使用者權限由後端授權判斷</span><span>每頁 50 筆</span></div></div>`;
  root.querySelectorAll("[data-edit-user]").forEach(b=>b.onclick=async()=>{const role=prompt("輸入角色：employee、manager、it_admin",b.dataset.role);if(!role)return;if(!["employee","manager","it_admin"].includes(role)){toast("角色值不正確。","error");return;}const active=confirm("按「確定」設為啟用；按「取消」設為停用。");try{if(!DEMO_MODE)await api.patch(`/users/${b.dataset.editUser}`,{role,is_active:active});toast("使用者設定已更新。");await renderAdmin();}catch(e){toast(e.message,"error");}});
}
async function renderAudit(root) {
  const data=DEMO_MODE?{items:demoData.audits,total:demoData.audits.length}:await api.get("/audit-logs?limit=50&offset=0");
  root.innerHTML=`<div class="panel"><div class="panel-header"><div><h2>系統稽核紀錄</h2><p>追蹤登入、提問、文件與使用者異動；紀錄不應包含提示詞或文件本文。</p></div><div class="panel-tools"><input class="field" id="auditUser" type="number" min="1" placeholder="使用者 ID"><button class="button button-small" id="auditFilter">套用篩選</button></div></div><div class="table-wrap"><table><thead><tr><th>時間</th><th>使用者 ID</th><th>操作事件</th><th>目標</th><th>來源 IP</th></tr></thead><tbody id="auditRows">${data.items.map(a=>`<tr data-user="${a.user_id||""}"><td>${formatDate(a.created_at)}</td><td>${escapeHtml(a.user_id??"—")}</td><td><strong>${escapeHtml(a.action)}</strong></td><td>${escapeHtml(a.target||"—")}</td><td>${escapeHtml(a.ip||"—")}</td></tr>`).join("")}</tbody></table></div><div class="pagination"><span>共 ${data.total} 筆紀錄</span><span>只讀稽核資料</span></div></div>`;
  $("#auditFilter").onclick=()=>{const id=$("#auditUser").value;document.querySelectorAll("#auditRows tr").forEach(r=>r.hidden=!!id&&r.dataset.user!==id);};
}
async function renderEvaluation(root) {
  const data=DEMO_MODE?{items:demoData.runs,total:demoData.runs.length}:await api.get("/eval-runs?limit=20&offset=0");
  const latest=data.items[0],m=latest?.metrics;
  root.innerHTML=`<div class="panel-header" style="padding:0 0 15px;border:0"><div><h2>檢索與回答品質</h2><p>依固定測試集追蹤檢索命中、拒答能力與回應時間。</p></div><button class="button button-primary button-small" id="runEval">執行評測</button></div>
  ${m?`<div class="metric-grid"><div class="metric-card"><small>Hit@1</small><strong>${(m.hit_at_1*100).toFixed(1)}%</strong><span>目標：依測試集追蹤</span></div><div class="metric-card"><small>Hit@3</small><strong>${(m.hit_at_3*100).toFixed(1)}%</strong><span>企劃目標 ≥ 85%</span></div><div class="metric-card"><small>MRR</small><strong>${m.mrr.toFixed(2)}</strong><span>企劃目標 ≥ 0.75</span></div><div class="metric-card"><small>拒答正確率</small><strong>${(m.refuse_accuracy*100).toFixed(1)}%</strong><span>企劃目標 ≥ 90%</span></div></div><div class="metric-grid"><div class="metric-card"><small>p50 回應時間</small><strong>${(m.p50_ms/1000).toFixed(2)}s</strong><span>中位數</span></div><div class="metric-card"><small>p95 回應時間</small><strong>${(m.p95_ms/1000).toFixed(2)}s</strong><span>企劃目標 ≤ 10 秒</span></div></div>`:""}
  <div class="panel"><div class="panel-header"><div><h2>評測批次</h2><p>比較不同 embedding model 與檢索參數。</p></div></div><div class="table-wrap"><table><thead><tr><th>批次</th><th>Embedding Model</th><th>開始時間</th><th>完成時間</th><th>Hit@3</th><th>MRR</th><th>操作</th></tr></thead><tbody>${data.items.map(r=>`<tr><td>#${r.id}</td><td>${escapeHtml(r.embed_model)}</td><td>${formatDate(r.started_at)}</td><td>${formatDate(r.finished_at)}</td><td>${r.metrics?`${(r.metrics.hit_at_3*100).toFixed(1)}%`:"—"}</td><td>${r.metrics?r.metrics.mrr.toFixed(2):"—"}</td><td><button class="table-action" data-results="${r.id}">查看失敗案例</button></td></tr>`).join("")}</tbody></table></div></div><div id="evalResults" style="margin-top:14px"></div>`;
  $("#runEval").onclick=async()=>{try{if(!DEMO_MODE)await api.post("/eval-runs",{});toast("評測已受理，請稍後重新整理批次。");}catch(e){toast(e.message,"error");}};
  root.querySelectorAll("[data-results]").forEach(b=>b.onclick=async()=>{try{const rows=DEMO_MODE?[{case_id:12,question:"無答案問題：某設備維修費用？",hit_rank:null,refused:true,latency_ms:2400},{case_id:9,question:"文件版本與生效日如何判斷？",hit_rank:4,refused:false,latency_ms:3600}]:await api.get(`/eval-runs/${b.dataset.results}/results?failed_only=true`);$("#evalResults").innerHTML=`<div class="panel"><div class="panel-header"><div><h2>失敗案例 · 批次 #${b.dataset.results}</h2><p>用於檢查檢索未命中、錯誤拒答與延遲問題。</p></div></div><div class="table-wrap"><table><thead><tr><th>測試題 ID</th><th>問題</th><th>命中名次</th><th>是否拒答</th><th>耗時</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${x.case_id}</td><td>${escapeHtml(x.question)}</td><td>${x.hit_rank??"未命中"}</td><td>${x.refused?"是":"否"}</td><td>${x.latency_ms??"—"} ms</td></tr>`).join("")}</tbody></table></div></div>`;}catch(e){toast(e.message,"error");}});
}
function bindLayout() {
  $("#authForm").addEventListener("submit",handleAuth);$("#authSwitch").addEventListener("click",toggleAuthMode);
  $("#chatForm").addEventListener("submit",handleAsk);$("#newConversation").addEventListener("click",createConversation);$("#chatNav").addEventListener("click",showChat);
  $("#logoutButton").addEventListener("click",()=>doLogout());$("#topLogout").addEventListener("click",()=>doLogout());
  $("#menuButton").addEventListener("click",()=>{$("#sidebar").classList.add("open");$("#mobileScrim").classList.add("show");});
  $("#mobileScrim").addEventListener("click",()=>{$("#sidebar").classList.remove("open");$("#mobileScrim").classList.remove("show");});
  $("#chatInput").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();$("#chatForm").requestSubmit();}});
  $("#chatInput").addEventListener("input",e=>{e.target.style.height="auto";e.target.style.height=Math.min(e.target.scrollHeight,130)+"px";});
}
async function init() {
  bindLayout();
  $("#environmentTag").textContent=DEMO_MODE?"DEMO DATA":"API MODE";
  if(DEMO_MODE){
    state.departments=demoData.departments;
    showAuth(); await loadDepartments();
    $("#email").value="it.admin@company.test";$("#password").value="demo-password";
    $("#connectionLabel").textContent="展示模式";
    return;
  }
  try {
    const ok=await api.refresh();
    if(!ok){showAuth();await loadDepartments();$("#connectionLabel").textContent="尚未登入";return;}
    state.user=await api.get("/me");setUser(state.user);showWorkspace();await loadConversations();
    $("#connectionLabel").textContent="API 已連線";
  } catch {
    showAuth();try{await loadDepartments();}catch(e){toast(`無法載入部門清單：${e.message}`,"error");}
    $("#connectionLabel").textContent="尚未連線";
  }
}
init();
