"""關鍵字檢索：倒排索引＋BM25。

對應職缺：RAG 應用開發；資料結構（雜湊表、堆）
規格測試：tests/spec/test_bm25.py

用途：向量檢索擅長語意相近，但條號、料號、專有名詞需要字面相符；BM25 補這一塊。

資料結構：
  postings：詞 → {文件編號: 詞頻}        （倒排索引：查詢時只走訪含有該詞的文件）
  doc_len ：文件編號 → 詞數
公式（對查詢中每個詞 t 加總）：
  idf(t) = ln((N - df + 0.5) / (df + 0.5) + 1)       越少文件出現的詞越有鑑別力
  score += idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
           k1 控制詞頻的飽和速度；b 控制長文件的懲罰程度
"""
import heapq
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Collection

_SEGMENT_RE = re.compile(r"[a-zA-Z0-9]+|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """斷詞：英數連續字串整串一個詞（轉小寫）；連續中文切成 bigram；標點與空白只當分隔。"""
    text = unicodedata.normalize("NFKC", text)     # 全形英數 → 半形，「９０」和「90」才會是同一個詞
    tokens: list[str] = []
    for segment in _SEGMENT_RE.findall(text):
        if segment.isascii():
            tokens.append(segment.lower())
        elif len(segment) == 1:
            tokens.append(segment)
        else:
            tokens.extend(segment[i:i + 2] for i in range(len(segment) - 1))
    return tokens


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.postings: dict[str, dict[int, int]] = {}
        self.doc_len: dict[int, int] = {}
        self._total_len = 0

    def __len__(self) -> int:
        return len(self.doc_len)

    def add(self, doc_id: int, text: str) -> None:
        """加入一份文件：斷詞後更新倒排索引與文件長度。"""
        if doc_id in self.doc_len:
            raise ValueError(f"doc_id {doc_id} 已在索引中")
        tokens = tokenize(text)
        self.doc_len[doc_id] = len(tokens)
        self._total_len += len(tokens)
        for term, tf in Counter(tokens).items():
            self.postings.setdefault(term, {})[doc_id] = tf

    def idf(self, term: str) -> float:
        n = len(self.doc_len)
        df = len(self.postings.get(term, ()))
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def search(self, query: str, k: int = 5, allowed: Collection[int] | None = None) -> list[tuple[int, float]]:
        """回傳分數最高的 k 筆 [(doc_id, score)]，高分在前；分數為 0 的不回傳。

        allowed：只在這些文件中計分（權限過濾），None 表示不限制。
        取前 k 名用最小堆：O(n log k)；全部排序是 O(n log n)，候選多而 k 小時差很多。
        """
        if not self.doc_len or k <= 0:
            return []
        avgdl = (self._total_len / len(self.doc_len)) or 1.0
        scores: dict[int, float] = {}
        for term in set(tokenize(query)):
            postings = self.postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            for doc_id, tf in postings.items():
                if allowed is not None and doc_id not in allowed:
                    continue
                norm = 1 - self.b + self.b * self.doc_len[doc_id] / avgdl
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return heapq.nlargest(k, ((d, s) for d, s in scores.items() if s > 0), key=lambda item: item[1])
