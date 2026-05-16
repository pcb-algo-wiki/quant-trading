"""
knowledge.vector_store
=====================
轻量向量检索：TF-IDF + TruncatedSVD 代替 sentence-transformers。
不依赖外部模型下载，sklearn 内置算法完全离线可用。

Phase 7 实装路线：
1. TfidfVectorizer 提取文本特征（词袋 + n-gram）
2. TruncatedSVD 降维到 128 维（潜在语义分析）
3. 余弦相似度检索

为什么不用 sentence-transformers：
- 需要连接 huggingface.co 下载模型，当前网络不通
- 后续网络恢复时，只需改一行 MODEL_NAME 切换到真实语义向量
"""
from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize


@dataclass
class VectorHit:
    doc_id: str
    score: float
    text: str
    source: str = "vector"
    extra: dict = field(default_factory=dict)


def tokenize_chinese(text: str) -> list[str]:
    """中英文混合分词：英文按词切分，中文用 jieba。"""
    import re
    import jieba
    # 英文连续字母/数字视为独立token
    tokens = re.findall(r'[a-zA-Z0-9_.%]+|[\u4e00-\u9fff]+', text)
    result = []
    for t in tokens:
        if re.match(r'^[a-zA-Z0-9_.%]+$', t):
            result.append(t.lower())
        else:
            result.extend(w.lower() for w in jieba.cut(t))
    return [w for w in result if w.strip()]


class VectorStore:
    """
    TF-IDF + SVD 向量检索。

    初始化后可反复调用 index() 添加文档，search() 检索。
    文档以 doc_id 为唯一键，重复添加会覆盖。
    """

    def __init__(
        self,
        n_components: int = 128,
        ngram_range: tuple[int, int] = (1, 2),
        min_df: int = 1,
        max_features: int = 10_000,
        vectorizer: Optional[TfidfVectorizer] = None,
    ) -> None:
        self.n_components = n_components
        self.ngram_range = ngram_range
        self.min_df = min_df
        self.max_features = max_features

        # 文档存储
        self._texts: dict[str, str] = {}   # doc_id → text
        self._extras: dict[str, dict] = {}  # doc_id → extra metadata

        # 向量组件（fit 后初始化）
        self._vectorizer: Optional[TfidfVectorizer] = vectorizer
        self._svd: Optional[TruncatedSVD] = None
        self._vectors: Optional[np.ndarray] = None  # shape (N, n_components)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index(self, doc_id: str, text: str, **kwargs) -> None:
        """添加或更新一个文档。"""
        self._texts[doc_id] = text
        if kwargs:
            self._extras[doc_id] = kwargs

    def build_index(self) -> None:
        """用当前所有文档构建向量索引。调用时机：批量添加文档后。"""
        if len(self._texts) < 2:
            self._vectors = None
            return

        texts = [self._texts[did] for did in self._texts]
        doc_ids = list(self._texts.keys())

        # TF-IDF
        self._vectorizer = TfidfVectorizer(
            tokenizer=tokenize_chinese,
            ngram_range=self.ngram_range,
            min_df=self.min_df,
            max_features=self.max_features,
            sublinear_tf=True,
        )
        tfidf = self._vectorizer.fit_transform(texts)  # (N, vocab_size)

        # SVD 降维
        n_comp = min(self.n_components, len(texts) - 1, tfidf.shape[1])
        self._svd = TruncatedSVD(n_components=n_comp, random_state=42)
        vectors = self._svd.fit_transform(tfidf)       # (N, n_comp)

        # L2 归一化（余弦相似度 = 点积）
        self._vectors = normalize(vectors, axis=1).astype(np.float32)

    def search(self, query: str, top_k: int = 10) -> list[VectorHit]:
        """检索 top_k 相关文档。"""
        if self._vectors is None or self._vectorizer is None:
            return []

        try:
            q_tfidf = self._vectorizer.transform([query])
            q_vec = self._svd.transform(q_tfidf).astype(np.float32)
            q_vec = normalize(q_vec, axis=1)
        except Exception:
            return []

        # 余弦相似度
        scores = np.dot(self._vectors, q_vec.T).flatten()
        top_indices = np.argsort(scores)[::-1][:top_k]

        hits = []
        doc_ids = list(self._texts.keys())
        for idx in top_indices:
            if scores[idx] <= 0:
                break
            did = doc_ids[idx]
            hits.append(VectorHit(
                doc_id=did,
                score=float(scores[idx]),
                text=self._texts[did][:500],  # 截断避免过大
                source="vector",
                extra=self._extras.get(did, {}),
            ))
        return hits

    def save(self, path: str | Path) -> None:
        """持久化到文件（numpy npz）。"""
        path = Path(path)
        np.savez(
            path,
            vectors=self._vectors,
            doc_ids=list(self._texts.keys()),
            svd_components=self._svd.components_ if self._svd else None,
            svd_explained_variance=self._svd.explained_variance_ratio_ if self._svd else None,
        )
        # 文本单独存 json
        text_path = path.with_suffix(".texts.json")
        with open(text_path, "w", encoding="utf-8") as f:
            json.dump(self._texts, f, ensure_ascii=False)
        extra_path = path.with_suffix(".extras.json")
        with open(extra_path, "w", encoding="utf-8") as f:
            json.dump(self._extras, f, ensure_ascii=False)

    def load(self, path: str | Path) -> None:
        """从文件加载。vectorizer 需要重新 fit（用保存的 vocab）。"""
        path = Path(path)
        data = np.load(path)
        self._vectors = data["vectors"]
        self._texts = json.loads(open(path.with_suffix(".texts.json")).read())
        self._extras = json.loads(open(path.with_suffix(".extras.json")).read())

        # vectorizer 不能序列化，重新 fit（用现有文本重新构建）
        # 注意：每次 load 后需要先有 vectorizer 状态才能 search
        self._vectorizer = None  # search 时会报错，调用者需确保 build_index


# ------------------------------------------------------------------
# Phase 7 占位符 → 真实 VectorRetriever
# ------------------------------------------------------------------


class VectorRetriever:
    """
    实现 HybridRetriever 所需的 VectorRetriever 接口。
    底层使用 VectorStore（TF-IDF + SVD）。

    使用方式（后续 sentence-transformers 可用时替换 build() 方法）：
        store = VectorStore()
        for item in news_items:
            store.index(item.id, item.title + " " + (item.content or ""))
        store.build_index()
        retriever = VectorRetriever(store)
        hits = retriever.search("GPU 供应链", top_k=5)
    """

    def __init__(self, store: Optional[VectorStore] = None) -> None:
        self._store = store or VectorStore()

    def search(self, query: str, top_k: int = 10) -> list:
        """返回 Hit 列表（适配 HybridRetriever）。"""
        hits = self._store.search(query, top_k=top_k)
        # 转换为 knowledge/retrieval.py 的 Hit 格式
        from knowledge.retrieval import Hit
        return [
            Hit(
                doc_id=h.doc_id,
                score=h.score,
                source="vector",
                evidence_chain=[f"vector:{h.doc_id}"],
                extra=h.extra,
            )
            for h in hits
        ]


def build_news_vector_store() -> VectorStore:
    """从 SQLite news_items 构建向量库。"""
    from data_store.db import get_connection

    store = VectorStore(n_components=128)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rowid, title, COALESCE(content, '') FROM news_items ORDER BY published_at DESC LIMIT 500"
        ).fetchall()
        for row in rows:
            doc_id, title, content = row
            text = f"{title} {content}".strip()
            if text:
                store.index(str(doc_id), text, title=title)

    store.build_index()
    return store
