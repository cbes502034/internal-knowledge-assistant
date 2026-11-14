"""關鍵字檢索：倒排索引＋BM25。

對應職缺：RAG 應用開發；資料結構（雜湊表、堆）
規格測試：tests/spec/test_bm25.py

用途：向量檢索擅長語意相近，但條號、料號、專有名詞需要字面相符；BM25 補這一塊。

資料結構：
  postings：詞 → {文件編號: 詞頻}        （倒排索引）
  doc_len ：文件編號 → 詞數
公式（對查詢中每個詞 t 加總）：
  idf(t) = ln((N - df + 0.5) / (df + 0.5) + 1)
  score += idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))
"""


def tokenize(text: str) -> list[str]:
    """TODO：斷詞。

    - 英數連續字串整串當一個詞，轉小寫（SOP → sop、90 → 90）
    - 連續中文字切成 bigram（廢溶劑 → 廢溶、溶劑）；單獨一個中文字就是它自己
    - 標點與空白只當分隔
    """
    raise NotImplementedError("core.bm25.tokenize 尚未實作")


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """TODO：初始化 k1、b、postings、doc_len。"""
        raise NotImplementedError("core.bm25.BM25Index.__init__ 尚未實作")

    def add(self, doc_id: int, text: str) -> None:
        """TODO：加入一份文件。同一個 doc_id 加入兩次 → raise ValueError。"""
        raise NotImplementedError("core.bm25.BM25Index.add 尚未實作")

    def search(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        """TODO：回傳分數最高的 k 筆 [(doc_id, score)]，高分在前；分數為 0 的不回傳。

        - 只走訪含有查詢詞的文件
        - 取前 k 名用最小堆（O(n log k)），不要全部排序
        """
        raise NotImplementedError("core.bm25.BM25Index.search 尚未實作")
