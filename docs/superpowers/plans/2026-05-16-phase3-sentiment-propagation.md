# Phase 3 政策挖掘与情感传导 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 `policy_items` + `news_items` 通过 TF-IDF 政策对齐 + SnowNLP 情感 + IndustryGraph BFS 衰减传播，输出结构化分数到 `industry_events`。

**架构：** `data/policy/` 负责政策文本摄取，`research/sentiment.py` 提供可热换的情感后端，`research/policy_alignment.py` 做 TF-IDF 余弦打分，`research/propagation.py` 在 `IndustryGraph` 上 BFS 衰减传播，最终分数写入 `industry_events` 的三个新列。

**技术栈：** Python 3.10+、SnowNLP、scikit-learn（TfidfVectorizer）、NetworkX（已有）、SQLite（已有）

---

## 文件结构

| 操作 | 文件 | 职责 |
|---|---|---|
| 创建 | `data/policy/__init__.py` | 包入口 |
| 创建 | `data/policy/fifteenth_five_year.py` | 政策文本抓取 + 幂等写入 `policy_items` |
| 创建 | `data/cache/policy_seed.json` | 离线种子数据（5条政策摘要）|
| 创建 | `research/sentiment.py` | `SentimentBackend` 抽象 + `SnowNLPBackend` 实现 |
| 创建 | `research/policy_alignment.py` | `PolicyAligner`：TF-IDF fit/score |
| 创建 | `research/propagation.py` | `propagate_scores` + `upsert_event_scores` |
| 修改 | `data_store/schema.py` | 添加 `MIGRATION_STATEMENTS` + `apply_migrations()` |
| 修改 | `data_store/db.py` | `get_connection()` 中调用 `apply_migrations()` |
| 修改 | `config.yaml` | 新增 `sentiment:` + `policy:` 段 |
| 修改 | `scripts/daily_pipeline.py` | 追加 `sentiment.enabled` feature flag |
| 修改 | `requirements.txt` | 添加 `snownlp` + `scikit-learn` |
| 创建 | `scripts/run_sentiment_replay.py` | 历史新闻重放入口 |
| 创建 | `tests/test_phase3_sentiment.py` | ≥16 用例 |

---

## 任务 1：Schema 迁移 + 依赖补充

**文件：**
- 修改：`data_store/schema.py`
- 修改：`data_store/db.py`
- 修改：`requirements.txt`
- 测试：`tests/test_phase3_sentiment.py`（第一批 2 个用例）

- [ ] **步骤 1：在 `requirements.txt` 末尾追加两行**

```text
snownlp>=0.12.3
scikit-learn>=1.3.0
```

（在现有 `pdfplumber>=0.10.0` 之后追加）

- [ ] **步骤 2：在 `data_store/schema.py` 末尾追加迁移逻辑**

在现有 `create_schema` 函数之后追加：

```python
# Phase 3 — industry_events 列迁移（幂等：PRAGMA 检查后才执行 ALTER TABLE）
MIGRATION_STATEMENTS = [
    ("policy_score",     "ALTER TABLE industry_events ADD COLUMN policy_score REAL;"),
    ("sentiment_score",  "ALTER TABLE industry_events ADD COLUMN sentiment_score REAL;"),
    ("propagated_score", "ALTER TABLE industry_events ADD COLUMN propagated_score REAL;"),
]


def apply_migrations(conn: sqlite3.Connection) -> None:
    """幂等追加新列——若列已存在则跳过（SQLite 重复 ADD COLUMN 会报 OperationalError）。"""
    cursor = conn.execute("PRAGMA table_info(industry_events)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    for col_name, stmt in MIGRATION_STATEMENTS:
        if col_name not in existing_cols:
            conn.execute(stmt)
    conn.commit()
```

- [ ] **步骤 3：在 `data_store/db.py` 中引入并调用 `apply_migrations`**

修改 import 行：
```python
from data_store.schema import create_schema, apply_migrations
```

在 `get_connection()` 中的 `create_schema(conn)` 之后加一行：
```python
    create_schema(conn)
    apply_migrations(conn)   # Phase 3: 追加 industry_events 新列
```

- [ ] **步骤 4：写失败测试（schema 迁移）**

在新文件 `tests/test_phase3_sentiment.py` 中写：

```python
"""Phase 3 政策挖掘与情感传导测试"""
from __future__ import annotations

import sqlite3
import pytest


# ── 任务 1：Schema 迁移 ──────────────────────────────────────────────────────

def test_migration_adds_columns(tmp_path):
    """apply_migrations 在 industry_events 上追加 3 列"""
    from data_store.schema import create_schema, apply_migrations

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    create_schema(conn)
    apply_migrations(conn)

    cursor = conn.execute("PRAGMA table_info(industry_events)")
    cols = {row[1] for row in cursor.fetchall()}
    assert "policy_score" in cols
    assert "sentiment_score" in cols
    assert "propagated_score" in cols
    conn.close()


def test_migration_is_idempotent(tmp_path):
    """apply_migrations 二次调用不报错，列数不变"""
    from data_store.schema import create_schema, apply_migrations

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    create_schema(conn)
    apply_migrations(conn)
    apply_migrations(conn)  # 第二次调用应静默成功

    cursor = conn.execute("PRAGMA table_info(industry_events)")
    cols = [row[1] for row in cursor.fetchall()]
    # policy_score 只出现一次
    assert cols.count("policy_score") == 1
    conn.close()
```

- [ ] **步骤 5：运行测试验证失败（预期 ImportError）**

```
python -m pytest tests/test_phase3_sentiment.py::test_migration_adds_columns -v
```
预期：FAIL，`cannot import name 'apply_migrations' from 'data_store.schema'`

- [ ] **步骤 6：运行测试验证通过**

```
python -m pytest tests/test_phase3_sentiment.py::test_migration_adds_columns tests/test_phase3_sentiment.py::test_migration_is_idempotent -v
```
预期：2 passed

- [ ] **步骤 7：Commit**

```bash
git add data_store/schema.py data_store/db.py requirements.txt tests/test_phase3_sentiment.py
git commit -m "feat(phase3): schema migration for industry_events + snownlp dep"
```

---

## 任务 2：政策文本摄取 `data/policy/fifteenth_five_year.py`

**文件：**
- 创建：`data/policy/__init__.py`
- 创建：`data/policy/fifteenth_five_year.py`
- 创建：`data/cache/policy_seed.json`
- 测试：`tests/test_phase3_sentiment.py`（追加 3 个用例）

- [ ] **步骤 1：创建种子文件 `data/cache/policy_seed.json`**

```json
[
  {
    "title": "国家\"十五五\"规划纲要（草案）摘要",
    "content": "加快发展新质生产力，推动先进制造业与现代服务业深度融合，培育壮大战略性新兴产业，超前布局未来产业。支持专精特新企业发展，提升产业链供应链韧性。",
    "url": "https://www.gov.cn/",
    "published_at": "2026-03-01",
    "source": "gov_seed"
  },
  {
    "title": "2025年产业政策重点方向",
    "content": "深入实施制造强国战略，推进新型工业化，发展绿色低碳产业，加大对半导体、人工智能、生物医药领域支持力度。推动数字经济与实体经济深度融合。",
    "url": "https://www.miit.gov.cn/",
    "published_at": "2025-01-15",
    "source": "gov_seed"
  },
  {
    "title": "碳达峰碳中和行动方案要点",
    "content": "加快能源结构调整，大力发展光伏、风电等可再生能源。积极推动新能源汽车和储能产业发展。支持碳捕捉利用封存技术研发。",
    "url": "https://www.ndrc.gov.cn/",
    "published_at": "2025-06-01",
    "source": "gov_seed"
  },
  {
    "title": "专精特新\"小巨人\"企业认定管理办法",
    "content": "聚焦主业、精耕细作，在细分市场占有率居国内前列，研发投入强度不低于3%，拥有核心技术和知识产权。",
    "url": "https://www.miit.gov.cn/",
    "published_at": "2024-09-10",
    "source": "gov_seed"
  },
  {
    "title": "人工智能产业发展三年行动计划",
    "content": "到2027年，人工智能核心产业规模超过1万亿元。推动大模型、具身智能等前沿技术产业化，加强算力基础设施建设，鼓励AI+制造、AI+医疗、AI+教育等场景应用。",
    "url": "https://www.gov.cn/",
    "published_at": "2025-03-20",
    "source": "gov_seed"
  }
]
```

- [ ] **步骤 2：创建 `data/policy/__init__.py`（空文件）**

```python
```

- [ ] **步骤 3：创建 `data/policy/fifteenth_five_year.py`**

```python
"""政策文本摄取

策略：
1. 优先调用 AkShare（如支持政策类接口则用，否则跳过）
2. 网络失败时从 data/cache/policy_seed.json 加载种子数据
3. 写入 policy_items（幂等：content_hash UNIQUE）
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

SEED_PATH = Path(__file__).parent.parent / "cache" / "policy_seed.json"
CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def _hash_content(title: str, content: str) -> str:
    return hashlib.md5(f"{title}{content}".encode("utf-8")).hexdigest()


def fetch_policy_articles(
    keywords: Optional[list[str]] = None,
    source: str = "gov_seed",
    max_items: int = 100,
) -> list[dict]:
    """抓取政策文章列表；网络失败时降级到 SEED_PATH。

    Returns:
        list of {title, content, url, published_at, content_hash, source}
    """
    articles: list[dict] = []

    # 尝试 AkShare（目前无稳定政策接口，直接降级）
    articles = _try_akshare(keywords or [], max_items)

    if not articles:
        articles = _load_seed()

    if keywords:
        articles = [
            a for a in articles
            if any(kw in (a.get("title", "") + a.get("content", "")) for kw in keywords)
        ] or articles  # 无匹配时返回全量种子

    for a in articles:
        a.setdefault("content_hash", _hash_content(a.get("title", ""), a.get("content", "")))
        a.setdefault("source", source)

    return articles[:max_items]


def _try_akshare(keywords: list[str], max_items: int) -> list[dict]:
    """尝试通过 AkShare 获取政策相关文章；任何异常返回空列表。"""
    try:
        import akshare as ak
        # akshare 目前无专用政策接口，使用宏观新闻接口兜底
        df = ak.stock_news_em(symbol="全部")
        if df is None or df.empty:
            return []
        rows = []
        for _, row in df.head(max_items).iterrows():
            title = str(row.get("新闻标题", row.get("title", "")))
            content = str(row.get("新闻内容", row.get("content", "")))
            if not title:
                continue
            if keywords and not any(kw in title + content for kw in keywords):
                continue
            rows.append({
                "title": title,
                "content": content,
                "url": str(row.get("新闻链接", row.get("url", ""))),
                "published_at": str(row.get("发布时间", row.get("published_at", ""))),
                "source": "akshare_news",
                "content_hash": _hash_content(title, content),
            })
        return rows
    except Exception as e:
        print(f"[policy] AkShare 获取失败（降级到种子数据）: {e}")
        return []


def _load_seed() -> list[dict]:
    """加载本地种子政策数据。"""
    if not SEED_PATH.exists():
        return []
    try:
        with open(SEED_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[policy] 种子数据加载失败: {e}")
        return []


def ingest_policy_articles(conn, articles: list[dict]) -> dict:
    """幂等写入 policy_items，以 (source, content_hash) 唯一。

    Returns:
        {"inserted": int, "skipped": int}
    """
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    inserted = skipped = 0
    for a in articles:
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO policy_items
                    (source, title, published_at, url, content, content_hash, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    a.get("source", "unknown"),
                    a.get("title", ""),
                    a.get("published_at", ""),
                    a.get("url", ""),
                    a.get("content", ""),
                    a.get("content_hash", _hash_content(a.get("title", ""), a.get("content", ""))),
                    now,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"[policy] ingest 失败: {e}")
    conn.commit()
    return {"inserted": inserted, "skipped": skipped}
```

- [ ] **步骤 4：写 3 个失败测试**

在 `tests/test_phase3_sentiment.py` 中追加：

```python
# ── 任务 2：政策摄取 ──────────────────────────────────────────────────────────

def test_policy_fetch_fallback_to_seed():
    """AkShare 失败时降级到种子数据，返回非空列表"""
    from data.policy.fifteenth_five_year import fetch_policy_articles
    from unittest.mock import patch

    with patch("data.policy.fifteenth_five_year._try_akshare", return_value=[]):
        result = fetch_policy_articles()
    assert isinstance(result, list)
    assert len(result) >= 1
    assert "title" in result[0]


def test_policy_ingest_idempotent(tmp_path):
    """重复摄取同一条政策，只插入一次"""
    import sqlite3
    from data_store.schema import create_schema, apply_migrations
    from data.policy.fifteenth_five_year import ingest_policy_articles

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    apply_migrations(conn)

    articles = [{"title": "测试政策", "content": "内容", "url": "", "published_at": "2026-01-01", "source": "test", "content_hash": "abc123"}]
    r1 = ingest_policy_articles(conn, articles)
    r2 = ingest_policy_articles(conn, articles)

    assert r1["inserted"] == 1
    assert r2["inserted"] == 0 and r2["skipped"] == 1
    conn.close()


def test_policy_keyword_filter():
    """keyword 过滤：只返回包含关键词的文章"""
    from data.policy.fifteenth_five_year import fetch_policy_articles
    from unittest.mock import patch

    seed = [
        {"title": "新能源政策", "content": "光伏发展", "url": "", "published_at": "2026-01-01", "source": "s"},
        {"title": "金融监管", "content": "银行规定", "url": "", "published_at": "2026-01-01", "source": "s"},
    ]
    with patch("data.policy.fifteenth_five_year._try_akshare", return_value=[]):
        with patch("data.policy.fifteenth_five_year._load_seed", return_value=seed):
            result = fetch_policy_articles(keywords=["新能源"])
    # 匹配到 1 条
    assert any("新能源" in a["title"] for a in result)
```

- [ ] **步骤 5：运行测试验证通过**

```
python -m pytest tests/test_phase3_sentiment.py::test_policy_fetch_fallback_to_seed tests/test_phase3_sentiment.py::test_policy_ingest_idempotent tests/test_phase3_sentiment.py::test_policy_keyword_filter -v
```
预期：3 passed

- [ ] **步骤 6：Commit**

```bash
git add data/policy/__init__.py data/policy/fifteenth_five_year.py data/cache/policy_seed.json tests/test_phase3_sentiment.py
git commit -m "feat(phase3): policy ingestion with AkShare fallback + seed data"
```

---

## 任务 3：情感分析 `research/sentiment.py`

**文件：**
- 创建：`research/sentiment.py`
- 测试：`tests/test_phase3_sentiment.py`（追加 4 个用例）

- [ ] **步骤 1：创建 `research/sentiment.py`**

```python
"""情感分析后端

架构：
- SentimentBackend：抽象接口，analyze(text) -> float [-1, 1]
- SnowNLPBackend：SnowNLP 基线 × 2 − 1 + 金融词典加权（上下限 ±0.3）
- get_default_backend()：读 config sentiment.backend，默认 snownlp

Phase 7 升级路径：实现 FinBERTBackend(SentimentBackend) 替换即可。
"""
from __future__ import annotations


DEFAULT_POS_TERMS = [
    "利好", "涨停", "超预期", "业绩增长", "订单", "扩产", "中标",
    "突破", "创新高", "增持", "回购", "分红",
]
DEFAULT_NEG_TERMS = [
    "利空", "下跌", "亏损", "违规", "诉讼", "暂停", "减值",
    "业绩下滑", "亏损扩大", "被查", "退市", "降级",
]


class SentimentBackend:
    """情感分析抽象基类。子类必须实现 analyze()。"""

    def analyze(self, text: str) -> float:
        """返回情感分数，范围 [-1, 1]。正面 > 0，负面 < 0，中性 ≈ 0。"""
        raise NotImplementedError


class SnowNLPBackend(SentimentBackend):
    """SnowNLP 基线 + 金融词典加权。

    SnowNLP.sentiments 输出 [0, 1]，× 2 − 1 → [-1, 1]。
    然后加词典 boost（每个词 ±0.1，上限各 ±0.3）。
    最终 clamp 到 [-1, 1]。
    """

    def __init__(
        self,
        pos_terms: list[str] | None = None,
        neg_terms: list[str] | None = None,
    ) -> None:
        self.pos_terms = pos_terms if pos_terms is not None else DEFAULT_POS_TERMS
        self.neg_terms = neg_terms if neg_terms is not None else DEFAULT_NEG_TERMS

    def analyze(self, text: str) -> float:
        if not text or not text.strip():
            return 0.0
        try:
            from snownlp import SnowNLP
            raw = SnowNLP(text).sentiments  # [0, 1]
            score = raw * 2.0 - 1.0         # [-1, 1]
        except Exception:
            score = 0.0

        pos_count = sum(1 for t in self.pos_terms if t in text)
        neg_count = sum(1 for t in self.neg_terms if t in text)
        boost = min(0.3, pos_count * 0.1) - min(0.3, neg_count * 0.1)

        return max(-1.0, min(1.0, score + boost))


def get_default_backend() -> SentimentBackend:
    """根据 config.yaml sentiment.backend 返回对应后端。默认 SnowNLPBackend。"""
    try:
        from utils.config import get_config
        cfg = get_config()
        backend_name = cfg.get("sentiment.backend", "snownlp")
    except Exception:
        backend_name = "snownlp"

    if backend_name == "snownlp":
        return SnowNLPBackend()
    # Phase 7: elif backend_name == "finbert": return FinBERTBackend()
    return SnowNLPBackend()
```

- [ ] **步骤 2：写 4 个失败测试**

在 `tests/test_phase3_sentiment.py` 中追加：

```python
# ── 任务 3：情感分析 ──────────────────────────────────────────────────────────

def test_sentiment_positive_text():
    """明确利好文本的 analyze 结果 > 0"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend()
    score = backend.analyze("公司业绩超预期大幅增长，股价涨停，订单大量增加")
    assert score > 0, f"expected > 0, got {score}"


def test_sentiment_negative_text():
    """明确利空文本的 analyze 结果 < 0"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend()
    score = backend.analyze("公司因违规被调查，业绩亏损扩大，面临退市风险")
    assert score < 0, f"expected < 0, got {score}"


def test_sentiment_empty_text():
    """空文本返回 0.0"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend()
    assert backend.analyze("") == 0.0
    assert backend.analyze("   ") == 0.0


def test_sentiment_clamp_in_range():
    """analyze 结果始终在 [-1, 1] 范围内"""
    from research.sentiment import SnowNLPBackend
    backend = SnowNLPBackend(
        pos_terms=["涨涨涨"] * 100,  # 极端词典
        neg_terms=[],
    )
    score = backend.analyze("涨涨涨涨涨涨涨")
    assert -1.0 <= score <= 1.0
```

- [ ] **步骤 3：运行测试验证通过（需先 `pip install snownlp`）**

```
pip install snownlp scikit-learn
python -m pytest tests/test_phase3_sentiment.py::test_sentiment_positive_text tests/test_phase3_sentiment.py::test_sentiment_negative_text tests/test_phase3_sentiment.py::test_sentiment_empty_text tests/test_phase3_sentiment.py::test_sentiment_clamp_in_range -v
```
预期：4 passed

- [ ] **步骤 4：Commit**

```bash
git add research/sentiment.py tests/test_phase3_sentiment.py
git commit -m "feat(phase3): SnowNLPBackend sentiment analyzer with financial dict"
```

---

## 任务 4：政策对齐分数 `research/policy_alignment.py`

**文件：**
- 创建：`research/policy_alignment.py`
- 测试：`tests/test_phase3_sentiment.py`（追加 3 个用例）

- [ ] **步骤 1：创建 `research/policy_alignment.py`**

```python
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
```

- [ ] **步骤 2：写 3 个失败测试**

在 `tests/test_phase3_sentiment.py` 中追加：

```python
# ── 任务 4：政策对齐 ──────────────────────────────────────────────────────────

def test_policy_aligner_basic():
    """相关文本的 score > 不相关文本的 score"""
    from research.policy_alignment import PolicyAligner
    aligner = PolicyAligner().fit([
        "推动新能源汽车产业发展，支持光伏和储能技术创新",
        "加强半导体芯片自主研发，推进集成电路产业升级",
    ])
    score_relevant = aligner.score("公司专注新能源电池和光伏组件制造")
    score_irrelevant = aligner.score("餐饮连锁门店扩张，主营烤鸭和火锅")
    assert score_relevant > score_irrelevant


def test_policy_aligner_empty_corpus():
    """空语料时 score 返回 0.0"""
    from research.policy_alignment import PolicyAligner
    aligner = PolicyAligner().fit([])
    assert aligner.score("任意文本") == 0.0


def test_policy_aligner_score_in_range():
    """score 始终在 [0, 1] 范围内"""
    from research.policy_alignment import PolicyAligner
    aligner = PolicyAligner().fit(["政策文本一", "政策文本二"])
    score = aligner.score("查询文本")
    assert 0.0 <= score <= 1.0
```

- [ ] **步骤 3：运行测试验证通过**

```
python -m pytest tests/test_phase3_sentiment.py::test_policy_aligner_basic tests/test_phase3_sentiment.py::test_policy_aligner_empty_corpus tests/test_phase3_sentiment.py::test_policy_aligner_score_in_range -v
```
预期：3 passed

- [ ] **步骤 4：Commit**

```bash
git add research/policy_alignment.py tests/test_phase3_sentiment.py
git commit -m "feat(phase3): PolicyAligner TF-IDF cosine policy alignment"
```

---

## 任务 5：BFS 情感传播 `research/propagation.py`

**文件：**
- 创建：`research/propagation.py`
- 测试：`tests/test_phase3_sentiment.py`（追加 4 个用例）

- [ ] **步骤 1：创建 `research/propagation.py`**

```python
"""图上 BFS 衰减情感传播

propagate_scores() 以种子节点分数为起点，每跳乘以 decay 系数，
向上下游扩散。种子节点分数不被覆盖（seed 优先）。

用法：
    from knowledge.graph import IndustryGraph
    graph = IndustryGraph()
    # ... 构建图 ...
    result = propagate_scores(graph, {"芯片": -0.8}, decay=0.5, max_hops=2)
    # -> {"芯片": -0.8, "半导体设备": -0.4, "封装测试": -0.2, ...}
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from knowledge.graph import IndustryGraph


def propagate_scores(
    graph: "IndustryGraph",
    seed_scores: dict[str, float],
    decay: float = 0.5,
    max_hops: int = 2,
) -> dict[str, float]:
    """BFS 衰减传播。

    Args:
        graph: IndustryGraph 实例（已加载节点和边）
        seed_scores: {node_id: 初始分数}，分数范围 [-1, 1]
        decay: 每跳衰减系数（0 < decay ≤ 1）
        max_hops: 最大传播跳数

    Returns:
        {node_id: propagated_score}（含种子节点；种子分数不被覆盖）
    """
    result: dict[str, float] = dict(seed_scores)
    current_frontier: dict[str, float] = dict(seed_scores)

    for _ in range(max(1, max_hops)):
        next_frontier: dict[str, float] = {}
        for node_id, score in current_frontier.items():
            propagated = score * decay
            for neighbor in graph.neighbors(node_id, hops=1):
                if neighbor in seed_scores:
                    continue  # seed 优先，不覆盖
                existing = result.get(neighbor, 0.0)
                if abs(propagated) > abs(existing):
                    next_frontier[neighbor] = propagated
        for node, val in next_frontier.items():
            if abs(val) > abs(result.get(node, 0.0)):
                result[node] = val
        current_frontier = next_frontier
        if not current_frontier:
            break

    return result


def build_industry_events(
    news_row: dict,
    sentiment_score: float,
    policy_score: float,
    propagated: dict[str, float],
) -> list[dict]:
    """将传播结果转化为 industry_events 格式的行列表。

    每个被传播到的节点产出一条 event 行；
    sentiment_score 和 policy_score 为共享元数据。
    """
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    events = []
    published_at = news_row.get("published_at", now)
    source = news_row.get("source", "unknown")
    title = news_row.get("title", "")

    for node_id, prop_score in propagated.items():
        events.append({
            "event_id": uuid.uuid4().hex,
            "event_type": "sentiment_propagation",
            "industry": node_id,
            "symbol": news_row.get("related_symbol"),
            "title": title,
            "score": round(prop_score, 4),
            "source": source,
            "published_at": published_at,
            "ingested_at": now,
            "sentiment_score": round(sentiment_score, 4),
            "policy_score": round(policy_score, 4),
            "propagated_score": round(prop_score, 4),
        })
    return events


def upsert_event_scores(conn, events: list[dict]) -> int:
    """幂等写入 industry_events（含三个新列）。返回 upserted 行数。"""
    count = 0
    for e in events:
        conn.execute(
            """
            INSERT OR REPLACE INTO industry_events
                (event_id, event_type, industry, symbol, title, score,
                 source, published_at, ingested_at,
                 sentiment_score, policy_score, propagated_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                e["event_id"], e["event_type"], e.get("industry"),
                e.get("symbol"), e["title"], e["score"],
                e["source"], e.get("published_at"), e["ingested_at"],
                e.get("sentiment_score"), e.get("policy_score"),
                e.get("propagated_score"),
            ),
        )
        count += 1
    conn.commit()
    return count
```

- [ ] **步骤 2：写 4 个失败测试**

在 `tests/test_phase3_sentiment.py` 中追加：

```python
# ── 任务 5：BFS 传播 ──────────────────────────────────────────────────────────

def _make_test_graph():
    """构建最小测试图：芯片 → 半导体设备 → 封装测试"""
    from knowledge.graph import IndustryGraph
    g = IndustryGraph()
    g.upsert_node("芯片", "industry", "芯片行业")
    g.upsert_node("半导体设备", "segment", "半导体设备")
    g.upsert_node("封装测试", "segment", "封装测试")
    g.upsert_edge("芯片", "半导体设备", "has_segment", weight=0.9)
    g.upsert_edge("芯片", "封装测试", "has_segment", weight=0.8)
    return g


def test_propagation_single_hop():
    """单跳传播：邻居节点得到 seed * decay"""
    from research.propagation import propagate_scores
    g = _make_test_graph()
    result = propagate_scores(g, {"芯片": -0.8}, decay=0.5, max_hops=1)
    assert "半导体设备" in result
    assert abs(result["半导体设备"] - (-0.4)) < 1e-9


def test_propagation_seed_not_overwritten():
    """种子节点的分数不被传播覆盖"""
    from research.propagation import propagate_scores
    g = _make_test_graph()
    g.upsert_node("消费电子", "segment", "消费电子")
    g.upsert_edge("芯片", "消费电子", "has_segment", weight=0.7)
    seeds = {"芯片": -0.8, "封装测试": 0.5}
    result = propagate_scores(g, seeds, decay=0.5, max_hops=2)
    # 封装测试是 seed，不应被 芯片 传播结果覆盖
    assert result["封装测试"] == 0.5


def test_propagation_isolated_node():
    """孤立节点不会被传播影响"""
    from research.propagation import propagate_scores
    from knowledge.graph import IndustryGraph
    g = IndustryGraph()
    g.upsert_node("芯片", "industry", "芯片行业")
    g.upsert_node("孤立节点", "industry", "孤立的")
    # 无边连接
    result = propagate_scores(g, {"芯片": -0.8}, decay=0.5, max_hops=2)
    assert "孤立节点" not in result


def test_upsert_event_scores(tmp_path):
    """upsert_event_scores 写入 industry_events 含三新列"""
    import sqlite3
    from data_store.schema import create_schema, apply_migrations
    from research.propagation import upsert_event_scores

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    apply_migrations(conn)

    events = [{
        "event_id": "test001",
        "event_type": "sentiment_propagation",
        "industry": "芯片",
        "symbol": None,
        "title": "半导体行业负面消息",
        "score": -0.4,
        "source": "test",
        "published_at": "2026-01-01",
        "ingested_at": "2026-01-01T00:00:00",
        "sentiment_score": -0.8,
        "policy_score": 0.6,
        "propagated_score": -0.4,
    }]
    count = upsert_event_scores(conn, events)
    assert count == 1

    row = conn.execute("SELECT * FROM industry_events WHERE event_id='test001'").fetchone()
    assert row is not None
    assert abs(row["sentiment_score"] - (-0.8)) < 1e-6
    assert abs(row["policy_score"] - 0.6) < 1e-6
    conn.close()
```

- [ ] **步骤 3：运行测试验证通过**

```
python -m pytest tests/test_phase3_sentiment.py::test_propagation_single_hop tests/test_phase3_sentiment.py::test_propagation_seed_not_overwritten tests/test_phase3_sentiment.py::test_propagation_isolated_node tests/test_phase3_sentiment.py::test_upsert_event_scores -v
```
预期：4 passed

- [ ] **步骤 4：Commit**

```bash
git add research/propagation.py tests/test_phase3_sentiment.py
git commit -m "feat(phase3): BFS decay propagation + upsert_event_scores"
```

---

## 任务 6：配置 + daily_pipeline + 重放脚本

**文件：**
- 修改：`config.yaml`
- 修改：`scripts/daily_pipeline.py`
- 创建：`scripts/run_sentiment_replay.py`
- 测试：`tests/test_phase3_sentiment.py`（追加 2 个用例）

- [ ] **步骤 1：在 `config.yaml` 的 `filings:` 段之后追加**

```yaml
# ---------- 情感分析与政策传导 (Phase 3) ----------
sentiment:
  enabled: false          # feature flag（默认关，手动开启后执行 run_sentiment_replay.py）
  backend: snownlp        # snownlp | finbert（Phase 7 升级）
  decay: 0.5              # BFS 衰减系数（每跳乘以该值）
  max_hops: 2             # 最大传播跳数

policy:
  enabled: false          # 是否在 daily_pipeline 中抓取政策文本
  keywords:
    - 十五五
    - 产业政策
    - 新质生产力
    - 专精特新
    - 半导体
    - 新能源
```

- [ ] **步骤 2：在 `scripts/daily_pipeline.py` 的 `run_daily_pipeline()` 末尾追加 feature flag**

在现有 `if cfg.get("filings.enabled", False):` 块之后、`result["summary"]` 之前追加：

```python
    if cfg.get("policy.enabled", False):
        from data.policy.fifteenth_five_year import fetch_policy_articles, ingest_policy_articles
        from data_store.db import get_connection
        keywords = cfg.get("policy.keywords", [])
        with get_connection() as conn:
            articles = fetch_policy_articles(keywords=keywords)
            result["policy_ingest"] = ingest_policy_articles(conn, articles)

    if cfg.get("sentiment.enabled", False):
        from scripts.run_sentiment_replay import run as sentiment_run
        result["sentiment"] = sentiment_run()
```

- [ ] **步骤 3：创建 `scripts/run_sentiment_replay.py`**

```python
#!/usr/bin/env python3
"""历史新闻情感重放脚本

流程：
1. 从 data_store 加载 IndustryGraph
2. 构建 PolicyAligner（从 policy_items）
3. 读取 news_items（可按 start_date 过滤）
4. 对每条新闻：情感打分 → 政策对齐 → 传播 → 写 industry_events
5. 打印汇总
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta


def run(start_date: str | None = None, dry_run: bool = False) -> dict:
    """执行情感重放。

    Args:
        start_date: ISO 日期字符串（含），默认最近 30 天
        dry_run: True 时只打印不写库

    Returns:
        {"processed": int, "inserted": int, "errors": int}
    """
    from data_store.db import get_connection
    from knowledge.graph import IndustryGraph
    from research.sentiment import get_default_backend
    from research.policy_alignment import build_aligner_from_store
    from research.propagation import propagate_scores, build_industry_events, upsert_event_scores
    from utils.config import get_config

    cfg = get_config()
    decay = cfg.get("sentiment.decay", 0.5)
    max_hops = cfg.get("sentiment.max_hops", 2)

    if start_date is None:
        start_date = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    processed = inserted = errors = 0

    with get_connection() as conn:
        graph = IndustryGraph()
        graph.load_from_store(conn)

        aligner = build_aligner_from_store(conn)
        backend = get_default_backend()

        rows = conn.execute(
            "SELECT * FROM news_items WHERE published_at >= ? ORDER BY published_at",
            (start_date,),
        ).fetchall()

        for row in rows:
            try:
                row_dict = dict(row)
                text = f"{row_dict.get('title', '')} {row_dict.get('content', '')}"
                sentiment_score = backend.analyze(text)
                policy_score = aligner.score(text)

                # 推断关联节点
                seed_node = row_dict.get("related_symbol") or row_dict.get("industry")
                if not seed_node or not graph.has_node(seed_node):
                    # 用 industry 字段推断（若图中无对应节点则跳过传播）
                    seed_node = None

                if seed_node:
                    propagated = propagate_scores(
                        graph,
                        {seed_node: sentiment_score},
                        decay=decay,
                        max_hops=max_hops,
                    )
                else:
                    propagated = {}

                events = build_industry_events(row_dict, sentiment_score, policy_score, propagated)

                if not dry_run and events:
                    upsert_event_scores(conn, events)
                    inserted += len(events)

                processed += 1
            except Exception as e:
                print(f"[replay] 处理失败: {e}", file=sys.stderr)
                errors += 1

    summary = {"processed": processed, "inserted": inserted, "errors": errors}
    print(f"[replay] 完成: {summary}")
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="情感重放脚本")
    parser.add_argument("--start-date", default=None, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = parser.parse_args()
    run(start_date=args.start_date, dry_run=args.dry_run)
```

- [ ] **步骤 4：写 2 个集成测试**

在 `tests/test_phase3_sentiment.py` 中追加：

```python
# ── 任务 6：daily_pipeline feature flag + 重放脚本 ────────────────────────────

def test_daily_pipeline_sentiment_flag_off(monkeypatch):
    """sentiment.enabled=False 时 daily_pipeline 不调用 run_sentiment_replay"""
    from unittest.mock import patch, MagicMock

    # patch 所有 IO 函数
    with patch("scripts.daily_pipeline.update_data_store_run", return_value={}), \
         patch("scripts.daily_pipeline.update_knowledge_run", return_value={}), \
         patch("scripts.daily_pipeline.update_events_run", return_value={}), \
         patch("scripts.daily_pipeline.train_ml_run", return_value={}), \
         patch("scripts.daily_pipeline.run_ml_backtest_run", return_value={}), \
         patch("research.report_builder.build_daily_summary", return_value="ok"):
        from scripts.daily_pipeline import run_daily_pipeline
        result = run_daily_pipeline()
    # sentiment key 不应在结果中
    assert "sentiment" not in result


def test_sentiment_replay_dry_run(tmp_path, monkeypatch):
    """dry_run=True 时不向数据库写入任何行"""
    import sqlite3
    from data_store.schema import create_schema, apply_migrations
    from unittest.mock import patch

    db_path = str(tmp_path / "test.db")
    conn_setup = sqlite3.connect(db_path)
    create_schema(conn_setup)
    apply_migrations(conn_setup)
    conn_setup.commit()
    conn_setup.close()

    # 插入一条假新闻
    conn_insert = sqlite3.connect(db_path)
    conn_insert.execute(
        "INSERT INTO news_items (source, title, published_at, content_hash, ingested_at) "
        "VALUES ('test', '测试利好消息', '2026-01-01', 'hash001', '2026-01-01T00:00:00')"
    )
    conn_insert.commit()
    conn_insert.close()

    with patch("data_store.db.DEFAULT_DB_PATH", tmp_path / "test.db"):
        from scripts.run_sentiment_replay import run
        result = run(start_date="2026-01-01", dry_run=True)

    assert result["processed"] >= 1
    assert result["inserted"] == 0   # dry_run 不写库

    # 验证无行被写入
    conn_check = sqlite3.connect(db_path)
    count = conn_check.execute("SELECT COUNT(*) FROM industry_events").fetchone()[0]
    conn_check.close()
    assert count == 0
```

- [ ] **步骤 5：运行测试验证通过**

```
python -m pytest tests/test_phase3_sentiment.py::test_daily_pipeline_sentiment_flag_off tests/test_phase3_sentiment.py::test_sentiment_replay_dry_run -v
```
预期：2 passed

- [ ] **步骤 6：Commit**

```bash
git add config.yaml scripts/daily_pipeline.py scripts/run_sentiment_replay.py tests/test_phase3_sentiment.py
git commit -m "feat(phase3): sentiment replay script + daily_pipeline feature flag"
```

---

## 任务 7：全量回归 + 最终 Commit

**文件：** 无新文件

- [ ] **步骤 1：安装新依赖**

```
pip install snownlp scikit-learn
```

- [ ] **步骤 2：运行全量测试**

```
python -m pytest -q
```

预期：**≥ 105 passed**（89 旧 + 16 新），0 failed，warnings 不超过现有数量。

- [ ] **步骤 3：验证 industry_events 三列存在**

```python
python -c "
from data_store.db import get_connection
with get_connection() as conn:
    cur = conn.execute('PRAGMA table_info(industry_events)')
    cols = [r[1] for r in cur.fetchall()]
    print(cols)
    assert 'policy_score' in cols
    assert 'sentiment_score' in cols
    assert 'propagated_score' in cols
    print('OK: 三列均存在')
"
```

- [ ] **步骤 4：最终 Commit**

```bash
git add -A
git commit -m "feat(Phase3): 政策挖掘与情感传导完整落地

- data/policy/fifteenth_five_year.py：政策抓取 + AkShare 降级 + 种子数据
- research/sentiment.py：SnowNLPBackend + 金融词典加权 + SentimentBackend 抽象
- research/policy_alignment.py：TF-IDF 字符 bigram 余弦相似度
- research/propagation.py：BFS 衰减传播 + upsert_event_scores（三新列）
- data_store/schema.py：apply_migrations() 幂等追加 policy/sentiment/propagated_score
- scripts/run_sentiment_replay.py：历史重放入口
- config.yaml：sentiment/policy 两段 feature flag
- tests/test_phase3_sentiment.py：16 用例全绿

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## 自检结果

**规格覆盖度：**
- ✅ `data/policy/fifteenth_five_year.py` → 任务 2
- ✅ `research/policy_alignment.py` → 任务 4
- ✅ `research/sentiment.py` → 任务 3
- ✅ `research/propagation.py` → 任务 5
- ✅ `industry_events` 三列迁移 → 任务 1
- ✅ `scripts/run_sentiment_replay.py` → 任务 6
- ✅ `config.yaml` 新段 → 任务 6
- ✅ `daily_pipeline.py` feature flag → 任务 6

**占位符扫描：** 无"待定"/"TODO"占位符；所有步骤含完整代码块。

**类型一致性：**
- `propagate_scores` 参数 `IndustryGraph` → 任务 3 图构建使用同一类型 ✅
- `upsert_event_scores(conn, events)` 在任务 5 定义，任务 6 脚本中调用 ✅
- `build_aligner_from_store(conn)` 在任务 4 定义，任务 6 脚本中调用 ✅
