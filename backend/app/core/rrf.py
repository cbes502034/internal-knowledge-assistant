"""
RRF（Reciprocal Rank Fusion）：把多路檢索結果融合成一份排名。
對應職缺：RAG 應用開發（混合檢索）。

為什麼用排名而不是分數融合：向量的相似度（0~1）和 BM25 分數（無上限）量綱完全不同，不能直接相加；
只看「名次」就不用處理量綱問題。
"""


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """rankings 是多份「文件編號依相關性由高到低」的清單；回傳融合後 (文件編號, RRF 分數)，由高到低。"""
    # TODO 1. 每份清單裡，名次 rank（從 1 開始）的文件得到 1 / (k + rank) 分
    # TODO 2. 同一份文件在多份清單出現就把分數加總（這就是「兩路都找得到的排前面」的原理）
    # TODO 3. 最後依總分由高到低排序；分數相同時順序要可預測，想想怎麼處理
    raise NotImplementedError("TODO: rrf_fuse")
