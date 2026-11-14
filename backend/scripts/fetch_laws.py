"""從全國法規資料庫下載法規全文，存成 data/raw/laws/<法規名稱>.txt。

執行（在 backend/ 下）：python -m scripts.fetch_laws
法律、命令依著作權法第 9 條不是著作權的標的，可以自由使用；使用前仍請確認是否為現行版本。
"""
import html
import re
import time
from datetime import date

import httpx

from app.config import ROOT_DIR

LAWS = {
    "N0060001": "職業安全衛生法",
    "N0060054": "危害性化學品標示及通識規則",
    "O0050001": "廢棄物清理法",
}
URL = "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
OUT_DIR = ROOT_DIR / "data" / "raw" / "laws"

_ROW_RE = re.compile(r'<div class="col-no">.*?>(第\s*[\d\-\s]+條)</a></div>\s*<div class="col-data">(.*?)</div>\s*</div>\s*</div>',
                     re.S)
_LINE_RE = re.compile(r'<div class="line-\d+[^"]*">(.*?)</div>', re.S)   # 項的首行會多一個 show-number


def _clean(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def parse(page: str) -> tuple[str, list[tuple[str, str]]]:
    """回傳 (修正日期, [(條號, 條文)])。章節標題不在 col-no 裡，自然被略過。"""
    amended = re.search(r"修正日期：</th>\s*<td[^>]*>(.*?)</td>", page, re.S) or re.search(r"(民國\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)", page)
    articles = []
    for number, body in _ROW_RE.findall(page):
        lines = [_clean(line) for line in _LINE_RE.findall(body)] or [_clean(body)]
        articles.append((re.sub(r"\s+", " ", number), "\n".join(line for line in lines if line)))
    return _clean(amended.group(1)) if amended else "未知", articles


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "Mozilla/5.0 (internal-knowledge-assistant; study project)"}
    with httpx.Client(headers=headers, timeout=60, follow_redirects=True) as client:
        for pcode, name in LAWS.items():
            page = client.get(URL.format(pcode=pcode)).text
            if name not in page:
                print(f"略過 {pcode}：頁面不是 {name}")
                continue
            amended, articles = parse(page)
            header = (f"法規名稱：{name}\n修正日期：{amended}\n來源：全國法規資料庫 {URL.format(pcode=pcode)}\n"
                      f"擷取日期：{date.today().isoformat()}\n\n")
            body = "\n".join(f"{number}\n{text}" for number, text in articles)
            (OUT_DIR / f"{name}.txt").write_text(header + body + "\n", encoding="utf-8")
            print(f"{name}：{len(articles)} 條（修正日期 {amended}）")
            time.sleep(1)          # 對公家網站客氣一點，不要連續猛抓


if __name__ == "__main__":
    main()
