"""Phase 2 基本面摄取与防幻觉框架测试"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── 任务 1：cninfo ────────────────────────────────────────────────────────────

def test_cninfo_fetch_returns_list():
    """fetch_cninfo_financial 应返回 list（可为空）"""
    from data.filings.cninfo import fetch_cninfo_financial
    with patch("data.filings.cninfo._fetch_via_akshare", return_value=[]):
        result = fetch_cninfo_financial("000001", years=1)
    assert isinstance(result, list)


def test_cninfo_record_schema():
    """返回的每条记录包含必要字段"""
    from data.filings.cninfo import FinancialRecord
    mock_record = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=1_000_000.0,
        net_profit=200_000.0,
        gross_margin=0.35,
        rd_expense=50_000.0,
        source="cninfo",
    )
    assert mock_record.symbol == "000001"
    assert mock_record.report_period == "2023-12-31"
    assert mock_record.revenue > 0


def test_cninfo_cache_hit(tmp_path):
    """缓存命中时不发起网络请求"""
    from data.filings.cninfo import fetch_cninfo_financial

    cache_file = tmp_path / "filings_cninfo_000001_1.json"
    cached_data = [
        {
            "symbol": "000001",
            "report_period": "2023-12-31",
            "revenue": 1e6,
            "net_profit": 2e5,
            "gross_margin": 0.35,
            "rd_expense": 5e4,
            "source": "cninfo",
        }
    ]
    cache_file.write_text(json.dumps(cached_data), encoding="utf-8")

    with patch("data.filings.cninfo.CACHE_DIR", tmp_path):
        with patch("data.filings.cninfo._fetch_via_akshare") as mock_fetch:
            result = fetch_cninfo_financial("000001", years=1)

    mock_fetch.assert_not_called()
    assert len(result) == 1
    assert result[0].symbol == "000001"


# ── 任务 2：edgar ─────────────────────────────────────────────────────────────

def test_edgar_search_returns_list():
    """search_edgar_filings 应返回 list"""
    from data.filings.edgar import search_edgar_filings
    with patch("data.filings.edgar._http_get_json", return_value={"hits": {"hits": []}}):
        result = search_edgar_filings("AAPL", form="10-K", limit=5)
    assert isinstance(result, list)


def test_edgar_filing_record_schema():
    """EdgarFiling dataclass 字段正确"""
    from data.filings.edgar import EdgarFiling
    f = EdgarFiling(
        cik="0000320193",
        accession="0000320193-24-000123",
        form="10-K",
        filed_at="2024-11-01",
        url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/",
        local_path=None,
    )
    assert f.cik == "0000320193"
    assert f.form == "10-K"


def test_edgar_search_parses_hits():
    """_parse_hits 从 EFTS JSON 正确提取 EdgarFiling"""
    from data.filings.edgar import _parse_hits
    raw = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "entity_id": "0000320193",
                        "accession_no": "0000320193-24-000123",
                        "form_type": "10-K",
                        "file_date": "2024-11-01",
                        "period_of_report": "2024-09-28",
                    }
                }
            ]
        }
    }
    results = _parse_hits(raw)
    assert len(results) == 1
    assert results[0].form == "10-K"
    assert "0000320193" in results[0].cik


# ── 任务 3：parser ────────────────────────────────────────────────────────────

def test_parse_empty_pdf_returns_none(tmp_path):
    """空 PDF 文件解析应安全返回 None，不抛异常"""
    from data.filings.parser import parse_cninfo_pdf
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    result = parse_cninfo_pdf(empty_pdf, symbol="000001", period="2023-12-31")
    assert result is None


def test_normalize_financial_record():
    """normalize 把原始 dict 映射到 FinancialRecord"""
    from data.filings.parser import normalize_financial_record
    from data.filings.cninfo import FinancialRecord
    raw = {
        "revenue": 1_000_000.0,
        "net_profit": 200_000.0,
        "gross_margin": 0.35,
        "rd_expense": 50_000.0,
    }
    rec = normalize_financial_record(raw, symbol="000001", period="2023-12-31", source="cninfo")
    assert isinstance(rec, FinancialRecord)
    assert rec.revenue == 1_000_000.0
    assert rec.source == "cninfo"


def test_upsert_financial_record_to_db(tmp_path):
    """FinancialRecord 落库后可查询到，且幂等"""
    from data_store.schema import create_schema
    from data.filings.parser import upsert_financial_record
    from data.filings.cninfo import FinancialRecord

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)

    rec = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=1_000_000.0,
        net_profit=200_000.0,
        gross_margin=0.35,
        rd_expense=50_000.0,
        source="cninfo",
    )
    n = upsert_financial_record(conn, rec)
    assert n == 1

    rows = conn.execute("SELECT * FROM financial_reports WHERE symbol='000001'").fetchall()
    assert len(rows) == 1
    assert rows[0]["net_profit"] == 200_000.0

    # 幂等：二次插入不增加行数
    n2 = upsert_financial_record(conn, rec)
    assert n2 == 0
    rows2 = conn.execute("SELECT * FROM financial_reports WHERE symbol='000001'").fetchall()
    assert len(rows2) == 1


# ── 任务 4：prompts ───────────────────────────────────────────────────────────

def test_roles_template_fields():
    """ROLES 模板包含 5 个必要部分"""
    from knowledge.prompts import build_roles_prompt
    prompt = build_roles_prompt(
        role="财报分析师",
        objective="核实净利润数据",
        limits="只参考公开披露数据",
        expectations="输出JSON格式核实结果",
        safeguards="数字出入超5%需标注存疑",
    )
    for keyword in ["Role:", "Objective:", "Limits:", "Expectations:", "Safeguards:"]:
        assert keyword in prompt, f"缺少 {keyword}"


def test_score_moat_returns_dict():
    """score_moat 无 LLM 也能返回包含各维度的 dict"""
    from knowledge.prompts import score_moat
    from data.filings.cninfo import FinancialRecord
    rec = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=5e9,
        net_profit=1e9,
        gross_margin=0.45,
        rd_expense=2e8,
        source="cninfo",
    )
    result = score_moat(rec)
    assert isinstance(result, dict)
    assert "total_score" in result
    assert 0.0 <= result["total_score"] <= 5.0
    assert "dimensions" in result


# ── 任务 5：validator ─────────────────────────────────────────────────────────

def test_validator_passes_consistent_record():
    """数字一致、有来源的记录应通过校验"""
    from knowledge.validator import FinancialValidator
    from data.filings.cninfo import FinancialRecord
    validator = FinancialValidator()
    rec = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=5_000_000.0,
        net_profit=1_000_000.0,
        gross_margin=0.45,
        rd_expense=200_000.0,
        source="cninfo",
    )
    result = validator.validate(rec)
    assert result.passed is True
    assert result.confidence >= 0.7
    assert len(result.issues) == 0


def test_validator_flags_negative_revenue():
    """负营收应触发校验失败"""
    from knowledge.validator import FinancialValidator
    from data.filings.cninfo import FinancialRecord
    validator = FinancialValidator()
    rec = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=-100.0,
        net_profit=50.0,
        gross_margin=0.35,
        rd_expense=10.0,
        source="cninfo",
    )
    result = validator.validate(rec)
    assert result.passed is False
    assert any("负" in issue or "revenue" in issue.lower() for issue in result.issues)


def test_validator_flags_impossible_gross_margin():
    """毛利率 > 1.0 应触发校验失败"""
    from knowledge.validator import FinancialValidator
    from data.filings.cninfo import FinancialRecord
    validator = FinancialValidator()
    rec = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=1_000_000.0,
        net_profit=200_000.0,
        gross_margin=1.5,
        rd_expense=50_000.0,
        source="cninfo",
    )
    result = validator.validate(rec)
    assert result.passed is False
    assert any("毛利率" in issue or "gross_margin" in issue.lower() for issue in result.issues)


def test_validator_flags_missing_source():
    """空 source 应触发低置信度"""
    from knowledge.validator import FinancialValidator
    from data.filings.cninfo import FinancialRecord
    validator = FinancialValidator()
    rec = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=1_000_000.0,
        net_profit=200_000.0,
        gross_margin=0.35,
        rd_expense=50_000.0,
        source="",
    )
    result = validator.validate(rec)
    assert result.confidence < 0.6


# ── 任务 6：ingest_filings ────────────────────────────────────────────────────

def test_ingest_filings_run_returns_dict(tmp_path):
    """run() 在 mock 环境下返回包含 inserted 字段的 dict"""
    from data_store.schema import create_schema
    from data.filings.cninfo import FinancialRecord

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)

    mock_record = FinancialRecord(
        symbol="000001",
        report_period="2023-12-31",
        revenue=5e9,
        net_profit=1e9,
        gross_margin=0.45,
        rd_expense=2e8,
        source="cninfo",
    )

    with patch("scripts.ingest_filings.get_db_connection", return_value=conn):
        with patch("scripts.ingest_filings.fetch_cninfo_financial", return_value=[mock_record]):
            with patch("scripts.ingest_filings._get_symbols", return_value=["000001"]):
                from scripts import ingest_filings
                import importlib
                importlib.reload(ingest_filings)
                result = ingest_filings.run()

    assert isinstance(result, dict)
    assert "inserted" in result
    assert result["inserted"] >= 0


def test_ingest_filings_skips_invalid_records(tmp_path):
    """校验不通过的记录不落库"""
    from data_store.schema import create_schema
    from data.filings.cninfo import FinancialRecord

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)

    bad_record = FinancialRecord(
        symbol="000002",
        report_period="2023-12-31",
        revenue=-1.0,
        net_profit=None,
        gross_margin=None,
        rd_expense=None,
        source="cninfo",
    )

    with patch("scripts.ingest_filings.get_db_connection", return_value=conn):
        with patch("scripts.ingest_filings.fetch_cninfo_financial", return_value=[bad_record]):
            with patch("scripts.ingest_filings._get_symbols", return_value=["000002"]):
                from scripts import ingest_filings
                import importlib
                importlib.reload(ingest_filings)
                result = ingest_filings.run()

    rows = conn.execute("SELECT * FROM financial_reports").fetchall()
    assert len(rows) == 0
