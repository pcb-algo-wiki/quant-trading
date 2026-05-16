# Phase 3 政策挖掘与情感传导 — 设计规格

> 日期：2026-05-16  
> 约束：单人 / 本地优先 / 无 GPU / 无外部 API Key

---

## 目标

将 `policy_items` + `news_items` 两张表的内容，通过三条管道产出结构化分数，并沿 `IndustryGraph` 传播，最终写入 `industry_events`：

1. **Policy Alignment Score** — 公司/行业主营业务与政策关键词的 TF-IDF 余弦相似度
2. **Sentiment Score** — SnowNLP 基线 + 金融情感词典加权（含正向/负向词表）
3. **Propagated Score** — 在 `IndustryGraph` 上 BFS 衰减传播，把节点得分扩散到上下游

---

## 数据流

```
policy_items (DB)
      │
      ▼
PolicyAligner.fit()          ←── TF-IDF 语料（政策文本合集）
      │
      ▼ .score(company_desc)
  policy_score: float [0,1]
      │
      ├─────────────────────────────────────────────┐
news_items (DB)                                      │
      │                                             │
      ▼                                             │
SentimentBackend.analyze(text)                      │
  sentiment_score: float [-1,1] (SnowNLPBackend)   │
      │                                             │
      ▼                                             │
propagate_scores(IndustryGraph, seeds)              │
  propagated_score: float [-1,1]                    │
      │                                             │
      └──────► industry_events                 ◄───┘
                  (upsert; 3 新列)
```

---

## 组件设计

### 1. `data/policy/fifteenth_five_year.py`

**职责**：抓取"十四五"/"十五五"政策文本（使用 AkShare `article_ths_bbs_xhsb` 或直接 HTTP 请求政府网站 RSS）并写入 `policy_items`。

**接口**：

```python
def fetch_policy_articles(
    keywords: list[str],           # 搜索关键词，如 ["十五五", "产业政策"]
    source: str = "gov_rss",       # 来源标签
    max_items: int = 100,
) -> list[dict]:
    """返回 [{title, content, url, published_at, content_hash, source}]"""

def ingest_policy_articles(conn, articles: list[dict]) -> dict:
    """幂等写入 policy_items，返回 {inserted: int, skipped: int}"""
```

**降级策略**：网络请求失败 → 读取 `data/cache/policy_seed.json`（项目预置 5 条政策摘要）。

---

### 2. `research/sentiment.py`

**职责**：对任意文本产出情感分数，支持多后端热切换。

**接口**：

```python
class SentimentBackend:
    """抽象接口，Phase 7 可替换为 FinBERT"""
    def analyze(self, text: str) -> float:
        """返回 [-1, 1]，正面 > 0，负面 < 0"""
        raise NotImplementedError

class SnowNLPBackend(SentimentBackend):
    """
    SnowNLP 基线（原始输出 [0,1]）×2−1 → [-1,1]
    然后叠加金融词典加权：
      positive_boost = count(pos_terms) * 0.1（上限 +0.3）
      negative_boost = count(neg_terms) * 0.1（下限 -0.3）
    最终 clamp(-1, 1)
    """
    def __init__(self, pos_terms: list[str], neg_terms: list[str]): ...
    def analyze(self, text: str) -> float: ...

def get_default_backend() -> SentimentBackend:
    """从 config.yaml sentiment.backend 读取，默认 SnowNLPBackend"""
```

**金融词典（内置默认值）**：

```python
DEFAULT_POS_TERMS = ["利好", "涨停", "超预期", "业绩增长", "订单", "扩产", "中标"]
DEFAULT_NEG_TERMS = ["利空", "下跌", "亏损", "违规", "诉讼", "暂停", "减值"]
```

---

### 3. `research/policy_alignment.py`

**职责**：用 TF-IDF 量化公司/行业与政策文本的对齐程度。

**接口**：

```python
class PolicyAligner:
    def fit(self, policy_texts: list[str]) -> "PolicyAligner":
        """构建 TF-IDF 词汇表和文档矩阵（sklearn TfidfVectorizer）"""

    def score(self, query_text: str) -> float:
        """query_text = 公司主营/行业描述；返回 max 余弦相似度 [0,1]"""

def build_aligner_from_store(conn) -> PolicyAligner:
    """从 policy_items 加载全部内容 fit PolicyAligner"""

def compute_policy_scores(
    conn,
    symbol_desc: dict[str, str],   # symbol -> 业务描述文本
) -> dict[str, float]:
    """批量返回每个 symbol 的 policy_score"""
```

**依赖**：`scikit-learn`（已在 requirements.txt）。

---

### 4. `research/propagation.py`

**职责**：在 `IndustryGraph` 上 BFS 衰减传播情感分数。

**接口**：

```python
def propagate_scores(
    graph: IndustryGraph,
    seed_scores: dict[str, float],   # node_id -> 初始分数 [-1,1]
    decay: float = 0.5,              # 每跳衰减系数（来自 config）
    max_hops: int = 2,               # 最大传播跳数
) -> dict[str, float]:
    """
    算法：BFS 逐层传播
    propagated[neighbor] = max(现有值, parent_score * decay^hop)
    不覆盖 seed_scores（seed 优先）
    返回所有被影响节点的 {node_id: score}
    """

def build_industry_events(
    news_row: dict,
    sentiment_score: float,
    policy_score: float,
    propagated: dict[str, float],
) -> list[dict]:
    """构造 industry_events 格式的行列表（供 upsert）"""

def upsert_event_scores(conn, events: list[dict]) -> int:
    """
    对 industry_events 做 INSERT OR REPLACE；
    新列 policy_score / sentiment_score / propagated_score
    返回 upserted 行数
    """
```

---

### 5. Schema 迁移（`data_store/schema.py`）

`industry_events` 表追加三列（幂等，PRAGMA table_info 检查）：

```sql
ALTER TABLE industry_events ADD COLUMN policy_score REAL;
ALTER TABLE industry_events ADD COLUMN sentiment_score REAL;
ALTER TABLE industry_events ADD COLUMN propagated_score REAL;
```

迁移通过 `MIGRATION_STATEMENTS` 列表 + `apply_migrations(conn)` 函数实现，在 `create_schema` 后调用（`db.get_connection()` 自动 bootstrap）。

---

### 6. `config.yaml` 新增段

```yaml
sentiment:
  enabled: false          # feature flag
  backend: snownlp        # snownlp | finbert（Phase 7）
  decay: 0.5              # BFS 衰减系数
  max_hops: 2             # 最大传播跳数

policy:
  enabled: false
  keywords:               # 政策搜索关键词
    - 十五五
    - 产业政策
    - 新质生产力
    - 专精特新
```

---

### 7. `scripts/run_sentiment_replay.py`

**职责**：重放历史 `news_items`，产出 `industry_events` + `propagated_score`。

**流程**：

```
1. 加载 IndustryGraph (load_from_store)
2. 构建 PolicyAligner (build_aligner_from_store)
3. 读取 news_items WHERE published_at >= start_date
4. 对每条新闻：
   a. 调 SentimentBackend.analyze(title + content)
   b. 调 PolicyAligner.score(title)
   c. 推断关联节点（industry / symbol 字段）
   d. 调 propagate_scores(graph, {node: sentiment_score})
   e. build_industry_events → upsert_event_scores
5. 打印汇总：processed / inserted / skipped
```

---

## 测试覆盖计划（≥ 16 用例）

| 测试模块 | 用例 |
|---|---|
| `test_sentiment` | SnowNLPBackend 正面文本 > 0；负面 < 0；中性约 0；词典加权上限 clamp |
| `test_policy_alignment` | fit + score 返回 [0,1]；空语料 score=0；相关文本 > 不相关 |
| `test_propagation` | 单跳传播 score = seed*decay；多跳衰减；seed 节点不被覆盖；孤立节点无传播 |
| `test_schema_migration` | migration 幂等（二次调用不报错）；三新列存在 |
| `test_policy_ingest` | fetch 失败降级到 seed；ingest 幂等（content_hash 唯一） |
| `test_sentiment_replay` | mock graph + mock news → industry_events 写入正确列 |

---

## 依赖补充

```
snownlp>=0.12.3   # 中文情感分析
```

（`scikit-learn` 已存在于 requirements.txt）

---

## 验收标准

1. `python -m pytest -q` → **≥ 105 passed**（89 旧 + 16 新）
2. 给定一条供应链负面新闻，`run_sentiment_replay.py` 能写入 `industry_events`，`propagated_score != NULL`
3. `data_store.industry_events` 三新列存在且 PRAGMA 验证通过
4. feature flag `sentiment.enabled=false` 时 daily_pipeline 跳过（不报错）
