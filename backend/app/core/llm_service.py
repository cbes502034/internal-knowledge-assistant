"""模型服務層：所有模型呼叫的唯一入口。其他模組不直接呼叫 Ollama。

對應職缺：LLM API 串接；將生成式 AI 落地到現有系統
規格測試：tests/spec/test_llm_and_metrics.py

好處：
- 換模型只改設定（EMBED_MODEL、GEN_MODEL）；換供應商只改這個檔案
- 逾時、重試、錯誤分類集中在一處
- 測試可以用 set_llm() 整個換成假的模型，不必真的載入模型

嵌入與生成都透過本機的 Ollama：資料不離開主機，適合內部機密文件。
"""
import logging
import threading
import time
from collections.abc import Callable, Sequence

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}
_EMBED_BATCH = 32          # 一次送幾段去算向量


class LLMUnavailableError(Exception):
    """模型暫時無法使用。呼叫端只需要接這個例外，不必知道背後是哪個服務。"""


def is_transient(exc: Exception) -> bool:
    """暫時性錯誤（等一下再試可能就好）才重試；請求本身有問題的錯誤重試也沒用。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    return isinstance(exc, (ConnectionError, TimeoutError))


class LLMService:
    MAX_RETRIES = 3
    BASE_DELAY = 1.0          # 重試等待 1、2、4 秒（指數退避，避免一起擠爆剛恢復的服務）

    def __init__(self, sleep: Callable[[float], None] = time.sleep, client: httpx.Client | None = None):
        settings = get_settings()
        self.embed_model = settings.embed_model
        self.gen_model = settings.gen_model
        self.embed_dim = settings.embed_dim
        self.max_tokens = settings.gen_max_tokens
        self._sleep = sleep
        self._client = client or httpx.Client(
            base_url=settings.ollama_url,
            timeout=httpx.Timeout(settings.ollama_timeout_s, connect=5.0),
        )

    # ---------- 共用：重試與日誌 ----------
    def _call_with_retry(self, func: Callable, *, operation: str = "call", model: str = "-"):
        """執行 func；暫時性錯誤重試，最多 MAX_RETRIES 次；放棄時丟出不含內部細節的 LLMUnavailableError。"""
        started = time.monotonic()
        retries = 0
        while True:
            try:
                result = func()
            except Exception as exc:
                if not is_transient(exc) or retries >= self.MAX_RETRIES:
                    error = type(exc).__name__
                    if isinstance(exc, httpx.HTTPStatusError):
                        error += f"({exc.response.status_code})"    # 404 通常是模型名稱錯或還沒 ollama pull
                    self._log(operation, model, started, ok=False, retries=retries, error=error)
                    raise LLMUnavailableError("AI 服務暫時無法使用") from exc
                self._sleep(self.BASE_DELAY * 2 ** retries)
                retries += 1
                continue
            self._log(operation, model, started, ok=True, retries=retries)
            return result

    @staticmethod
    def _log(operation: str, model: str, started: float, *, ok: bool, retries: int, error: str = "") -> None:
        """只記操作、模型、耗時、結果、重試次數；不記提示詞與文件內容（可能含機密）。"""
        level = logging.INFO if ok else logging.WARNING
        logger.log(level, "llm_call op=%s model=%s ms=%d ok=%s retries=%d error=%s",
                   operation, model, (time.monotonic() - started) * 1000, ok, retries, error or "-")

    def _post(self, path: str, payload: dict) -> dict:
        response = self._client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    # ---------- 嵌入 ----------
    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """多段文字 → 向量（每個長度 = embed_dim），分批送出。"""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = list(texts[start:start + _EMBED_BATCH])
            data = self._call_with_retry(
                lambda: self._post("/api/embed", {"model": self.embed_model, "input": batch, "keep_alive": "30m"}),
                operation="embed", model=self.embed_model)
            got = data.get("embeddings") or []
            if len(got) != len(batch) or any(len(v) != self.embed_dim for v in got):
                logger.error("embed shape mismatch: expected %d vectors of dim %d", len(batch), self.embed_dim)
                raise LLMUnavailableError("AI 服務暫時無法使用")
            vectors.extend(got)
        return vectors

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]

    # ---------- 生成 ----------
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """提示詞 → 回答。system 放規則、prompt 放資料與問題，兩者分開比較不容易被資料裡的文字帶偏。"""
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        payload = {
            "model": self.gen_model,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.1, "num_predict": self.max_tokens},   # 低溫度：回答穩定、少發揮
        }
        data = self._call_with_retry(lambda: self._post("/api/chat", payload),
                                     operation="generate", model=self.gen_model)
        content = ((data.get("message") or {}).get("content") or "").strip()
        if not content:
            raise LLMUnavailableError("AI 服務暫時無法使用")
        return content

    # ---------- 健康檢查 ----------
    def ping(self) -> list[str]:
        """回傳 Ollama 上已下載的模型名稱；連不上會丟 LLMUnavailableError。"""
        response = self._call_with_retry(lambda: self._client.get("/api/tags", timeout=5.0),
                                         operation="ping", model="-")
        response.raise_for_status()
        return [m.get("name", "") for m in response.json().get("models", [])]


_service: LLMService | None = None
_service_lock = threading.Lock()


def get_llm() -> LLMService:
    """取得共用的模型服務（第一次用到才建立）。"""
    global _service
    with _service_lock:
        if _service is None:
            _service = LLMService()
        return _service


def set_llm(service) -> None:
    """替換模型服務；測試時換成假的，None 表示下次重新建立。"""
    global _service
    with _service_lock:
        _service = service
