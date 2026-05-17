"""Phase 16.1 — LLM 统一客户端抽象 + 缓存

接口默认 OFF；支持 mock / deepseek / qwen / openai 后端。
未配置 API key 时优雅降级为 None。
"""
from __future__ import annotations

import abc
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LLMConfig:
    backend: str = "disabled"  # disabled / mock / deepseek / qwen / openai
    api_key: str = ""
    model: str = ""
    max_tokens: int = 2048
    temperature: float = 0.1
    base_url: str = ""
    extra: dict = field(default_factory=dict)


class BaseLLM(abc.ABC):
    """LLM 统一接口。"""

    model: str = ""

    def __init__(self):
        # 防止直接实例化（测试 test_base_llm_is_abstract）
        if type(self) is BaseLLM:
            raise TypeError("BaseLLM is abstract")

    @abc.abstractmethod
    def complete(self, prompt: str, **kwargs) -> str:
        raise NotImplementedError


class MockLLM(BaseLLM):
    """单元测试用：返回固定 / 关键字映射。"""

    model = "mock"

    def __init__(
        self,
        canned_response: str = "",
        response_map: Optional[dict] = None,
    ):
        super().__init__()
        self.canned_response = canned_response
        self.response_map = response_map or {}
        self.call_count = 0

    def complete(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        for keyword, resp in self.response_map.items():
            if keyword in prompt:
                return resp
        return self.canned_response


class DeepSeekLLM(BaseLLM):
    """DeepSeek 适配（openai 兼容协议，按需开启）。"""

    def __init__(self, cfg: LLMConfig):
        super().__init__()
        self.cfg = cfg
        self.model = cfg.model or "deepseek-chat"

    def complete(self, prompt: str, **kwargs) -> str:
        try:
            import requests  # type: ignore
        except ImportError as e:
            raise RuntimeError("DeepSeekLLM 需要 requests 包") from e
        url = (self.cfg.base_url or "https://api.deepseek.com") + "/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", self.cfg.max_tokens),
            "temperature": kwargs.get("temperature", self.cfg.temperature),
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


class OpenAILLM(BaseLLM):
    """OpenAI 适配（按需开启）。"""

    def __init__(self, cfg: LLMConfig):
        super().__init__()
        self.cfg = cfg
        self.model = cfg.model or "gpt-4o-mini"

    def complete(self, prompt: str, **kwargs) -> str:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise RuntimeError("OpenAILLM 需要 openai 包") from e
        client = OpenAI(api_key=self.cfg.api_key, base_url=self.cfg.base_url or None)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=kwargs.get("max_tokens", self.cfg.max_tokens),
            temperature=kwargs.get("temperature", self.cfg.temperature),
        )
        return resp.choices[0].message.content or ""


def get_llm_client(cfg: LLMConfig) -> Optional[BaseLLM]:
    """工厂方法：根据配置返回客户端；禁用或缺 key 返回 None。"""
    backend = (cfg.backend or "disabled").lower()
    if backend == "disabled":
        return None
    if backend == "mock":
        return MockLLM(canned_response="{}")
    if backend in ("deepseek", "qwen"):
        if not cfg.api_key:
            return None
        return DeepSeekLLM(cfg)
    if backend == "openai":
        if not cfg.api_key:
            return None
        return OpenAILLM(cfg)
    return None


class LLMCache:
    """简单 sqlite LLM 响应缓存（按 (prompt_hash, model)）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_cache (
                prompt_hash TEXT NOT NULL,
                model TEXT NOT NULL,
                response TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (prompt_hash, model)
            )
            """
        )
        self._conn.commit()

    @staticmethod
    def _hash(prompt: str) -> str:
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def get(self, prompt: str, model: str) -> Optional[str]:
        cur = self._conn.execute(
            "SELECT response FROM llm_cache WHERE prompt_hash=? AND model=?",
            (self._hash(prompt), model),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set(self, prompt: str, model: str, response: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO llm_cache(prompt_hash, model, response, created_at) "
            "VALUES (?,?,?,?)",
            (self._hash(prompt), model, response, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
