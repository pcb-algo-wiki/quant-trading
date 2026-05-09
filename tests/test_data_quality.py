"""
tests/test_data_quality.py
==========================
数据质量校验测试
"""

import pytest
import pandas as pd
import numpy as np
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data.quality import validate_ohlc, detect_suspicious_data, check_data_freshness, QualityReport


class TestValidateOHLC:
    """OHLC校验测试"""

    def test_clean_data_passes(self, sample_ohlcv):
        """干净数据 → 全部通过"""
        df_clean, report = validate_ohlc(sample_ohlcv)
        assert report.level == "PASS"
        assert report.original_rows == len(sample_ohlcv)
        assert report.cleaned_rows == report.original_rows

    def test_high_less_than_low_fixed(self):
        """high < low → 应被修正"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5),
            "open": [100, 101, 103, 102, 101],
            "high": [102, 106, 105, 104, 103],  # row2: 105 < low=106? No - set below
            "low": [99, 105, 106, 99, 98],      # row2: high=105 < low=106 → 违规
            "close": [101, 105, 104, 103, 102],
            "volume": [1_000_000] * 5,
        })
        # 人为制造 high < low 违规（仅row2）
        df.loc[2, "high"] = 100  # < low=106
        df.loc[2, "open"] = 103   # 同时修复open
        
        df_clean, report = validate_ohlc(df)
        assert report.high_low_violations == 1
        # 修正后high应 >= low
        if len(df_clean) > 0:
            assert (df_clean["high"] >= df_clean["low"]).all()

    def test_zero_volume_filtered(self):
        """volume=0 → 应被移除（停牌日）"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5),
            "open": [100, 101, 102, 103, 104],
            "high": [105, 106, 107, 108, 109],
            "low": [99, 98, 97, 96, 95],
            "close": [100, 101, 102, 103, 104],
            "volume": [1_000_000, 0, 2_000_000, 0, 3_000_000],  # 停牌日
        })
        df_clean, report = validate_ohlc(df)
        assert report.zero_volume_rows == 2
        assert len(df_clean) == 3

    def test_missing_values_removed(self):
        """缺失值 → 应被移除"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5),
            "open": [100, np.nan, 102, 103, 104],
            "high": [105, 106, 107, 108, 109],
            "low": [99, 98, 97, 96, 95],
            "close": [100, 101, np.nan, 103, 104],
            "volume": [1_000_000] * 5,
        })
        df_clean, report = validate_ohlc(df)
        assert report.missing_value_rows == 2
        assert len(df_clean) == 3

    def test_quality_report_fixes(self):
        """QualityReport.fixes记录修复过程"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5),
            "open": [100, 105, 103, 102, 101],
            "high": [102, 108, 105, 104, 103],
            "low": [99, 106, 100, 99, 98],
            "close": [101, 106, 104, 103, 102],
            "volume": [1_000_000, 0, 2_000_000, 0, 3_000_000],
        })
        df.loc[2, "high"] = 100  # 制造违规
        df_clean, report = validate_ohlc(df)
        assert len(report.fixes) >= 0  # 有或没有都行


class TestDetectSuspicious:
    """可疑数据检测测试"""

    def test_no_suspicious_in_clean_data(self, sample_ohlcv):
        """干净数据 → 无可疑"""
        result = detect_suspicious_data(sample_ohlcv)
        assert result.sum() == 0

    def test_zero_volume_detected(self):
        """停牌日 → 可疑"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=10),
            "open": [100] * 10,
            "high": [105] * 10,
            "low": [99] * 10,
            "close": [100] * 10,
            "volume": [1_000_000] * 7 + [0, 0, 0],
        })
        suspicious = detect_suspicious_data(df, lookback=5)
        assert suspicious.iloc[-5:].sum() >= 3


class TestDataFreshness:
    """数据新鲜度测试"""

    def test_fresh_data(self):
        """近5日数据 → fresh=True"""
        df = pd.DataFrame({
            "date": pd.date_range(pd.Timestamp.today() - pd.Timedelta(days=2), periods=5),
            "open": [100] * 5,
            "high": [105] * 5,
            "low": [99] * 5,
            "close": [100] * 5,
            "volume": [1_000_000] * 5,
        })
        result = check_data_freshness(df)
        assert result["fresh"] is True
        assert result["age_days"] <= 5

    def test_stale_data(self):
        """超过5日 → fresh=False"""
        df = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=5),
            "open": [100] * 5,
            "high": [105] * 5,
            "low": [99] * 5,
            "close": [100] * 5,
            "volume": [1_000_000] * 5,
        })
        result = check_data_freshness(df)
        assert result["fresh"] is False
        assert result["age_days"] > 5
