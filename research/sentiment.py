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
