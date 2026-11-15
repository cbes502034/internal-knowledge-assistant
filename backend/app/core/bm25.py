"""
BM25 關鍵字檢索（自己實作，不用現成套件）。
對應職缺：RAG 應用開發（混合檢索的「關鍵字」那一半）；順便練到倒排索引、堆積（heap）等資料結構。

為什麼需要它：向量檢索擅長「意思相近」，但對條號、專有名詞、型號這種「字面一定要對」的查詢會失準，
BM25 剛好補上這塊。

套件提示：collections（Counter / defaultdict）、math（log）、heapq（取前 k 名）。
"""

import heapq
import math
import re
import unicodedata
from collections import Counter, defaultdict

# 一次抓出「連續的中文字」或「連續的英數字」，其餘（標點、空白）自然就被丟掉
_TOKEN_RUN = re.compile(r"[一-鿿]+|[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """中文沒有空白可切，改用 bigram（相鄰兩字一組）；英文數字則整串視為一個詞。"""
    # TODO 1. 先決定怎麼處理標點與空白（建議直接丟掉）
    # 答：正規表達式只挑中文與英數，標點空白不會進來；先做 NFKC 正規化把全形英數轉半形，並統一小寫
    text = unicodedata.normalize("NFKC", text).lower()

    tokens: list[str] = []
    for run in _TOKEN_RUN.findall(text):
        if "一" <= run[0] <= "鿿":
            # TODO 2. 連續的中文字取 bigram，例如「廢溶劑」→ ['廢溶', '溶劑']；單獨一個字時怎麼辦？
            # 答：只有一個字就沒辦法組 bigram，直接把那個字當 token，不然這個字會完全消失
            if len(run) == 1:
                tokens.append(run)
            else:
                tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        else:
            # TODO 3. 連續的英數字母（如 'SOP-OPS-004'）想想要整串保留還是再拆
            # 答：「連續」的英數字整串保留成一個 token；連字號會把它切開，所以 SOP-OPS-004 會是 sop / ops / 004，
            #     查詢與文件用同一套切法，所以查 'SOP-OPS-004' 或只查 '004' 都找得到
            tokens.append(run)

    return tokens


class BM25Index:
    """對一批文件建立倒排索引並計算 BM25 分數。"""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        """docs 是每個 chunk 的文字；k1 控制詞頻飽和度，b 控制文件長度懲罰。"""
        self.k1 = k1
        self.b = b

        # TODO 1. 對每份文件 tokenize，記下文件長度與整批的平均長度
        tokenized = [tokenize(doc) for doc in docs]
        self.doc_len = [len(tokens) for tokens in tokenized]
        self.avgdl = sum(self.doc_len) / len(docs) if docs else 0.0

        # TODO 2. 建倒排索引：詞 -> [(文件編號, 該詞在該文件出現次數), ...]
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for doc_id, tokens in enumerate(tokenized):
            for term, tf in Counter(tokens).items():
                postings[term].append((doc_id, tf))
        self.postings = dict(postings)  # 轉成一般 dict，之後查不存在的詞不會意外新增項目

        # TODO 3. 算每個詞的 IDF（出現在越少文件裡越稀有、權重越高），先查 BM25 的 IDF 公式
        # 用 log(1 + (N - df + 0.5) / (df + 0.5))：加 1 讓 IDF 永遠為正，
        # 否則「幾乎每份文件都有」的詞會出現負分，把相關文件的分數往下拉
        n = len(docs)
        self.idf = {
            term: math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
            for term, plist in self.postings.items()
        }

    def search(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        """回傳分數最高的 k 筆 (文件編號, 分數)，由高到低排列；分數為 0 的不要回傳。"""
        if k <= 0:
            return []

        # TODO 1. 對 query tokenize，只需要掃「查詢詞」的倒排列表，不要掃全部文件
        # TODO 2. 累加每份文件的 BM25 分數
        # 查詢詞去重：同一個詞在查詢裡重複出現，不該讓分數無意義地膨脹
        scores: dict[int, float] = defaultdict(float)
        for term in set(tokenize(query)):
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = self.idf[term]
            for doc_id, tf in plist:
                # 長度正規化：文件越長，同樣的詞頻越不值錢
                norm = 1 - self.b + self.b * self.doc_len[doc_id] / self.avgdl
                scores[doc_id] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)

        # TODO 3. 取前 k 名：用 heapq.nlargest 而不是整批排序，想想時間複雜度差在哪
        # 答：整批排序是 O(n log n)；nlargest 維護大小為 k 的堆，是 O(n log k)，k 遠小於 n 時差很多
        # key 第二項用 -doc_id：分數相同時編號小的排前面，結果才可重現
        # 只有「至少命中一個查詢詞」的文件會進 scores，所以不會出現分數為 0 的結果
        return heapq.nlargest(k, scores.items(), key=lambda item: (item[1], -item[0]))
