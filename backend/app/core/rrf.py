"""
RRF（Reciprocal Rank Fusion）：把多路檢索結果融合成一份排名。
對應職缺：RAG 應用開發（混合檢索）。

為什麼用排名而不是分數融合：向量的相似度（0~1）和 BM25 分數（無上限）量綱完全不同，不能直接相加；
只看「名次」就不用處理量綱問題。
"""


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """rankings 是多份「文件編號依相關性由高到低」的清單；回傳融合後 (文件編號, RRF 分數)，由高到低。"""
    scores: dict[int, float] = {}
    first_seen: dict[int, int] = {}  # 每個文件第一次出現的先後，用來在同分時決定順序

    for ranking in rankings:
        seen_in_this_list: set[int] = set()
        for rank, doc_id in enumerate(ranking, start=1):
            # 同一份清單裡重複出現的文件只算第一次，避免重複的名次灌水
            if doc_id in seen_in_this_list:
                continue
            seen_in_this_list.add(doc_id)

            # TODO 1. 每份清單裡，名次 rank（從 1 開始）的文件得到 1 / (k + rank) 分
            # TODO 2. 同一份文件在多份清單出現就把分數加總（這就是「兩路都找得到的排前面」的原理）
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(doc_id, len(first_seen))

    # TODO 3. 最後依總分由高到低排序；分數相同時順序要可預測，想想怎麼處理
    # 答：同分時，比較早出現的文件（排在前面的清單、名次較前）排前面，同樣輸入永遠得到同樣順序
    return sorted(scores.items(), key=lambda item: (-item[1], first_seen[item[0]]))
