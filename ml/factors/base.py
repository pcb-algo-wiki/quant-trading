"""Phase 14.1 — 因子库基础设施"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseFactor(ABC):
    name: str = ""
    category: str = "uncategorized"

    @abstractmethod
    def compute(self, price_df: pd.DataFrame) -> pd.Series:
        raise NotImplementedError


class FactorRegistry:
    def __init__(self):
        self._factors: dict[str, BaseFactor] = {}

    def register(self, factor: BaseFactor) -> None:
        if not factor.name:
            raise ValueError("Factor must have non-empty name")
        self._factors[factor.name] = factor

    def get(self, name: str) -> BaseFactor:
        if name not in self._factors:
            raise KeyError(f"Factor '{name}' not registered")
        return self._factors[name]

    def list_names(self) -> list[str]:
        return list(self._factors.keys())

    def list_by_category(self, category: str) -> list[str]:
        return [n for n, f in self._factors.items() if f.category == category]

    def compute_matrix(self, price_df: pd.DataFrame) -> pd.DataFrame:
        if not self._factors:
            return pd.DataFrame(index=price_df.index)
        out = {}
        for name, factor in self._factors.items():
            try:
                s = factor.compute(price_df)
                out[name] = s.reset_index(drop=True)
            except Exception:
                out[name] = pd.Series([float("nan")] * len(price_df))
        return pd.DataFrame(out)
