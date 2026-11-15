"""
LLM 服務封裝：文字轉向量（embedding）與文字生成（generation）。
對應職缺：LLM API 串接、高可用性（重試、逾時、降級）。

設計重點：上層（rag.py）只認這個類別的 embed / generate，不關心底層是 Ollama、HF 還是別家 API，
日後換模型只改這個檔案。

套件提示：httpx（呼叫 HTTP API，支援逾時設定）、time（重試之間的等待）。
"""


class LLMUnavailableError(Exception):
    """模型服務連不上或重試用完仍失敗；上層應捕捉它並回傳友善訊息，而不是讓 500 直接噴給使用者。"""


class LLMService:
    """封裝對模型服務的所有呼叫。"""

    def __init__(self, base_url: str, embed_model: str, chat_model: str, timeout: float = 30.0, max_retries: int = 3):
        """base_url 例如本機 Ollama 的位址；兩個 model 分別是向量模型與對話模型。"""
        # TODO 1. 把參數存成屬性
        # TODO 2. 思考：timeout 設太長、太短各會發生什麼事？
        raise NotImplementedError("TODO: LLMService.__init__")

    def _call_with_retry(self, path: str, payload: dict) -> dict:
        """對模型服務發 POST；失敗時依序重試，等待時間逐次加倍（指數退避），用盡後拋 LLMUnavailableError。"""
        # TODO 1. 迴圈最多 max_retries 次，用 httpx 發請求並設定 timeout
        # TODO 2. 哪些錯誤值得重試（連線失敗、逾時、5xx），哪些不該（4xx 通常是你的請求本身有問題）？
        # TODO 3. 每次失敗後 sleep 1、2、4 秒…，避免對正在掛掉的服務狂轟
        raise NotImplementedError("TODO: LLMService._call_with_retry")

    def embed(self, text: str) -> list[float]:
        """回傳這段文字的向量；維度要和資料庫 Vector 欄位的維度一致。"""
        # TODO 1. 組出對應 API 的 payload，呼叫 _call_with_retry
        # TODO 2. 從回應取出向量；回應格式請對照你選的模型服務文件
        raise NotImplementedError("TODO: LLMService.embed")

    def generate(self, prompt: str) -> str:
        """回傳模型對 prompt 的完整回答文字。"""
        # TODO 1. 關閉串流（stream=False）先求簡單，之後要做打字機效果再改
        # TODO 2. 思考：temperature 要設高還是低？查資料型的問答為什麼偏好低？
        raise NotImplementedError("TODO: LLMService.generate")
