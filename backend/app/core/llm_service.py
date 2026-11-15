"""
LLM 服務封裝：文字轉向量（embedding）與文字生成（generation）。
對應職缺：LLM API 串接、高可用性（重試、逾時、降級）。

設計重點：上層（rag.py）只認這個類別的 embed / generate，不關心底層是 Ollama、HF 還是別家 API，
日後換模型只改這個檔案。

套件提示：httpx（呼叫 HTTP API，支援逾時設定）、time（重試之間的等待）。
"""

import time

import httpx


class LLMUnavailableError(Exception):
    """模型服務連不上或重試用完仍失敗；上層應捕捉它並回傳友善訊息，而不是讓 500 直接噴給使用者。"""


class LLMService:
    """封裝對模型服務的所有呼叫。"""

    def __init__(self, base_url: str, embed_model: str, chat_model: str, timeout: float = 30.0, max_retries: int = 3):
        """base_url 例如本機 Ollama 的位址；兩個 model 分別是向量模型與對話模型。"""
        # TODO 1. 把參數存成屬性
        self.base_url = base_url.rstrip("/")  # 去掉結尾斜線，之後組網址才不會變成 //api
        self.embed_model = embed_model
        self.chat_model = chat_model
        self.timeout = timeout
        self.max_retries = max_retries  # 這裡指「總共最多嘗試幾次」，不是「失敗後額外重試幾次」

        # TODO 2. 思考：timeout 設太長、太短各會發生什麼事？
        # 答：太短 → 服務只是回得慢（本機 CPU 跑生成特別明顯）就被當成失敗，重試反而讓它更忙；
        #     太長 → 服務真的掛了，請求還卡著占住連線與 worker，使用者也只能乾等。

    def _call_with_retry(self, path: str, payload: dict) -> dict:
        """對模型服務發 POST；失敗時依序重試，等待時間逐次加倍（指數退避），用盡後拋 LLMUnavailableError。"""
        last_error: Exception | None = None

        # TODO 1. 迴圈最多 max_retries 次，用 httpx 發請求並設定 timeout
        for attempt in range(1, self.max_retries + 1):
            try:
                response = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            except httpx.TransportError as e:
                # TODO 2. 哪些錯誤值得重試（連線失敗、逾時、5xx），哪些不該（4xx 通常是你的請求本身有問題）？
                # 連線失敗、逾時、網路中斷都屬於暫時性問題 → 重試
                last_error = e
            else:
                if response.is_success:
                    try:
                        return response.json()
                    except ValueError as e:
                        raise LLMUnavailableError("模型服務回應不是合法的 JSON") from e

                if response.status_code < 500:
                    # 4xx（例如模型名稱打錯回 404）是請求本身有問題，重試一百次結果也一樣，直接放棄
                    raise LLMUnavailableError(
                        f"模型服務拒絕了請求（HTTP {response.status_code}）：{response.text[:200]}"
                    )

                # 5xx 是服務端暫時出狀況 → 重試
                last_error = LLMUnavailableError(f"模型服務回應 HTTP {response.status_code}")

            # TODO 3. 每次失敗後 sleep 1、2、4 秒…，避免對正在掛掉的服務狂轟
            if attempt < self.max_retries:  # 最後一次失敗後不用再等，直接放棄
                time.sleep(2 ** (attempt - 1))

        raise LLMUnavailableError(f"模型服務在 {self.max_retries} 次嘗試後仍然無法使用") from last_error

    def embed(self, text: str) -> list[float]:
        """回傳這段文字的向量；維度要和資料庫 Vector 欄位的維度一致。"""
        # TODO 1. 組出對應 API 的 payload，呼叫 _call_with_retry
        data = self._call_with_retry("/api/embed", {"model": self.embed_model, "input": text})

        # TODO 2. 從回應取出向量；回應格式請對照你選的模型服務文件
        # Ollama 的 /api/embed 回傳 {"embeddings": [[...]]}，外層是「每個輸入一個向量」，所以取第 0 個
        embeddings = data.get("embeddings")
        if not embeddings:
            raise LLMUnavailableError("模型服務回應缺少 embeddings 欄位")
        return embeddings[0]

    def generate(self, prompt: str) -> str:
        """回傳模型對 prompt 的完整回答文字。"""
        # TODO 1. 關閉串流（stream=False）先求簡單，之後要做打字機效果再改
        # TODO 2. 思考：temperature 要設高還是低？查資料型的問答為什麼偏好低？
        # 答：低。溫度越低輸出越穩定、越貼近給它的資料；溫度高會增加隨機性，對「照資料回答」是增加編造的風險
        data = self._call_with_retry(
            "/api/generate",
            {
                "model": self.chat_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1},
            },
        )

        answer = data.get("response")
        if answer is None:
            raise LLMUnavailableError("模型服務回應缺少 response 欄位")
        return answer.strip()
