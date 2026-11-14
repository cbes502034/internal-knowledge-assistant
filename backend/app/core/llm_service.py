"""模型服務層：所有模型呼叫的唯一入口。其他模組不直接呼叫 Ollama 或 Hugging Face。

對應職缺：LLM API 串接；將生成式 AI 落地到現有系統
規格測試：tests/spec/test_llm_service.py

好處：換模型只改這個檔案；錯誤處理集中；測試可以整個換成假的。

可選的實作方式（自己決定並能說明理由）：
  嵌入：(a) sentence-transformers 載入 BAAI/bge-m3（pip install -r requirements-ml.txt）
        (b) Ollama 的 /api/embed（ollama pull bge-m3）
  生成：Ollama 的 /api/generate 或 /api/chat（httpx 呼叫 settings.ollama_url）
"""
import time
from collections.abc import Callable


class LLMUnavailableError(Exception):
    """模型暫時無法使用。呼叫端只需要接這個例外，不必知道背後是哪個服務。"""


class LLMService:
    MAX_RETRIES = 3
    BASE_DELAY = 1.0          # 重試等待 1、2、4 秒

    def __init__(self, sleep: Callable[[float], None] = time.sleep):
        self._sleep = sleep   # 可注入，測試時不用真的等待

    def _call_with_retry(self, func: Callable):
        """TODO：執行 func；暫時性錯誤（逾時、連線失敗、5xx）重試，最多 MAX_RETRIES 次。

        - 每次重試前等待 BASE_DELAY * 2 ** 已重試次數
        - 重試用完或遇到非暫時性錯誤 → raise LLMUnavailableError（訊息不含內部細節）
        - 日誌只記：操作、模型、耗時、是否成功、重試次數；不記提示詞與文件內容
        """
        raise NotImplementedError("core.llm_service.LLMService._call_with_retry 尚未實作")

    def embed(self, text: str) -> list[float]:
        """TODO：文字 → 向量（長度 = settings.embed_dim）。"""
        raise NotImplementedError("core.llm_service.LLMService.embed 尚未實作")

    def generate(self, prompt: str) -> str:
        """TODO：提示詞 → 回答文字。記得設定逾時與輸出長度上限。"""
        raise NotImplementedError("core.llm_service.LLMService.generate 尚未實作")
