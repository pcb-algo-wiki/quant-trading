"""情感分析后端

架构：
- SentimentBackend：抽象接口，analyze(text) -> float [-1, 1]
- SnowNLPBackend：SnowNLP 基线 × 2 − 1 + 金融词典加权（上下限 ±0.3）
- FinBERTBackend：Phase 7 升级后端，软导入 transformers/torch，无包自动降级 SnowNLP
- get_default_backend()：读 config sentiment.backend，默认 snownlp
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_POS_TERMS = [
    "利好", "涨停", "超预期", "业绩增长", "订单", "扩产", "中标",
    "突破", "创新高", "增持", "回购", "分红",
]
DEFAULT_NEG_TERMS = [
    "利空", "下跌", "亏损", "违规", "诉讼", "暂停", "减值",
    "业绩下滑", "亏损扩大", "被查", "退市", "降级",
]

# FinBERT 中文模型（Hugging Face Hub）
_FINBERT_MODEL = "yiyanghkust/finbert-tone"
_FINBERT_CN_MODEL = "hw-tseng/finbert-chinese"


class SentimentBackend:
    """情感分析抽象基类。子类必须实现 analyze()。"""

    def analyze(self, text: str) -> float:
        """返回情感分数，范围 [-1, 1]。正面 > 0，负面 < 0，中性 ≈ 0。"""
        raise NotImplementedError

    def analyze_batch(self, texts: list[str]) -> list[float]:
        """批量分析（默认逐条调用 analyze，子类可覆盖提升效率）。"""
        return [self.analyze(t) for t in texts]


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


class FinBERTBackend(SentimentBackend):
    """Phase 7 FinBERT 升级后端。

    软导入 transformers + torch：
      - 有包且 GPU/CPU 可用 → 真实 FinBERT 推理
      - 无包或加载失败 → 自动降级为 SnowNLPBackend

    Args:
        model_name: Hugging Face Hub 模型名（可本地路径）
        device: "cpu" | "cuda" | "auto"（auto 时优先 CUDA）
        fallback: 是否在加载失败时自动降级（默认 True）
    """

    def __init__(
        self,
        model_name: str = _FINBERT_CN_MODEL,
        device: str = "auto",
        fallback: bool = True,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._fallback = fallback
        self._pipeline = None
        self._fallback_backend: SentimentBackend | None = None
        self._ready = False
        self._try_load()

    def _try_load(self) -> None:
        """尝试加载 FinBERT pipeline，失败时设置 fallback。"""
        try:
            import torch
            from transformers import pipeline as hf_pipeline

            device_id: int | str
            if self._device == "auto":
                device_id = 0 if torch.cuda.is_available() else -1
            elif self._device == "cuda":
                device_id = 0
            else:
                device_id = -1

            self._pipeline = hf_pipeline(
                "text-classification",
                model=self._model_name,
                device=device_id,
                top_k=None,
            )
            self._ready = True
            logger.info("[FinBERT] 模型加载成功: %s (device=%s)", self._model_name, self._device)
        except ImportError:
            logger.warning("[FinBERT] transformers/torch 未安装，降级为 SnowNLPBackend")
            self._fallback_backend = SnowNLPBackend()
        except Exception as exc:
            logger.warning("[FinBERT] 模型加载失败: %s，降级为 SnowNLPBackend", exc)
            if self._fallback:
                self._fallback_backend = SnowNLPBackend()
            else:
                raise

    @property
    def is_ready(self) -> bool:
        """返回 True 表示 FinBERT 已就绪；False 表示降级模式。"""
        return self._ready

    def analyze(self, text: str) -> float:
        if not text or not text.strip():
            return 0.0
        if not self._ready:
            return self._fallback_backend.analyze(text) if self._fallback_backend else 0.0

        try:
            results = self._pipeline(text[:512])  # 截断超长文本
            # results: [[{label, score}, ...]] top_k=None
            if results and results[0]:
                label_scores = {r["label"].lower(): r["score"] for r in results[0]}
                pos = label_scores.get("positive", 0.0)
                neg = label_scores.get("negative", 0.0)
                return float(pos - neg)  # [-1, 1]
        except Exception as exc:
            logger.debug("[FinBERT] 推理失败: %s", exc)

        return self._fallback_backend.analyze(text) if self._fallback_backend else 0.0

    def analyze_batch(self, texts: list[str]) -> list[float]:
        """批量推理（FinBERT 支持 batching）。"""
        if not self._ready or not texts:
            return [self.analyze(t) for t in texts]

        try:
            truncated = [t[:512] for t in texts]
            results = self._pipeline(truncated)
            scores = []
            for r in results:
                label_scores = {item["label"].lower(): item["score"] for item in r}
                pos = label_scores.get("positive", 0.0)
                neg = label_scores.get("negative", 0.0)
                scores.append(float(pos - neg))
            return scores
        except Exception as exc:
            logger.debug("[FinBERT] 批量推理失败: %s，逐条降级", exc)
            return [self.analyze(t) for t in texts]


def get_default_backend() -> SentimentBackend:
    """根据 config.yaml sentiment.backend 返回对应后端。默认 SnowNLPBackend。

    支持值：
      snownlp  — SnowNLPBackend（默认）
      finbert  — FinBERTBackend（Phase 7，软导入，无包自动降级）
    """
    try:
        from utils.config import get_config
        cfg = get_config()
        backend_name = cfg.get("sentiment.backend", "snownlp")
    except Exception:
        backend_name = "snownlp"

    if backend_name == "finbert":
        return FinBERTBackend()
    return SnowNLPBackend()
