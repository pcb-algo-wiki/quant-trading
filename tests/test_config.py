"""
tests/test_config.py
====================
配置管理测试
"""

import pytest
import yaml
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.config import Config, load_config, get_config


class TestConfig:
    """配置加载测试"""

    def test_load_from_file(self, config_path):
        """从文件加载配置"""
        cfg = Config(config_path)
        assert cfg._loaded is True
        assert cfg.backtest["initial_capital"] == 100_000

    def test_get_with_default(self, config_path):
        """get方法默认值"""
        cfg = Config(config_path)
        assert cfg.get("nonexistent.key", "default") == "default"
        assert cfg.get("backtest.commission", 0.001) == 0.0003

    def test_get_nested(self, config_path):
        """嵌套字段访问"""
        cfg = Config(config_path)
        assert cfg.get("strategies.ma_cross.fast_period") == 5
        assert cfg.get("strategies.ma_cross.slow_period") == 20

    def test_set_runtime(self, config_path):
        """运行时修改"""
        cfg = Config(config_path)
        cfg.set("backtest.initial_capital", 500_000)
        assert cfg.get("backtest.initial_capital") == 500_000

    def test_etfs_enabled_filter(self, config_path):
        """enabled_etf_codes过滤"""
        cfg = Config(config_path)
        codes = cfg.enabled_etf_codes
        assert "510300" in codes
        assert "159915" in codes

    def test_singleton(self, config_path):
        """单例模式"""
        cfg1 = load_config(config_path)
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_repr(self, config_path):
        """repr"""
        cfg = Config(config_path)
        assert "loaded=True" in repr(cfg)

    def test_env_reference_resolution(self, tmp_path, monkeypatch):
        """YAML中${VAR}可解析为环境变量"""
        config = {
            "notification": {
                "pushplus_token": "${PUSHPLUS_TOKEN}",
            }
        }
        path = tmp_path / "env_config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True)

        monkeypatch.setenv("PUSHPLUS_TOKEN", "token-from-env")
        cfg = Config(str(path))
        assert cfg.get("notification.pushplus_token") == "token-from-env"

    def test_env_reference_missing_falls_back_empty(self, tmp_path, monkeypatch):
        """环境变量缺失时，${VAR}解析为空字符串"""
        config = {
            "notification": {
                "pushplus_token": "${PUSHPLUS_TOKEN}",
            }
        }
        path = tmp_path / "env_config.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True)

        monkeypatch.delenv("PUSHPLUS_TOKEN", raising=False)
        cfg = Config(str(path))
        assert cfg.get("notification.pushplus_token") == ""
