"""RRF（Reciprocal Rank Fusion）：把多份排名合成一份。

對應職缺：RAG 應用開發
規格測試：tests/spec/test_rrf.py

用途：向量檢索與 BM25 的分數尺度不同，不能直接相加；RRF 只看名次。
公式：score(d) = Σ 1 / (k + 名次)，名次從 1 起算，k 預設 60。
"""


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """TODO：融合多份排名。

    rankings：每份是由高到低的編號清單，例如 [[3, 1, 2], [1, 4]]
    回傳：[(編號, 分數)]，分數高的在前；分數相同時編號小的在前
    """
    raise NotImplementedError("core.rrf.rrf_fuse 尚未實作")
