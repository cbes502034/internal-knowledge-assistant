"""
RAG 問答流程的總指揮：檢索 -> 組 context -> 組 prompt -> 生成 -> 附出處。
對應職缺：LLM / RAG / Agent 應用開發（整條鏈串起來的地方，也是面試最容易被叫去白板畫的一張圖）。
"""

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.llm_service import LLMService, LLMUnavailableError
from app.core.retriever import Hit, hybrid_search
from app.models.user import User

# 檢索不到足夠相關內容時的固定回答：寧可拒答，也不要讓模型憑空編造
REFUSE_TEXT = "根據目前可查閱的文件，找不到足以回答這個問題的依據，請洽相關部門確認。"

# 模型服務連不上時的回答
LLM_DOWN_TEXT = "AI 服務暫時無法使用，請稍後再試。"

PROMPT_TEMPLATE = """你是公司內部規章與 SOP 的問答助理。
只能根據下方【參考資料】回答，資料中沒有的內容一律回答「找不到依據」，不要自行推測。
回答時請標註引用的文件名稱與條號。

【參考資料】
{context}

【問題】
{question}
"""

TOP_K = 5  # 最後交給模型看幾筆
MAX_CONTEXT_CHARS = 3000  # 參考資料的字數上限，避免超過模型能吃的長度
# 拒答門檻：最相近的那筆向量相似度低於它就拒答。
# 數值來源（bge-m3、6 題評測）：該拒答的題目最高 0.49、可回答的題目最低 0.66，取缺口中間值。
# 題數很少，只能當起點；題庫變多或換嵌入模型都要重新量。
MIN_SIMILARITY = 0.57


def fit_hits(hits: list[Hit], max_chars: int = MAX_CONTEXT_CHARS) -> list[Hit]:
    """依相關性順序保留放得進字數上限的 hits；至少保留第一筆。"""
    used: list[Hit] = []
    total = 0
    for hit in hits:
        total += len(hit.content)
        if used and total > max_chars:
            break
        used.append(hit)
    return used


def build_context(hits: list[Hit]) -> str:
    """把檢索到的 Hit 排成給模型看的參考資料文字，每筆要帶文件標題與條號，方便模型引用。"""
    # TODO 1. 決定單筆的格式，例如：[文件標題 第三條] 內文
    blocks = []
    for hit in hits:
        label = f"{hit.doc_title} {hit.article_no}" if hit.article_no else hit.doc_title
        blocks.append(f"[{label}]\n{hit.content}")

    # TODO 2. 思考：hits 太多、context 超過模型長度上限時怎麼辦？
    # 答：超長的處理放在 fit_hits（依相關性由高到低保留放得下的，後面的捨棄），
    #     這裡只負責排版，這樣「給模型看的」和「回傳給前端的出處」會是同一批 hits
    return "\n\n".join(blocks)


def answer_question(db: Session, user: User, question: str, llm: LLMService | None = None) -> dict:
    """完整問答流程；回傳 {'answer': 回答文字, 'citations': 引用的 Hit 清單}。"""
    # llm 參數讓測試可以換成假的模型；平常不傳，就依設定檔建立
    llm = llm or LLMService(
        settings.ollama_base_url,
        settings.embed_model,
        settings.chat_model,
        timeout=settings.llm_timeout,
    )

    try:
        # TODO 1. 用 LLMService.embed 把問題轉成向量
        query_embedding = llm.embed(question)

        # TODO 2. 呼叫 hybrid_search 取得 hits（權限過濾已在檢索層處理）
        hits = hybrid_search(db, question, query_embedding, user, k=TOP_K)

        # TODO 3. 拒答判斷：hits 為空或最高分低於門檻，直接回傳 REFUSE_TEXT（門檻怎麼定？用評測資料去量，不要憑感覺）
        # 判斷用「向量相似度」而不是 RRF 分數：RRF 只看名次，再不相關的問題也會有名次、也會有分數，
        # 沒辦法回答「到底夠不夠像」；餘弦相似度才是有絕對意義的數字
        best_similarity = max((hit.similarity for hit in hits if hit.similarity is not None), default=0.0)
        if not hits or best_similarity < MIN_SIMILARITY:
            return {"answer": REFUSE_TEXT, "citations": []}

        # TODO 4. build_context + PROMPT_TEMPLATE 組出 prompt，呼叫 LLMService.generate
        used_hits = fit_hits(hits)
        prompt = PROMPT_TEMPLATE.format(context=build_context(used_hits), question=question)
        answer = llm.generate(prompt)

    except LLMUnavailableError:
        # TODO 5. 捕捉 LLMUnavailableError，回傳友善訊息
        return {"answer": LLM_DOWN_TEXT, "citations": []}

    # TODO 6. 回答時一併回傳 citations，前端才能顯示出處
    # 只回傳真正放進 prompt 的那些 hits，出處才和模型實際看到的資料一致
    return {"answer": answer, "citations": used_hits}
