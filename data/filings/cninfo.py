"""巨潮财报抓取

优先 AkShare；失败时记录警告并返回空列表。
结果缓存到 CACHE_DIR/filings_cninfo_{symbol}_{years}.json。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


@dataclass
class FinancialRecord:
    symbol: str
    report_period: str          # "YYYY-MM-DD"（报告期末）
    revenue: Optional[float]    # 营业收入（元）
    net_profit: Optional[float]
    gross_margin: Optional[float]   # 0–1 小数
    rd_expense: Optional[float]
    source: str                 # "cninfo" | "edgar"


def _fetch_via_akshare(symbol: str, years: int) -> list[dict]:
    """调用 akshare 抓取利润表，返回原始行列表。失败返回 []。"""
    try:
        import akshare as ak
        df = ak.stock_financial_benefit_ths(symbol=symbol, indicator="按年度")
        if df is None or df.empty:
            return []
        rows = []
        for _, row in df.head(years).iterrows():
            rows.append(dict(row))
        return rows
    except Exception as e:
        print(f"[cninfo] AkShare 失败 {symbol}: {e}")
        return []


def _parse_akshare_row(symbol: str, raw: dict) -> Optional[FinancialRecord]:
    """把 akshare 利润表行映射到 FinancialRecord。"""
    period = raw.get("报告期", raw.get("REPORT_DATE", ""))
    if not period:
        return None
    try:
        period = str(period)[:10]
    except Exception:
        return None

    def _float(key_candidates):
        for k in key_candidates:
            v = raw.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return None

    revenue = _float(["营业总收入", "营业收入", "TOTAL_OPERATE_INCOME"])
    net_profit = _float(["净利润", "归母净利润", "PARENT_NETPROFIT"])
    rd = _float(["研发费用", "研发支出", "RESEARCH_EXPENSE"])
    gross_margin_raw = _float(["毛利率", "销售毛利率"])
    gross_margin = gross_margin_raw / 100 if gross_margin_raw is not None else None

    return FinancialRecord(
        symbol=symbol,
        report_period=period,
        revenue=revenue,
        net_profit=net_profit,
        gross_margin=gross_margin,
        rd_expense=rd,
        source="cninfo",
    )


def fetch_cninfo_financial(symbol: str, years: int = 3) -> list[FinancialRecord]:
    """抓取 A 股财报，优先读缓存，否则调 AkShare。

    Args:
        symbol: A股代码，如 "000001"
        years: 抓取最近 N 年年报

    Returns:
        FinancialRecord 列表（可为空）
    """
    cache_file = CACHE_DIR / f"filings_cninfo_{symbol}_{years}.json"

    if cache_file.exists():
        age_hours = (datetime.now().timestamp() - cache_file.stat().st_mtime) / 3600
        if age_hours < 24:
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                return [FinancialRecord(**r) for r in data]
            except Exception:
                pass

    raw_rows = _fetch_via_akshare(symbol, years)
    records = []
    for row in raw_rows:
        rec = _parse_akshare_row(symbol, row)
        if rec:
            records.append(rec)

    try:
        cache_file.write_text(
            json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[cninfo] 缓存写入失败: {e}")

    return records
