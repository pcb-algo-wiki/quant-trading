"""政策对齐分数

使用 TF-IDF 字符级 bigram 余弦相似度，量化公司/行业描述与政策文本的匹配程度。
无需 LLM，全离线运行。

用法示例：
    aligner = build_aligner_from_store(conn)
    score = aligner.score("公司主营半导体设备制造，聚焦光刻机核心零部件")
    # -> float in [0, 1]
"""
from __future__ import annotations


class PolicyAligner:
    """TF-IDF 政策对齐器。

    fit() 接受政策文本列表；score() 返回 query 与政策语料的最大余弦相似度。
    语料为空时 score() 恒返回 0.0。
    """

    def __init__(self) -> None:
        self._vectorizer = None
        self._matrix = None

    def fit(self, policy_texts: list[str]) -> "PolicyAligner":
        """用政策文本列表构建 TF-IDF 矩阵。"""
        if not policy_texts:
            self._vectorizer = None
            self._matrix = None
            return self
        from sklearn.feature_extraction.text import TfidfVectorizer
        self._vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), min_df=1)
        self._matrix = self._vectorizer.fit_transform(policy_texts)
        return self

    def score(self, query_text: str) -> float:
        """返回 query_text 与政策语料的最大余弦相似度 [0, 1]。"""
        if self._vectorizer is None or self._matrix is None:
            return 0.0
        if not query_text or not query_text.strip():
            return 0.0
        from sklearn.metrics.pairwise import cosine_similarity
        q_vec = self._vectorizer.transform([query_text])
        sims = cosine_similarity(q_vec, self._matrix)
        return float(sims.max())


def build_aligner_from_store(conn) -> PolicyAligner:
    """从 policy_items 表读取全部文本并 fit PolicyAligner。"""
    rows = conn.execute(
        "SELECT title, content FROM policy_items WHERE content IS NOT NULL"
    ).fetchall()
    texts = [f"{r[0]} {r[1]}" for r in rows]
    return PolicyAligner().fit(texts)


def compute_policy_scores(
    conn,
    symbol_desc: dict[str, str],
) -> dict[str, float]:
    """批量计算每个 symbol 的政策对齐分数。

    Args:
        conn: SQLite 连接（已含 policy_items）
        symbol_desc: {symbol: 业务描述文本}

    Returns:
        {symbol: policy_score}（float [0, 1]）
    """
    aligner = build_aligner_from_store(conn)
    return {sym: aligner.score(desc) for sym, desc in symbol_desc.items()}
