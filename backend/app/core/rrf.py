"""RRF（Reciprocal Rank Fusion）：把多份排名合成一份。

對應職缺：RAG 應用開發
規格測試：tests/spec/test_algorithms.py

用途：向量相似度（0–1）和 BM25 分數（沒有上限）尺度不同，不能直接相加；RRF 只看名次。
公式：score(d) = Σ weight_i / (k + 名次_i)，名次從 1 起算。
k 越大，第 1 名和第 10 名的差距越小；60 是原始論文的建議值。
兩份排名都出現的項目會累積兩次分數，所以「兩種方法都認為相關」的段落會排在前面。
weights 讓某一份排名的影響力小一點：本專案的評測顯示，等權重時 BM25 的雜訊會把正確條文擠出前幾名，
關鍵字權重降到 0.3 後 Hit@3 回到 100%（見 README「評測結果」）。
"""


def rrf_fuse(rankings: list[list[int]], k: int = 60,
             weights: list[float] | None = None) -> list[tuple[int, float]]:
    """回傳 [(編號, 分數)]，分數高的在前；分數相同時編號小的在前，讓結果可重現。"""
    weights = weights if weights is not None else [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("weights 的數量要和 rankings 相同")
    scores: dict[int, float] = {}
    for weight, ranking in zip(weights, rankings):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
