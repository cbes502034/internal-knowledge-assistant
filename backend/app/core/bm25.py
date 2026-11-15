"""
BM25 關鍵字檢索（自己實作，不用現成套件）。
對應職缺：RAG 應用開發（混合檢索的「關鍵字」那一半）；順便練到倒排索引、堆積（heap）等資料結構。

為什麼需要它：向量檢索擅長「意思相近」，但對條號、專有名詞、型號這種「字面一定要對」的查詢會失準，
BM25 剛好補上這塊。

套件提示：collections（Counter / defaultdict）、math（log）、heapq（取前 k 名）。
"""


def tokenize(text: str) -> list[str]:
    """中文沒有空白可切，改用 bigram（相鄰兩字一組）；英文數字則整串視為一個詞。"""
    # TODO 1. 先決定怎麼處理標點與空白（建議直接丟掉）
    # TODO 2. 連續的中文字取 bigram，例如「廢溶劑」→ ['廢溶', '溶劑']；單獨一個字時怎麼辦？
    # TODO 3. 連續的英數字母（如 'SOP-OPS-004'）想想要整串保留還是再拆
    raise NotImplementedError("TODO: tokenize")


class BM25Index:
    """對一批文件建立倒排索引並計算 BM25 分數。"""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        """docs 是每個 chunk 的文字；k1 控制詞頻飽和度，b 控制文件長度懲罰。"""
        # TODO 1. 對每份文件 tokenize，記下文件長度與整批的平均長度
        # TODO 2. 建倒排索引：詞 -> [(文件編號, 該詞在該文件出現次數), ...]
        # TODO 3. 算每個詞的 IDF（出現在越少文件裡越稀有、權重越高），先查 BM25 的 IDF 公式
        raise NotImplementedError("TODO: BM25Index.__init__")

    def search(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        """回傳分數最高的 k 筆 (文件編號, 分數)，由高到低排列；分數為 0 的不要回傳。"""
        # TODO 1. 對 query tokenize，只需要掃「查詢詞」的倒排列表，不要掃全部文件
        # TODO 2. 累加每份文件的 BM25 分數
        # TODO 3. 取前 k 名：用 heapq.nlargest 而不是整批排序，想想時間複雜度差在哪
        raise NotImplementedError("TODO: BM25Index.search")
