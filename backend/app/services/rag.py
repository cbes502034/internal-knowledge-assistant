"""
RAG 問答流程的總指揮：檢索 -> 組 context -> 組 prompt -> 生成 -> 附出處。
對應職缺：LLM / RAG / Agent 應用開發（整條鏈串起來的地方，也是面試最容易被叫去白板畫的一張圖）。
"""

from sqlalchemy.orm import Session

from app.core.retriever import Hit
from app.models.user import User

# 檢索不到足夠相關內容時的固定回答：寧可拒答，也不要讓模型憑空編造
REFUSE_TEXT = "根據目前可查閱的文件，找不到足以回答這個問題的依據，請洽相關部門確認。"

PROMPT_TEMPLATE = """你是公司內部規章與 SOP 的問答助理。
只能根據下方【參考資料】回答，資料中沒有的內容一律回答「找不到依據」，不要自行推測。
回答時請標註引用的文件名稱與條號。

【參考資料】
{context}

【問題】
{question}
"""


def build_context(hits: list[Hit]) -> str:
    """把檢索到的 Hit 排成給模型看的參考資料文字，每筆要帶文件標題與條號，方便模型引用。"""
    # TODO 1. 決定單筆的格式，例如：[文件標題 第三條] 內文
    # TODO 2. 思考：hits 太多、context 超過模型長度上限時怎麼辦？
    raise NotImplementedError("TODO: build_context")


def answer_question(db: Session, user: User, question: str) -> dict:
    """完整問答流程；回傳 {'answer': 回答文字, 'citations': 引用的 Hit 清單}。"""
    # TODO 1. 用 LLMService.embed 把問題轉成向量
    # TODO 2. 呼叫 hybrid_search 取得 hits（權限過濾已在檢索層處理）
    # TODO 3. 拒答判斷：hits 為空或最高分低於門檻，直接回傳 REFUSE_TEXT（門檻怎麼定？用評測資料去量，不要憑感覺）
    # TODO 4. build_context + PROMPT_TEMPLATE 組出 prompt，呼叫 LLMService.generate
    # TODO 5. 捕捉 LLMUnavailableError，回傳友善訊息
    # TODO 6. 回傳答案時一併回傳 citations，前端才能顯示出處
    raise NotImplementedError("TODO: answer_question")
