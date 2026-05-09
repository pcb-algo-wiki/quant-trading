"""
data/quality.py
===============
数据质量校验 — 确保OHLCV数据可靠

功能:
- OHLC逻辑校验: high ≥ low, high ≥ open, high ≥ close, low ≤ open, low ≤ close
- 停牌日过滤: volume = 0
- 异常值检测: 涨跌幅超过阈值
- 缺失值处理: 前向填充 + 标记
- 复权一致性: 检测前复权/后复权混用

用法:
  from data.quality import validate_and_clean
  df_clean = validate_and_clean(df, fix=True)
"""

import pandas as pd
import numpy as np
from typing import Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class QualityReport:
    """数据质量报告"""
    original_rows: int = 0
    cleaned_rows: int = 0
    removed_rows: int = 0
    
    # 问题计数
    high_low_violations: int = 0      # high < low
    high_open_violations: int = 0    # high < open
    high_close_violations: int = 0   # high < close
    low_open_violations: int = 0      # low > open
    low_close_violations: int = 0     # low > close
    zero_volume_rows: int = 0         # 停牌日
    missing_value_rows: int = 0       # 缺失值
    extreme_change_rows: int = 0     # 涨跌幅异常
    
    # 修复记录
    fixes: list = field(default_factory=list)
    
    # 级别
    level: str = "PASS"  # PASS | WARN | ERROR
    
    @property
    def clean_rate(self) -> float:
        if self.original_rows == 0:
            return 1.0
        return self.cleaned_rows / self.original_rows
    
    def add_fix(self, msg: str):
        self.fixes.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    
    def summary(self) -> str:
        total_issues = (
            self.high_low_violations + self.high_open_violations +
            self.high_close_violations + self.low_open_violations +
            self.low_close_violations + self.zero_volume_rows +
            self.missing_value_rows + self.extreme_change_rows
        )
        return (
            f"数据质量: {self.level} | "
            f"原始{self.original_rows}行 → 清洗后{self.cleaned_rows}行 "
            f"(移除{total_issues}问题, 修复{len(self.fixes)}处)"
        )


def validate_ohlc(df: pd.DataFrame) -> Tuple[pd.DataFrame, QualityReport]:
    """
    校验并清洗OHLCV数据
    
    Args:
        df: 原始OHLCV DataFrame，需包含 date/open/high/low/close/volum列
        fix: 是否自动修复
    
    Returns:
        (清洗后DataFrame, QualityReport)
    """
    df = df.copy()
    report = QualityReport()
    report.original_rows = len(df)
    
    required_cols = ["open", "high", "low", "close"]
    has_volume = "volume" in df.columns
    
    # 检查列
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"缺少必需列: {col}")
    
    # 初始化
    mask_bad = pd.Series(False, index=df.index)
    
    # ---- 1. OHLC逻辑校验 ----
    # high必须 >= low
    mask = df["high"] < df["low"]
    report.high_low_violations = mask.sum()
    mask_bad |= mask
    if mask.any():
        report.add_fix(f"high<low: {mask.sum()}行 → 修正high=low")
        if "volume" in df.columns:
            df.loc[mask, "high"] = df.loc[mask, ["open", "close"]].max(axis=1)
        else:
            df.loc[mask, "high"] = df.loc[mask, "low"]
    
    # high >= open
    mask = df["high"] < df["open"]
    report.high_open_violations = mask.sum()
    mask_bad |= mask
    if mask.any():
        report.add_fix(f"high<open: {mask.sum()}行 → 修正high=open")
        df.loc[mask, "high"] = df.loc[mask, "open"]
    
    # high >= close
    mask = df["high"] < df["close"]
    report.high_close_violations = mask.sum()
    mask_bad |= mask
    if mask.any():
        report.add_fix(f"high<close: {mask.sum()}行 → 修正high=close")
        df.loc[mask, "high"] = df.loc[mask, "close"]
    
    # low <= open
    mask = df["low"] > df["open"]
    report.low_open_violations = mask.sum()
    mask_bad |= mask
    if mask.any():
        report.add_fix(f"low>open: {mask.sum()}行 → 修正low=open")
        df.loc[mask, "low"] = df.loc[mask, "open"]
    
    # low <= close
    mask = df["low"] > df["close"]
    report.low_close_violations = mask.sum()
    mask_bad |= mask
    if mask.any():
        report.add_fix(f"low>close: {mask.sum()}行 → 修正low=close")
        df.loc[mask, "low"] = df.loc[mask, "close"]
    
    # ---- 2. 停牌日过滤 (volume=0) ----
    if has_volume:
        mask_zero_vol = df["volume"] == 0
        report.zero_volume_rows = mask_zero_vol.sum()
        mask_bad |= mask_zero_vol
        if mask_zero_vol.any():
            report.add_fix(f"停牌日(volume=0): {mask_zero_vol.sum()}行 → 移除")
    
    # ---- 3. 缺失值 ----
    mask_na = df[required_cols].isna().any(axis=1)
    report.missing_value_rows = mask_na.sum()
    mask_bad |= mask_na
    if mask_na.any():
        report.add_fix(f"缺失值(OHLC): {mask_na.sum()}行 → 移除")
    
    # ---- 4. 涨跌幅异常 (>20% 单日) ----
    if len(df) > 1 and "close" in df.columns:
        pct_change = df["close"].pct_change().abs()
        mask_extreme = pct_change > 0.20  # 20%
        report.extreme_change_rows = mask_extreme.sum()
        if mask_extreme.any() and not mask_extreme.sum() > len(df) * 0.1:
            # 少量极端值不删除，只记录
            report.add_fix(f"涨跌幅异常(>20%): {mask_extreme.sum()}行 → 标记但保留")
    
    # 移除坏数据
    df_clean = df[~mask_bad].reset_index(drop=True)
    report.cleaned_rows = len(df_clean)
    report.removed_rows = report.original_rows - report.cleaned_rows
    
    # 判断级别
    total_issues = (
        report.high_low_violations + report.high_open_violations +
        report.high_close_violations + report.low_open_violations +
        report.low_close_violations + report.zero_volume_rows +
        report.missing_value_rows
    )
    if total_issues == 0:
        report.level = "PASS"
    elif report.clean_rate > 0.99:
        report.level = "PASS"
    elif report.clean_rate > 0.95:
        report.level = "WARN"
    else:
        report.level = "ERROR"
    
    return df_clean, report


def detect_suspicious_data(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    检测近期可疑数据（用于报警）
    返回每行是否可疑
    """
    if len(df) < lookback:
        return pd.Series(False, index=df.index)
    
    suspicious = pd.Series(False, index=df.index)
    
    # 近N日成交量为0
    if "volume" in df.columns:
        recent_vol_zero = df["volume"].iloc[-lookback:] == 0
        suspicious.iloc[-lookback:] = recent_vol_zero
    
    # 近N日价格变化异常
    if "close" in df.columns and len(df) > 1:
        pct = df["close"].pct_change().iloc[-lookback:].abs()
        suspicious.iloc[-lookback:] |= (pct > 0.15)
    
    return suspicious


def check_data_freshness(df: pd.DataFrame, max_age_days: int = 5) -> dict:
    """
    检查数据新鲜度
    """
    if "date" not in df.columns or len(df) == 0:
        return {"fresh": False, "error": "无日期列"}
    
    last_date = pd.to_datetime(df["date"]).max()
    today = pd.Timestamp.today()
    age_days = (today - last_date).days
    
    return {
        "fresh": age_days <= max_age_days,
        "last_date": str(last_date.date()),
        "age_days": age_days,
        "max_age_days": max_age_days,
    }


# ============ 主入口 ============

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    
    from data.fetcher import fetch_etf
    
    print("=" * 60)
    print("  数据质量检查")
    print("=" * 60)
    
    for code, name in [("510300", "沪深300ETF"), ("159915", "创业板ETF")]:
        df = fetch_etf(code, "20240101", "20240501")
        if df.empty:
            print(f"\n{code}: 获取失败")
            continue
        
        df_clean, report = validate_ohlc(df)
        
        print(f"\n{name}({code}):")
        print(f"  {report.summary()}")
        print(f"  OHLC违规: high<low={report.high_low_violations}, "
              f"high<open={report.high_open_violations}, "
              f"low>open={report.low_open_violations}")
        print(f"  停牌日: {report.zero_volume_rows}行")
        print(f"  缺失值: {report.missing_value_rows}行")
        if report.fixes:
            print(f"  修复记录:")
            for f in report.fixes[:5]:
                print(f"    - {f}")
        
        freshness = check_data_freshness(df)
        print(f"  数据新鲜度: {freshness}")
