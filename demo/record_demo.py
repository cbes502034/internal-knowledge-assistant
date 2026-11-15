"""內部知識助理完整流程的示範影片（做法照 final_project/report/qa/record_demo.py）。
無頭 Chrome 逐格擷取畫面，下面接一條中文字幕帶（不疊在網頁上），合成 MP4。

    python demo/record_demo.py --trial      試跑：不錄影，每一步存一張截圖（快很多），先確認每一步都對
    python demo/record_demo.py              正式錄影，產出 demo/知識助理_完整流程.mp4

事前準備：後端、前端都已啟動，資料庫裡有示範文件（python -m scripts.import_samples），
並且有一個營運部員工帳號與一個 IT 管理員帳號。帳密在終端機輸入（密碼不顯示、不存檔，影片裡只看得到圓點）；
本機試跑可以用 --accounts 給 JSON 檔：{"employee": {"email": ..., "password": ...}, "admin": {...}}。

流程：員工登入 → 有答案的問題（附出處、展開原文、回饋）→ 用詞不同的問題 → 越權的問題 → 文件裡沒有的問題 → 登出
     → IT 管理員登入 → 同一題因為有權限所以答得出來 → 管理中心：文件 → 上傳新文件 → 處理完成 → 新文件馬上能問
     → 稽核紀錄 → 成效評測（執行並看結果）

⚠ 會在系統上留下資料：兩個帳號的對話、一份上傳的文件、一批評測。建議對臨時資料庫錄，不要對正式資料庫。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import bisect
import datetime as dt
import getpass
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import httpx
import websockets
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
W, H = 1280, 800
BAND = 128                                   # 字幕帶：接在網頁畫面下面，不疊在網頁上
FONTS = r"C:\Windows\Fonts"
_fonts, _bands = {}, {}


def font(name, size):
    from PIL import ImageFont
    if (name, size) not in _fonts:
        _fonts[name, size] = ImageFont.truetype(os.path.join(FONTS, name), size)
    return _fonts[name, size]


def caption_band(cap):
    """字幕帶：第一行「第幾步＋標題」、第二行說明，置中。cap 是 (第幾步, 共幾步, 標題, 說明)；None 是片頭片尾（空白）"""
    if cap not in _bands:
        from PIL import ImageDraw
        img = Image.new("RGB", (W, BAND), (11, 15, 20))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 2], fill=(10, 186, 181))
        if cap:
            n, total, title, desc = cap
            tag, f_tag, f_title = "%d / %d" % (n, total), font("consolab.ttf", 20), font("msjhbd.ttc", 34)
            tag_w = d.textlength(tag, font=f_tag) + 20
            x = (W - tag_w - 16 - d.textlength(title, font=f_title)) / 2
            d.rectangle([x, 28, x + tag_w, 58], fill=(10, 186, 181))
            d.text((x + tag_w / 2, 43), tag, font=f_tag, fill=(11, 15, 20), anchor="mm")
            d.text((x + tag_w + 16, 43), title, font=f_title, fill=(255, 255, 255), anchor="lm")
            size = 24
            while size > 16 and d.textlength(desc, font=font("msjh.ttc", size)) > W - 80:
                size -= 1
            d.text((W / 2, 92), desc, font=font("msjh.ttc", size), fill=(219, 228, 236), anchor="mm")
        _bands[cap] = img
    return _bands[cap]


def compose(img, cap):
    """網頁畫面＋下面的字幕帶"""
    if img.size != (W, H):
        scale = H / img.size[1]
        img = img.resize((max(1, int(img.size[0] * scale)), H))
        page = Image.new("RGB", (W, H), (11, 15, 20))
        page.paste(img, ((W - img.size[0]) // 2, 0))
        img = page
    out = Image.new("RGB", (W, H + BAND))
    out.paste(img, (0, 0))
    out.paste(caption_band(cap), (0, H))
    return out


#: 畫面上的滑鼠游標。無頭 Chrome 錄不到真的游標，所以畫一個：
#: 從上一個位置滑到目標 → 停一下 → 點的地方出現波紋 → 才真的點下去，看的人跟得上。
#: sel 是 CSS 選擇器；寫成 "text:管理中心" 是找畫面上有這幾個字的按鈕或連結。sel 是 null 時只把游標放回上次的位置。
CURSOR_JS = r"""
(async function (sel, x0, y0, pause, doClick) {
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };
  var cur = document.getElementById('qa-cur');
  if (!cur) {
    cur = document.createElement('div'); cur.id = 'qa-cur';
    cur.innerHTML = '<svg viewBox="0 0 24 24" width="28" height="28"><path d="M2 1.5l7.8 20 2.7-8.1 8-2.8z" ' +
      'fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    cur.setAttribute('style', 'position:fixed;left:0;top:0;width:28px;height:28px;z-index:2147483647;pointer-events:none;' +
      'filter:drop-shadow(0 2px 3px rgba(0,0,0,.45));transition:transform .8s cubic-bezier(.45,0,.25,1);' +
      'transform:translate(' + (x0 - 2) + 'px,' + (y0 - 2) + 'px)');
    document.documentElement.appendChild(cur);
    await sleep(60);
  }
  if (!sel) return [x0, y0];
  var el = null;
  if (sel.indexOf('text:') === 0) {
    var want = sel.slice(5);
    el = Array.prototype.filter.call(document.querySelectorAll('a,button,label,summary'),
      function (e) { return e.offsetParent !== null && e.textContent.trim().indexOf(want) >= 0; })[0];
  } else {
    el = document.querySelector(sel);
  }
  if (!el) return null;
  var r = el.getBoundingClientRect();
  if (r.top < 70 || r.bottom > innerHeight - 100) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    await sleep(750);
    r = el.getBoundingClientRect();
  }
  var x = Math.round(r.left + Math.min(r.width / 2, 70)), y = Math.round(r.top + r.height / 2);
  cur.style.transform = 'translate(' + (x - 2) + 'px,' + (y - 2) + 'px)';
  await sleep(850);
  await sleep(pause * 1000);
  if (doClick) {
    var rip = document.createElement('div');
    rip.setAttribute('style', 'position:fixed;left:' + (x - 20) + 'px;top:' + (y - 20) + 'px;width:40px;height:40px;' +
      'border:3px solid #2BFFE0;border-radius:50%;z-index:2147483646;pointer-events:none');
    document.documentElement.appendChild(rip);
    rip.animate([{ transform: 'scale(.3)', opacity: 1 }, { transform: 'scale(1.5)', opacity: 0 }], { duration: 500 });
    setTimeout(function () { rip.remove(); }, 520);
    await sleep(180);
    el.click();
  }
  return [x, y];
})
"""

CARD_CSS = """
html,body{margin:0;height:100%;background:#0b0f14;color:#e6edf3;font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif}
body{background-image:linear-gradient(#1f2a36 1px,transparent 1px),linear-gradient(90deg,#1f2a36 1px,transparent 1px);background-size:48px 48px}
.c{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 110px}
.e{color:#0ABAB5;font:14px Consolas,monospace;letter-spacing:.2em}
h1{font-size:54px;margin:18px 0 12px;color:#fff;line-height:1.2}
p{color:#a9b6c3;font-size:20px;margin:0 0 8px}
"""


def card_html(eyebrow, title, lines):
    return ("<!doctype html><html><head><meta charset='utf-8'><style>%s</style></head><body><div class='c'>"
            "<div class='e'>%s</div><h1>%s</h1>%s</div></body></html>") % (
        CARD_CSS, eyebrow, title, "".join("<p>%s</p>" % x for x in lines))


class CDP:
    def __init__(self, ws):
        self.ws, self.seq, self.wait, self.frames = ws, 0, {}, []
        self.recording = False
        self.ff = []          # [(開始, 結束, 合成後最多幾秒)]：等載入、等模型的片段，合成時快轉
        self.caps = []        # [(時間, (第幾步, 共幾步, 標題, 說明) 或 None)]：字幕帶什麼時候換字
        self.errors = []      # 頁面上的 JavaScript 錯誤：卡住的時候印出來

    async def reader(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if msg.get("method") == "Page.screencastFrame":
                p = msg["params"]
                if self.recording:
                    self.frames.append((p["metadata"]["timestamp"], base64.b64decode(p["data"])))
                self.seq += 1
                await self.ws.send(json.dumps({"id": self.seq, "method": "Page.screencastFrameAck",
                                               "params": {"sessionId": p["sessionId"]}}))
            elif msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errors.append((d.get("exception") or {}).get("description") or d.get("text"))
            elif "id" in msg and msg["id"] in self.wait:
                self.wait.pop(msg["id"]).set_result(msg)

    async def send(self, method, **params):
        self.seq += 1
        me = self.seq
        fut = asyncio.get_event_loop().create_future()
        self.wait[me] = fut
        await self.ws.send(json.dumps({"id": me, "method": method, "params": params}))
        msg = await asyncio.wait_for(fut, 60)
        if "error" in msg:
            raise RuntimeError("%s: %s" % (method, msg["error"]))
        return msg.get("result", {})

    async def js(self, expr, wait=False):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=wait, returnByValue=True)
        return r.get("result", {}).get("value")


class Api:
    """用 API 看後端的狀態（文件處理好了沒、評測跑完了沒）：影片裡不用等的部分，不必在畫面上一直重新整理。"""

    def __init__(self, base, admin):
        r = httpx.post(base + "/auth/token", data={"grant_type": "password", "username": admin["email"], "password": admin["password"]}, timeout=60)
        if r.status_code != 200:
            raise SystemExit("管理員帳號登入失敗（%s）：%s" % (r.status_code, r.text[:200]))
        self.base = base
        self.h = {"Authorization": "Bearer " + r.json()["access_token"]}

    def get(self, path):
        return httpx.get(self.base + path, headers=self.h, timeout=60).json()


async def run(ws_url, args, acc, workdir):
    front, api_base = args.front.rstrip("/"), args.api.rstrip("/")
    trial = args.trial
    pace = 0.3 if trial else 1.0
    emp, adm = acc["employee"], acc["admin"]
    api = Api(api_base, adm)
    upload_file = os.path.abspath(args.upload_file)
    upload_title = os.path.splitext(os.path.basename(upload_file))[0]
    today = dt.date.today()
    trial_dir = args.trial_dir
    if trial:
        shutil.rmtree(trial_dir, ignore_errors=True)
        os.makedirs(trial_dir)

    async with websockets.connect(ws_url, max_size=256 * 1024 * 1024) as ws:
        c = CDP(ws)
        reader = asyncio.ensure_future(c.reader())
        await c.send("Page.enable")
        await c.send("Runtime.enable")
        await c.send("DOM.enable")
        await c.send("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
        # 步驟數＝這支腳本裡呼叫 cap() 的次數（加步驟忘了改總數，就會出現 20 / 18）
        total = io.open(__file__, encoding="utf-8").read().count("await " + "cap(")
        pos = [W // 2, H // 2]
        step = [0]
        shown = {}

        async def wait(sec):
            await asyncio.sleep(sec * pace)

        async def cap(title, desc):
            step[0] += 1
            shown.update(title=title, desc=desc)
            c.caps.append((time.time(), (step[0], total, title, desc)))
            print("  %2d/%d %s" % (step[0], total, title), flush=True)
            if trial:
                await asyncio.sleep(0.4)
                shot = await c.send("Page.captureScreenshot", format="png")
                img = Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB")
                compose(img, c.caps[-1][1]).save(os.path.join(trial_dir, "%02d_%s.png" % (step[0], title.replace("/", "／"))))

        async def click(sel, pause=0.6, do=True, need=True):
            """游標移過去、停一下、波紋、點下去。找不到：need=True 就停下來說是哪一步，不然跳過。"""
            r = await c.js("(%s)(%s, %d, %d, %s, %s)" % (CURSOR_JS, json.dumps(sel), pos[0], pos[1], pause * pace,
                                                          "true" if do else "false"), wait=True)
            if isinstance(r, (list, tuple)) and len(r) == 2:
                pos[0], pos[1] = int(r[0]), int(r[1])
            if r is None and need:
                raise RuntimeError("畫面上找不到要點的東西：%s（第 %d 步「%s」）" % (sel, step[0], shown.get("title", "")))
            return r is not None

        async def point():
            # 換頁之後游標會被清掉：放回上次的位置，不要突然消失
            await c.js("(%s)(null, %d, %d, 0, false)" % (CURSOR_JS, pos[0], pos[1]), wait=True)

        async def until(expr, timeout=40, need=True):
            # ⚠️ 一定要先轉成 true／false：querySelector 傳回來的 DOM 元素在 Python 這邊會變成空物件 {}
            t0 = time.time()
            while time.time() - t0 < timeout:
                if await c.js("!!(%s)" % expr):
                    return True
                await asyncio.sleep(0.4)
            if need:
                shot = await c.send("Page.captureScreenshot", format="png")
                with open(os.path.join(HERE, "record_fail.png"), "wb") as f:
                    f.write(base64.b64decode(shot["data"]))
                toasts = await c.js("[...document.querySelectorAll('#toastRegion > *')].map(x => x.textContent).join(' ／ ')")
                raise RuntimeError("等不到畫面：%s（第 %d 步「%s」）畫面提示：%s；頁面錯誤：%s；截圖 demo/record_fail.png"
                                   % (expr, step[0], shown.get("title", ""), toasts, c.errors[-3:]))
            return False

        async def go(url, ready=None, keep=1.0, timeout=60):
            # 從換頁到畫面準備好的這一段快轉成最多 keep 秒
            t0 = time.time()
            await c.send("Page.navigate", url=url)
            await asyncio.sleep(0.6)
            if ready:
                await until(ready, timeout)
            else:
                await asyncio.sleep(1.5)
            if not url.startswith("file:"):
                await point()
            c.ff.append((t0, time.time(), keep))

        async def busy(expr, keep=1.5, timeout=60):
            """等後端或模型做完：這一段快轉"""
            t0 = time.time()
            await until(expr, timeout)
            c.ff.append((t0, time.time(), keep))

        async def busy_api(done, keep=2.0, timeout=420):
            """等後端的背景工作（文件處理、評測）：用 API 問狀態，這一段快轉"""
            t0 = time.time()
            while time.time() - t0 < timeout:
                if await asyncio.to_thread(done):
                    break
                await asyncio.sleep(1.5)
            else:
                raise RuntimeError("等不到後端的背景工作完成（第 %d 步「%s」）" % (step[0], shown.get("title", "")))
            c.ff.append((t0, time.time(), keep))

        async def type_in(sel, text, delay=75):
            await c.js("""(async (s, t, d) => { const el = document.querySelector(s); el.focus(); el.value = '';
                          for (const ch of t) { el.value += ch; el.dispatchEvent(new Event('input', {bubbles: true}));
                          await new Promise(r => setTimeout(r, d)); } })(%s, %s, %d)"""
                       % (json.dumps(sel), json.dumps(text), int(delay * pace)), wait=True)

        async def set_val(sel, value, change=True):
            await c.js("""(function (s, v, ch) { var e = document.querySelector(s); e.value = v;
                          e.dispatchEvent(new Event('input', {bubbles: true}));
                          if (ch) e.dispatchEvent(new Event('change', {bubbles: true})); })(%s, %s, %s)"""
                       % (json.dumps(sel), json.dumps(value), "true" if change else "false"))

        async def scroll_to(sel, block="center"):
            await c.js("var e=document.querySelector(%s); if(e) e.scrollIntoView({block:%s, behavior:'smooth'})"
                       % (json.dumps(sel), json.dumps(block)))
            await asyncio.sleep(0.8)

        async def set_file(sel, path):
            """檔案選擇：瀏覽器不讓網頁自己選檔，用 DevTools 把檔案直接放進 <input type=file>"""
            r = await c.send("Runtime.evaluate", expression="document.querySelector(%s)" % json.dumps(sel))
            await c.send("DOM.setFileInputFiles", files=[path], objectId=r["result"]["objectId"])

        async def login(user, who):
            await click("#email", pause=0.3)
            await type_in("#email", user["email"], 55)
            # 密碼一次填好，畫面上只看得到圓點；這支腳本不存密碼
            await click("#password", pause=0.2)
            await set_val("#password", user["password"], change=False)
            await wait(0.8)
            await click("#authSubmit")
            await until("document.getElementById('workspace') && !document.getElementById('workspace').hidden"
                        " && document.querySelector('#chatMessages')", 40)
            await wait(0.8)

        async def ask(question, keep=2.5):
            """在輸入框打問題 → 送出 → 等助理回答（等模型的這一段快轉）"""
            n0 = await c.js("document.querySelectorAll('.message-row.assistant').length")
            await click("#chatInput", pause=0.3)
            await type_in("#chatInput", question, 70)
            await wait(0.8)
            await click("#sendButton")
            await busy("document.querySelectorAll('.message-row.assistant').length > %d" % n0, keep=keep, timeout=240)
            await wait(0.8)
            # 回答出來後，聊天區會自動捲到最底（只看得到出處卡）：往上捲到「問題＋回答的開頭」，字幕講的內容才看得到
            await scroll_to("#chatMessages .message-row:nth-last-child(2)", "start")

        def card_url(name, html):
            path = os.path.join(workdir, name + ".html")
            with io.open(path, "w", encoding="utf-8") as f:
                f.write(html)
            return "file:///" + path.replace("\\", "/")

        # ---------------------------------------------------------------- 片頭（不算步驟）
        await go(card_url("open", card_html("INTERNAL KNOWLEDGE ASSISTANT · FULL WALKTHROUGH · " + today.isoformat(), "內部知識助理<br>完整流程",
                                            ["員工提問 → 依權限檢索 → 附出處的回答 → 管理員上傳文件、稽核、評測",
                                             "在本機錄：本機模型（bge-m3、qwen2.5:3b），資料不離開本機；示範文件全部是模擬資料",
                                             "每一步下方的字幕說明正在做什麼；密碼欄只看得到圓點"])), keep=0.5)
        if not trial:
            await c.send("Page.startScreencast", format="jpeg", quality=82, maxWidth=W, maxHeight=H, everyNthFrame=1)
            c.recording = True
        await wait(4)

        # ---------------------------------------------------------------- 1. 員工
        await go(front + "/?r=%d" % (time.time() * 1000),
                 "document.getElementById('authView') && !document.getElementById('authView').hidden && document.querySelector('#department option')")
        await cap("登入頁", "用公司帳號登入；自助註冊的帳號一律是一般員工，不能自己選角色")
        await wait(3.5)
        await login(emp, "員工")
        await cap("員工登入", "營運部員工登入；右上角寫著「營運 · 依權限檢索」，只會從他看得到的文件找答案")
        await wait(3.5)

        await ask("廢溶劑可以在廠內暫存多久？")
        await cap("提問：有答案的問題", "系統把問題轉成向量，找出最相關的條文，再整理成回答；回答標明是哪份文件的第幾條")
        await wait(4)
        await click("#chatMessages .message-row:last-child .citation-expand", pause=0.4)
        await scroll_to("#chatMessages .message-row:last-child .citation-detail:not([hidden])", "center")
        await cap("出處與原文", "每個回答附上文件名稱、版本、條號和相似度，點開可以直接看條文原文來核對")
        await wait(5)
        await click('#chatMessages .message-row:last-child [data-feedback="up"]', pause=0.4)
        await cap("回饋", "對回答按「有用」或「沒用」，回饋會記錄下來")
        await wait(3)

        await ask("特休可以只請半天嗎？")
        await cap("提問：用詞不同", "條文寫的是「特別休假」「以半日為單位」，問法不同、意思相同，一樣找得到")
        await wait(4.5)

        await ask("發現資安事件要在多久內通報？", keep=1.5)
        await cap("越權的問題", "這份文件是限閱，營運部員工沒有權限：系統直接說找不到依據，不透露文件存在，也不會把內容交給模型")
        await wait(5)

        await ask("員工旅遊補助怎麼申請？", keep=1.5)
        await cap("文件裡沒有的問題", "文件裡沒有相關規定就明講找不到，請洽相關部門，不自己編答案")
        await wait(5)

        await click("#topLogout", pause=0.4)
        await until("document.getElementById('authView') && !document.getElementById('authView').hidden", 20)
        await cap("登出", "登出會作廢登入憑證（refresh token）；換 IT 管理員登入")
        await wait(3)

        # ---------------------------------------------------------------- 2. 管理員
        await login(adm, "管理員")
        await cap("管理員登入", "IT 管理員登入，左邊多了「管理中心」")
        await wait(3)
        await ask("發現資安事件要在多久內通報？")
        await cap("同一個問題，有權限就答得出來", "限閱文件只有 IT 管理員看得到；剛才員工被擋下的同一題，這裡答出第 2 條")
        await wait(5)

        await click("text:管理中心", pause=0.4)
        await until("document.querySelector('#documentRows')", 30)
        await wait(1)
        await cap("管理中心：文件", "七份示範文件，各自有存取等級和處理狀態；只有「可用」的文件才會被檢索")
        await wait(5)

        await click("#uploadDocument", pause=0.4)
        await until("document.querySelector('.upload-modal')", 10)
        await wait(0.8)
        await set_file(".upload-modal input[type=file]", upload_file)
        await click(".upload-modal input[name=title]", pause=0.3)
        await type_in(".upload-modal input[name=title]", upload_title, 70)
        await set_val(".upload-modal select[name=dept_code]", "gm_office")
        await wait(1.5)
        await cap("上傳文件", "選檔、填名稱、所屬部門和存取等級；系統先收下並回覆「已受理」，切塊與向量化在背景進行")
        await wait(4)
        await click(".upload-modal button[type=submit]", pause=0.4)
        await until("!document.querySelector('.upload-modal') && document.querySelectorAll('#documentRows tr').length >= 8", 30)
        await wait(1.5)
        await cap("處理中", "新文件一開始是「處理中」；處理完成之前不會被檢索到，也不會讓人看到半份內容")
        await wait(4)
        await busy_api(lambda: next((d["status"] for d in api.get("/documents?limit=50")["items"] if d["title"] == upload_title), "") == "ready", keep=2.0, timeout=240)
        await click('[data-tab="documents"]', pause=0.3)
        await until("document.querySelector('#documentRows tr .status.ready')", 20)
        await cap("處理完成", "狀態變成「可用」；文件已依條切塊、轉成向量存進資料庫")
        await wait(5)

        await click("#chatNav", pause=0.4)
        await until("!document.getElementById('chatPage').hidden", 10)
        await ask("領用辦公室用品要怎麼申請？")
        await cap("新文件馬上能問", "剛上傳的文件已經能查到，不用重新訓練模型；文件更新就是更新資料庫")
        await wait(5)

        # ---------------------------------------------------------------- 3. 稽核與評測
        await click("text:管理中心", pause=0.4)
        await until("document.querySelector('.admin-tab')", 10)
        await click('[data-tab="audit"]', pause=0.4)
        await until("document.querySelector('#auditRows tr')", 20)
        await wait(1)
        await cap("稽核紀錄", "誰、何時、從哪個 IP、做了什麼：登入、提問、上傳都有記錄；不記提問內容，避免機密多一個外流的地方")
        await wait(6)

        await click('[data-tab="evaluation"]', pause=0.4)
        await until("document.querySelector('#runEval')", 20)
        await cap("成效評測", "RAG 的好壞要用數字說話：按「執行評測」，用 26 題固定題庫量檢索與拒答")
        await wait(3)
        await click("#runEval", pause=0.4)
        await wait(2)
        await busy_api(lambda: api.get("/eval-runs?limit=1")["items"][0]["status"] != "running", keep=3.0, timeout=600)
        await click('[data-tab="evaluation"]', pause=0.3)
        await until("document.querySelector('.metric-grid')", 20)
        await wait(1)
        await cap("評測結果", "Hit@1、Hit@3、MRR 看正確條文排第幾；拒答正確率看該拒答時有沒有拒答；另外記錄回應時間")
        await wait(7)

        # ---------------------------------------------------------------- 片尾
        # 畫面大小沒變，擷取不用停掉再重開（重開太快的話，片尾卡的畫面會收不到）
        shown.clear()
        c.caps.append((time.time(), None))
        await go(card_url("end", card_html("END", "謝謝觀看", [
            "依權限檢索　・　附出處　・　找不到就拒答　・　文件更新馬上生效　・　可以評測"])), keep=0.5)
        await wait(5)
        c.recording = False
        if not trial:
            await c.send("Page.stopScreencast")
        reader.cancel()
        return c.frames, c.ff, c.caps


def remap(ff):
    """原本的時間 → 合成後的時間：快轉片段壓到 keep 秒，其他照原速。"""
    segs = sorted((a, b, min(1.0, k / (b - a)) if b > a else 1.0) for a, b, k in ff)

    def f(t):
        cut = 0.0
        for a, b, factor in segs:
            if t <= a:
                break
            cut += (min(t, b) - a) * (1 - factor)
        return t - cut
    return f


def encode(frames, caps, out_mp4, workdir, ff=()):
    import imageio_ffmpeg
    frames.sort(key=lambda f: f[0])
    tmap = remap(ff)
    end = frames[-1][0] + 1.5
    # 截圖串流只在網頁畫面有變的時候送一格；字幕換字時畫面不一定有變，所以換字的時間點也要切一刀
    cuts = sorted(set([f[0] for f in frames] + [tc for tc, _ in caps if frames[0][0] < tc < end]))
    cap_t = [tc for tc, _ in caps]
    lines, made, fi = [], {}, 0
    for i, ts in enumerate(cuts):
        while fi + 1 < len(frames) and frames[fi + 1][0] <= ts:
            fi += 1
        k = bisect.bisect_right(cap_t, ts) - 1
        cap = caps[k][1] if k >= 0 else None
        path = made.get((fi, cap))
        if not path:
            path = made[fi, cap] = os.path.join(workdir, "f%05d.jpg" % len(made))
            compose(Image.open(io.BytesIO(frames[fi][1])).convert("RGB"), cap).save(path, quality=90)
        nxt = cuts[i + 1] if i + 1 < len(cuts) else end
        lines.append("file '%s'\nduration %.3f" % (path.replace("\\", "/"), max(0.001, tmap(nxt) - tmap(ts))))
    lines.append("file '%s'" % path.replace("\\", "/"))
    lst = os.path.join(workdir, "list.txt")
    with io.open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "21", "-preset", "medium",
                    "-movflags", "+faststart", out_mp4], check=True, capture_output=True)
    # 每一步在影片的第幾秒開始：剪片段、做簡報時用
    t0 = tmap(frames[0][0])
    steps = [{"n": c[0], "title": c[2], "start": round(tmap(tc) - t0, 1)} for tc, c in caps if c]
    with io.open(os.path.splitext(out_mp4)[0] + "_步驟時間.json", "w", encoding="utf-8") as f:
        json.dump({"total_seconds": round(tmap(end) - t0, 1), "steps": steps}, f, ensure_ascii=False, indent=1)


def warm_up(args):
    """把兩個模型先載入記憶體：第一次呼叫要載入（生成約 40 秒），不先暖機的話，影片裡第一題的回應時間會很難看"""
    try:
        httpx.post(args.ollama + "/api/embed", json={"model": args.embed_model, "input": "暖機", "keep_alive": "30m"}, timeout=300).raise_for_status()
        httpx.post(args.ollama + "/api/generate", json={"model": args.chat_model, "prompt": "請回答：好", "stream": False, "keep_alive": "30m"}, timeout=300).raise_for_status()
        print("模型已暖機")
    except httpx.HTTPError as e:
        print("⚠ 模型暖機失敗（%s）：影片裡第一題可能會等很久" % e)


def ask_accounts(args):
    if args.accounts:
        with io.open(args.accounts, encoding="utf-8") as f:
            return json.load(f)
    print("影片會用兩個帳號：營運部員工（提問）、IT 管理員（上傳文件、稽核、評測）。")
    print("密碼不會顯示、不會存檔，影片裡的密碼欄只看得到圓點。\n")
    out = {}
    for key, label in (("employee", "營運部員工"), ("admin", "IT 管理員")):
        out[key] = {"email": input("%s的 email：" % label).strip(), "password": getpass.getpass("%s的密碼：" % label)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="內部知識助理完整流程的示範影片")
    ap.add_argument("--front", default="http://127.0.0.1:5502", help="前端網址（用 127.0.0.1，不要用 localhost：refresh cookie 的跨站限制）")
    ap.add_argument("--api", default="http://127.0.0.1:8002/api/v1", help="後端 API 網址")
    ap.add_argument("--trial", action="store_true", help="試跑：不錄影，每一步存一張截圖")
    ap.add_argument("--trial-dir", default=os.path.join(tempfile.gettempdir(), "ika-demo-trial"))
    ap.add_argument("--accounts", help="帳密的 JSON 檔（只給本機臨時資料庫用）")
    ap.add_argument("--upload-file", default=os.path.join(HERE, "upload_sample", "辦公室用品領用辦法.txt"), help="影片裡要上傳的文件")
    ap.add_argument("--out", default=os.path.join(HERE, "知識助理_完整流程.mp4"))
    ap.add_argument("--show", action="store_true", help="開出 Chrome 視窗（不是無頭），看得到它在做什麼")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434", help="Ollama 位址（錄影前先把模型暖機）")
    ap.add_argument("--embed-model", default="bge-m3")
    ap.add_argument("--chat-model", default="qwen2.5:3b")
    ap.add_argument("--no-warmup", action="store_true", help="不暖機")
    args = ap.parse_args()
    accounts = ask_accounts(args)
    if not args.no_warmup:
        warm_up(args)
    exe = next(p for p in CHROME if os.path.exists(p))
    workdir = tempfile.mkdtemp(prefix="ika-video-")
    profile = os.path.join(workdir, "profile")
    port = 9336
    flags = ["--remote-debugging-port=%d" % port, "--user-data-dir=" + profile, "--hide-scrollbars",
             "--no-first-run", "--lang=zh-TW", "--window-size=%d,%d" % (W, H)]
    if not args.show:
        flags.insert(0, "--headless=new")
    proc = subprocess.Popen([exe] + flags + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                tabs = httpx.get("http://127.0.0.1:%d/json/list" % port, timeout=1).json()
                page = next(t for t in tabs if t.get("type") == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        frames, ff, caps = asyncio.run(run(page["webSocketDebuggerUrl"], args, accounts, workdir))
        if args.trial:
            print("試跑完成，每一步的截圖在", args.trial_dir)
            return 0
        print("frames:", len(frames), "seconds:", round(frames[-1][0] - frames[0][0], 1) if frames else 0)
        encode(frames, caps, args.out, workdir, ff)
        print(args.out)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:      # 無頭 Chrome 偶爾關不掉：強制結束
            proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
