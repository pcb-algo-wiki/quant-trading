"""
utils/config.py
===============
配置管理模块 — 从 config.yaml 加载所有配置

用法:
  from utils.config import cfg
  print(cfg.etfs['159915'])
  print(cfg.backtest.commission)
  cfg.set('news.enabled', True)   # 运行时修改
"""

import yaml
import os
from pathlib import Path
from typing import Any, Dict, Optional
from copy import deepcopy


class Config:
    """配置管理类"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            # 自动查找 config.yaml
            project_root = Path(__file__).parent.parent
            config_path = project_root / "config.yaml"
        
        self._path = str(config_path)
        self._raw: Dict[str, Any] = {}
        self._loaded = False
        self.load()

    def load(self):
        """从YAML文件加载配置"""
        path = Path(self._path)
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self._path}")
        
        with open(path, "r", encoding="utf-8") as f:
            self._raw = yaml.safe_load(f) or {}
        self._loaded = True
        self._apply_env_overrides()

    def _apply_env_overrides(self):
        """环境变量覆盖（优先级最高）"""
        # 例如: QUANT_COMMISSION=0.0005 python run.py
        env_map = {
            "QUANT_INITIAL_CAPITAL": ("backtest", "initial_capital"),
            "QUANT_COMMISSION": ("backtest", "commission"),
            "QUANT_SLIPPAGE": ("backtest", "slippage"),
            "QUANT_NEWS_ENABLED": ("news", "enabled"),
            "QUANT_LOG_LEVEL": ("logging", "level"),
        }
        for env_key, (section, key) in env_map.items():
            val = os.environ.get(env_key)
            if val is not None:
                try:
                    val = float(val)
                except ValueError:
                    pass
                if section in self._raw and key in self._raw[section]:
                    self._raw[section][key] = val

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号路径
        例如: cfg.get('backtest.commission', 0.0003)
        """
        keys = key_path.split(".")
        val = self._raw
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set(self, key_path: str, value: Any):
        """运行时修改配置（仅影响内存）"""
        keys = key_path.split(".")
        d = self._raw
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    def __getitem__(self, key: str) -> Any:
        """cfg.section 访问"""
        if key in self._raw:
            return self._raw[key]
        raise AttributeError(f"配置项不存在: {key}")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return super().__getattribute__(name)
        if name in self._raw:
            return self._raw[name]
        raise AttributeError(f"配置项不存在: {name}")

    def reload(self):
        """重新从文件加载"""
        self.load()

    @property
    def etfs(self) -> Dict[str, Dict]:
        """启用的ETF标的"""
        all_etfs = self._raw.get("etfs", {})
        return {k: v for k, v in all_etfs.items() if v.get("enabled", True)}

    @property
    def enabled_etf_codes(self) -> list:
        """启用的ETF代码列表"""
        return list(self.etfs.keys())

    def __repr__(self):
        return f"<Config loaded={self._loaded} path={self._path}>"


# 全局单例
_cfg: Optional[Config] = None


def load_config(path: str = None) -> Config:
    """加载配置（单例）"""
    global _cfg
    _cfg = Config(path)
    return _cfg


def get_config() -> Config:
    """获取已加载的配置"""
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


# 快捷访问
cfg = get_config()
