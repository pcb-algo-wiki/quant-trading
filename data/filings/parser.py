"""财报 PDF / HTML 解析与落库

- parse_cninfo_pdf: pdfplumber 抽取巨潮 PDF 三大表
- normalize_financial_record: 原始 dict → FinancialRecord
- upsert_financial_record: FinancialRecord → SQLite financial_reports（幂等）
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from data.filings.cninfo import FinancialRecord


def parse_cninfo_pdf(path: Path, symbol: str, period: str) -> Optional[FinancialRecord]:
    """用 pdfplumber 解析巨潮年报 PDF，提取利润表关键科目。

    解析失败安全降级返回 None。
    """
    try:
        import pdfplumber
    except ImportError:
        print("[parser] pdfplumber 未安装，无法解析 PDF")
        return None

    try:
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join(
                page.extract_text() or "" for page in pdf.pages[:30]
            )
    except Exception as e:
        print(f"[parser] PDF 解析失败 {path}: {e}")
        return None

    if not text.strip():
        return None

    raw = _extract_income_statement_keywords(text)
    return normalize_financial_record(raw, symbol=symbol, period=period, source="cninfo_pdf")


def _extract_income_statement_keywords(text: str) -> dict:
    """从利润表文本中用正则提取关键科目数值（元）。"""

    def _find_amount(patterns: list[str]) -> Optional[float]:
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                num_str = m.group(1).replace(",", "").replace("，", "")
                try:
                    return float(num_str)
                except ValueError:
                    pass
        return None

    revenue = _find_amount([
        r"营业(?:总)?收入\s*[:|：]?\s*([\d,，]+(?:\.\d+)?)",
        r"一、营业(?:总)?收入\s+([\d,，]+(?:\.\d+)?)",
    ])
    net_profit = _find_amount([
        r"净利润\s*[:|：]?\s*([\d,，]+(?:\.\d+)?)",
        r"归属于母公司.*?净利润\s+([\d,，]+(?:\.\d+)?)",
    ])
    rd = _find_amount([
        r"研发(?:费用|支出)\s*[:|：]?\s*([\d,，]+(?:\.\d+)?)",
    ])

    return {"revenue": revenue, "net_profit": net_profit, "rd_expense": rd}


def normalize_financial_record(
    raw: dict,
    symbol: str,
    period: str,
    source: str,
) -> FinancialRecord:
    """把任意原始 dict 规范化为 FinancialRecord。"""

    def _safe_float(key: str) -> Optional[float]:
        v = raw.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return FinancialRecord(
        symbol=symbol,
        report_period=period,
        revenue=_safe_float("revenue"),
        net_profit=_safe_float("net_profit"),
        gross_margin=_safe_float("gross_margin"),
        rd_expense=_safe_float("rd_expense"),
        source=source,
    )


def upsert_financial_record(conn: sqlite3.Connection, rec: FinancialRecord) -> int:
    """把 FinancialRecord 写入 financial_reports 表（幂等，重复返回 0）。

    Returns:
        实际插入行数（0 或 1）
    """
    sql = """
    INSERT OR IGNORE INTO financial_reports
        (symbol, report_period, revenue, net_profit, gross_margin, rd_expense, source, ingested_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    now = datetime.utcnow().replace(microsecond=0).isoformat()
    cur = conn.execute(
        sql,
        (
            rec.symbol,
            rec.report_period,
            rec.revenue,
            rec.net_profit,
            rec.gross_margin,
            rec.rd_expense,
            rec.source,
            now,
        ),
    )
    conn.commit()
    return cur.rowcount
