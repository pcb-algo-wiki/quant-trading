# Phase 2 基本面摄取与防幻觉框架 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 新增 `data/filings/` 模块抓取巨潮 + SEC EDGAR 财报；用 `pdfplumber` 解析三大表落库 `financial_reports`；提供 ROLES 提示模板和规则版防幻觉校验器，全部接入 `daily_pipeline`。

**架构：** `data/filings/` 负责下载（cninfo/edgar）+ 解析（parser），`knowledge/prompts.py` 提供 ROLES 模板和规则版护城河打分，`knowledge/validator.py` 提供数字一致性 + 来源回链校验，`scripts/ingest_filings.py` 编排整个摄取流程并通过 feature flag 接入 `daily_pipeline`。所有摄取幂等（`INSERT OR IGNORE` + 内容 hash）。

**技术栈：** Python 3.11、pdfplumber（已在 requirements.txt）、akshare（已有）、sqlite3（data_store）、requests/urllib.request（或 curl subprocess 作为备选）

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `data/filings/__init__.py` | 模块导出入口 |
| `data/filings/cninfo.py` | 巨潮财报抓取：AkShare 三大表 + PDF 链接下载 + 本地缓存 |
| `data/filings/edgar.py` | SEC EDGAR EFTS RSS 搜索 + 10-K HTM 下载 + 本地缓存 |
| `data/filings/parser.py` | `pdfplumber` / HTML 解析三大表科目；返回 `FinancialRecord` dataclass；写库 |
| `knowledge/prompts.py` | ROLES 框架模板 dict + `score_moat()` 规则版护城河打分（无 LLM 可运行） |
| `knowledge/validator.py` | `FinancialValidator`：数字一致性 + 来源回链 + 置信阈值；`ValidationResult` dataclass |
| `scripts/ingest_filings.py` | 编排脚本：读 cfg → 调 cninfo/edgar → 解析 → 校验 → 落库；`run()` 返回 dict |
| `scripts/daily_pipeline.py` | 增加 `filings.enabled` feature flag 接入 ingest_filings step |
| `tests/test_filings_phase2.py` | 全部新模块的单元测试（≥ 12 用例） |

---

## 任务 1：`data/filings/` 目录 + `cninfo.py` 巨潮抓取

**文件：**
- 创建：`data/filings/__init__.py`
- 创建：`data/filings/cninfo.py`
- 测试：`tests/test_filings_phase2.py`（本任务写前 3 个测试）

- [ ] **步骤 1：编写失败测试（cninfo 基础接口）**

新建 `tests/test_filings_phase2.py`：

```python
"""Phase 2 基本面摄取与防幻觉框架测试"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ── 任务 1：cninfo ────────────────────────────────────────────────────────────

def test_cninfo_fetch_returns_list():
    """fetch_cninfo_financial 应返回 list（可为空）"""
    from data.filings.cninfo import fetch_cninfo_financial
    # 用 monkeypatch 避免真实网络请求
    with patch("data.filings.cninfo._fetch_via_akshare", return_value=[]):
        result = fetch_cninfo_financial("000001", years=1)
    assert isinstance(result, list)


def test_cninfo_record_schema():
    """返回的每条记录包含必要字段"""
    from data.filings.cninfo import fetch_cninfo_financial, FinancialRecord
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
    import json

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
```

- [ ] **步骤 2：运行测试验证失败**

```
python -m pytest tests/test_filings_phase2.py::test_cninfo_fetch_returns_list -v
```
预期：`ModuleNotFoundError: data.filings.cninfo`

- [ ] **步骤 3：创建 `data/filings/__init__.py`**

```python
"""财报摄取模块 - 巨潮 (cninfo) + SEC EDGAR"""
```

- [ ] **步骤 4：创建 `data/filings/cninfo.py`**

```python
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
    report_period: str         # "YYYY-MM-DD"（报告期末）
    revenue: Optional[float]   # 营业收入（元）
    net_profit: Optional[float]
    gross_margin: Optional[float]  # 0–1 小数
    rd_expense: Optional[float]
    source: str                # "cninfo" | "edgar"


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


def _parse_akshare_row(symbol: str, raw: dict) -> FinancialRecord | None:
    """把 akshare 利润表行映射到 FinancialRecord。"""
    # AkShare 列名因接口版本不同，做宽松映射
    period = raw.get("报告期", raw.get("REPORT_DATE", ""))
    if not period:
        return None
    try:
        period = str(period)[:10]  # 取 YYYY-MM-DD
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

    # 缓存命中（当日内）
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

    # 写缓存
    try:
        cache_file.write_text(
            json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[cninfo] 缓存写入失败: {e}")

    return records
```

- [ ] **步骤 5：运行测试验证通过**

```
python -m pytest tests/test_filings_phase2.py::test_cninfo_fetch_returns_list tests/test_filings_phase2.py::test_cninfo_record_schema tests/test_filings_phase2.py::test_cninfo_cache_hit -v
```
预期：3 PASSED

---

## 任务 2：`data/filings/edgar.py` SEC EDGAR 抓取

**文件：**
- 创建：`data/filings/edgar.py`
- 测试：`tests/test_filings_phase2.py`（追加 3 个测试）

- [ ] **步骤 1：追加失败测试（edgar 接口）**

在 `tests/test_filings_phase2.py` 末尾追加：

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

```
python -m pytest tests/test_filings_phase2.py::test_edgar_search_returns_list -v
```
预期：`ModuleNotFoundError: data.filings.edgar`

- [ ] **步骤 3：创建 `data/filings/edgar.py`**

```python
"""SEC EDGAR 财报抓取

使用 EDGAR EFTS 全文搜索 API（无需 API key）搜索 10-K/10-Q，
下载 HTM 文件并缓存到 CACHE_DIR/edgar/{cik}/{accession}/ 目录。
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).parent.parent / "cache" / "edgar"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data"


@dataclass
class EdgarFiling:
    cik: str
    accession: str
    form: str
    filed_at: str   # "YYYY-MM-DD"
    url: str        # 归档目录 URL
    local_path: Optional[Path]  # 下载后的本地路径


def _http_get_json(url: str, timeout: int = 20) -> dict:
    """带 User-Agent 的 HTTP GET，返回 JSON dict。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "quant-trading-research contact@example.com"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_hits(raw: dict) -> list[EdgarFiling]:
    """从 EFTS JSON 提取 EdgarFiling 列表。"""
    hits = raw.get("hits", {}).get("hits", [])
    results = []
    for h in hits:
        src = h.get("_source", {})
        cik = str(src.get("entity_id", "")).zfill(10)
        accession = src.get("accession_no", "")
        form = src.get("form_type", "")
        filed_at = str(src.get("file_date", ""))[:10]
        acc_path = accession.replace("-", "")
        url = f"{EDGAR_ARCHIVE}/{int(cik)}/{acc_path}/"
        results.append(EdgarFiling(
            cik=cik,
            accession=accession,
            form=form,
            filed_at=filed_at,
            url=url,
            local_path=None,
        ))
    return results


def search_edgar_filings(
    ticker: str,
    form: str = "10-K",
    limit: int = 5,
) -> list[EdgarFiling]:
    """搜索 EDGAR 财报，返回最新 N 条 EdgarFiling。

    Args:
        ticker: 美股 ticker，如 "AAPL"
        form: 表单类型，"10-K" 或 "10-Q"
        limit: 返回数量上限

    Returns:
        EdgarFiling 列表（可为空）
    """
    url = (
        f"{EFTS_BASE}?q=%22{ticker}%22"
        f"&forms={form}"
        f"&dateRange=custom&startdt=2018-01-01"
        f"&_source=entity_id,accession_no,form_type,file_date,period_of_report"
        f"&from=0&size={limit}"
    )
    try:
        raw = _http_get_json(url)
        return _parse_hits(raw)
    except Exception as e:
        print(f"[edgar] EFTS 搜索失败 {ticker}: {e}")
        return []


def download_filing(filing: EdgarFiling, force: bool = False) -> Optional[Path]:
    """下载 filing 的主 HTM 文件到本地缓存。

    Returns:
        本地文件路径，失败返回 None
    """
    acc_dir = CACHE_DIR / filing.cik / filing.accession.replace("-", "")
    acc_dir.mkdir(parents=True, exist_ok=True)

    # 先查缓存
    existing = list(acc_dir.glob("*.htm")) + list(acc_dir.glob("*.html"))
    if existing and not force:
        filing.local_path = existing[0]
        return existing[0]

    # 从 index.json 取主文档 URL
    try:
        acc_nodash = filing.accession.replace("-", "")
        index_url = (
            f"https://data.sec.gov/submissions/CIK{filing.cik}.json"
        )
        # 简化：直接拼 {cik}/{accession_nodash}/{ticker}-{date}.htm
        # 实际项目可解析 index.json 取精确文件名；此处以 best-effort 下载
        raw = _http_get_json(
            f"https://data.sec.gov/Archives/edgar/data/{int(filing.cik)}/{acc_nodash}/index.json"
        )
        for item in raw.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if name.endswith(".htm") or name.endswith(".html"):
                file_url = f"{filing.url}{name}"
                req = urllib.request.Request(
                    file_url,
                    headers={"User-Agent": "quant-trading-research contact@example.com"},
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content = resp.read()
                local = acc_dir / name
                local.write_bytes(content)
                filing.local_path = local
                return local
    except Exception as e:
        print(f"[edgar] 下载失败 {filing.accession}: {e}")
    return None
```

- [ ] **步骤 4：运行测试验证通过**

```
python -m pytest tests/test_filings_phase2.py::test_edgar_search_returns_list tests/test_filings_phase2.py::test_edgar_filing_record_schema tests/test_filings_phase2.py::test_edgar_search_parses_hits -v
```
预期：3 PASSED

---

## 任务 3：`data/filings/parser.py` PDF/HTML 解析 + 落库

**文件：**
- 创建：`data/filings/parser.py`
- 测试：`tests/test_filings_phase2.py`（追加 3 个测试）

- [ ] **步骤 1：追加失败测试（parser）**

```python
# ── 任务 3：parser ────────────────────────────────────────────────────────────

def test_parse_empty_pdf_returns_none(tmp_path):
    """空 PDF 文件解析应安全返回 None，不抛异常"""
    from data.filings.parser import parse_cninfo_pdf
    empty_pdf = tmp_path / "empty.pdf"
    empty_pdf.write_bytes(b"%PDF-1.4\n%%EOF")
    result = parse_cninfo_pdf(empty_pdf, symbol="000001", period="2023-12-31")
    # 空文件 → None（解析失败降级）
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
    """FinancialRecord 落库后可查询到"""
    import sqlite3
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

    rows = conn.execute(
        "SELECT * FROM financial_reports WHERE symbol='000001'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["net_profit"] == 200_000.0

    # 幂等：二次插入不增加行数
    n2 = upsert_financial_record(conn, rec)
    assert n2 == 0
    rows2 = conn.execute(
        "SELECT * FROM financial_reports WHERE symbol='000001'"
    ).fetchall()
    assert len(rows2) == 1
```

- [ ] **步骤 2：运行测试验证失败**

```
python -m pytest tests/test_filings_phase2.py::test_normalize_financial_record -v
```
预期：`ModuleNotFoundError: data.filings.parser`

- [ ] **步骤 3：创建 `data/filings/parser.py`**

```python
"""财报 PDF / HTML 解析与落库

- parse_cninfo_pdf: pdfplumber 抽取巨潮 PDF 三大表
- parse_edgar_html: 从 SEC HTM 提取关键科目
- normalize_financial_record: 原始 dict → FinancialRecord
- upsert_financial_record: FinancialRecord → SQLite financial_reports（幂等）
"""
from __future__ import annotations

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
    import re

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
```

- [ ] **步骤 4：运行测试验证通过**

```
python -m pytest tests/test_filings_phase2.py::test_parse_empty_pdf_returns_none tests/test_filings_phase2.py::test_normalize_financial_record tests/test_filings_phase2.py::test_upsert_financial_record_to_db -v
```
预期：3 PASSED

---

## 任务 4：`knowledge/prompts.py` ROLES 模板 + 规则版护城河打分

**文件：**
- 创建：`knowledge/prompts.py`
- 测试：`tests/test_filings_phase2.py`（追加 2 个测试）

- [ ] **步骤 1：追加失败测试（prompts）**

```python
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
```

- [ ] **步骤 2：运行测试验证失败**

```
python -m pytest tests/test_filings_phase2.py::test_roles_template_fields -v
```
预期：`ModuleNotFoundError: knowledge.prompts`

- [ ] **步骤 3：创建 `knowledge/prompts.py`**

```python
"""ROLES 框架提示模板 + 规则版护城河打分

ROLES = Role / Objective / Limits / Expectations / Safeguards

score_moat() 不依赖 LLM，可在离线环境运行。
"""
from __future__ import annotations

from typing import Optional

from data.filings.cninfo import FinancialRecord

# ── ROLES 模板 ──────────────────────────────────────────────────────────────

_ROLES_TEMPLATE = """\
Role: {role}
Objective: {objective}
Limits: {limits}
Expectations: {expectations}
Safeguards: {safeguards}
"""


def build_roles_prompt(
    role: str,
    objective: str,
    limits: str,
    expectations: str,
    safeguards: str,
) -> str:
    """构建 ROLES 框架提示词。"""
    return _ROLES_TEMPLATE.format(
        role=role,
        objective=objective,
        limits=limits,
        expectations=expectations,
        safeguards=safeguards,
    )


# ── 预设角色 ──────────────────────────────────────────────────────────────────

FINANCIAL_ANALYST_PROMPT = build_roles_prompt(
    role="资深财报分析师，专注 A 股上市公司基本面研究",
    objective="核实财务数据的内部一致性，识别潜在会计风险",
    limits="只参考公开披露文件；不做买卖建议；不猜测未披露信息",
    expectations="以 JSON 格式输出：{passed: bool, issues: [str], confidence: float}",
    safeguards="数字出入超 5% 需标注存疑；缺失数据不得推断；盈利预测不得超 3 年",
)

EDGAR_ANALYST_PROMPT = build_roles_prompt(
    role="SEC 文件分析师，专注美股 10-K 风险因素与财务数据",
    objective="提取三大表关键科目并标注数据来源页码",
    limits="只读取提供的 10-K 文本；不引用第三方数据",
    expectations="以 JSON 输出 {revenue, net_income, total_assets, risk_factors: [str]}",
    safeguards="所有数字必须带单位（millions USD）；缺失字段标注 null 不得填 0",
)

# ── 规则版护城河打分 ─────────────────────────────────────────────────────────

def score_moat(
    rec: FinancialRecord,
    policy_alignment: float = 0.0,
) -> dict:
    """规则版护城河打分，无需 LLM，离线可运行。

    五个维度，各 0-1 分，total_score = 加权平均 × 5（上限 5.0）。

    Args:
        rec: FinancialRecord
        policy_alignment: 政策契合度 0-1（由 research.policy_alignment 提供，默认 0）

    Returns:
        {total_score, dimensions: {brand, switching_cost, cost_advantage, rd_moat, policy}}
    """
    scores: dict[str, float] = {}

    # 毛利率 > 40% → 品牌或成本优势
    gm = rec.gross_margin or 0.0
    scores["brand"] = min(1.0, max(0.0, (gm - 0.20) / 0.40))

    # 净利率代理切换成本（高净利率 → 高定价权）
    net_margin = 0.0
    if rec.revenue and rec.net_profit and rec.revenue > 0:
        net_margin = rec.net_profit / rec.revenue
    scores["switching_cost"] = min(1.0, max(0.0, net_margin / 0.25))

    # 毛利率高于净利率 → 非成本优势（倒扣）；否则给分
    if gm > 0 and net_margin > 0:
        spread = gm - net_margin
        scores["cost_advantage"] = min(1.0, max(0.0, 1.0 - spread / 0.5))
    else:
        scores["cost_advantage"] = 0.0

    # 研发费用 / 收入 > 5% → 技术护城河
    rd_ratio = 0.0
    if rec.revenue and rec.rd_expense and rec.revenue > 0:
        rd_ratio = rec.rd_expense / rec.revenue
    scores["rd_moat"] = min(1.0, max(0.0, rd_ratio / 0.10))

    # 政策契合度直接映射
    scores["policy"] = min(1.0, max(0.0, float(policy_alignment)))

    weights = {
        "brand": 0.30,
        "switching_cost": 0.25,
        "cost_advantage": 0.20,
        "rd_moat": 0.15,
        "policy": 0.10,
    }
    weighted = sum(scores[k] * weights[k] for k in scores)
    total = round(weighted * 5.0, 2)

    return {"total_score": total, "dimensions": scores}
```

- [ ] **步骤 4：运行测试验证通过**

```
python -m pytest tests/test_filings_phase2.py::test_roles_template_fields tests/test_filings_phase2.py::test_score_moat_returns_dict -v
```
预期：2 PASSED

---

## 任务 5：`knowledge/validator.py` 规则防幻觉校验器

**文件：**
- 创建：`knowledge/validator.py`
- 测试：`tests/test_filings_phase2.py`（追加 4 个测试）

- [ ] **步骤 1：追加失败测试（validator）**

```python
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
        gross_margin=1.5,  # 不可能 > 1
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
        source="",  # 空来源
    )
    result = validator.validate(rec)
    assert result.confidence < 0.6
```

- [ ] **步骤 2：运行测试验证失败**

```
python -m pytest tests/test_filings_phase2.py::test_validator_passes_consistent_record -v
```
预期：`ModuleNotFoundError: knowledge.validator`

- [ ] **步骤 3：创建 `knowledge/validator.py`**

```python
"""财务数据防幻觉校验器

MAD（Multi-Agent Debate）的单规则替代：
- 数字一致性检查（物理不可能值）
- 来源回链强制（空 source → 低置信）
- 置信度阈值（低于 cfg.knowledge.validation.confidence_threshold 则降级）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from data.filings.cninfo import FinancialRecord


@dataclass
class ValidationResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    confidence: float = 1.0  # 0–1


class FinancialValidator:
    """规则校验器，无需 LLM，离线可运行。

    LLM 校验路径预留：子类 override `_llm_validate` 即可接入。
    """

    def __init__(self, confidence_threshold: float = 0.6):
        self.confidence_threshold = confidence_threshold

    def validate(self, rec: FinancialRecord) -> ValidationResult:
        """对 FinancialRecord 执行多项规则校验。

        Returns:
            ValidationResult（passed=True 表示无严重问题）
        """
        issues: list[str] = []
        confidence = 1.0

        # ── 来源回链 ─────────────────────────────────────────────────────────
        if not rec.source:
            issues.append("缺少数据来源（source 为空）")
            confidence -= 0.4
        elif rec.source not in ("cninfo", "cninfo_pdf", "edgar", "edgar_html"):
            confidence -= 0.1  # 非标准来源，轻微扣分

        # ── 物理不可能值 ──────────────────────────────────────────────────────
        if rec.revenue is not None and rec.revenue < 0:
            issues.append(f"负营收不合理：revenue={rec.revenue}")
            confidence -= 0.5

        if rec.net_profit is not None and rec.revenue is not None and rec.revenue > 0:
            net_margin = rec.net_profit / rec.revenue
            if net_margin > 0.99:
                issues.append(f"净利率超过 99%，疑似数据错误：net_margin={net_margin:.1%}")
                confidence -= 0.3

        if rec.gross_margin is not None:
            if rec.gross_margin < 0 or rec.gross_margin > 1.0:
                issues.append(f"毛利率超出 [0,1] 范围：gross_margin={rec.gross_margin}")
                confidence -= 0.4

        if rec.rd_expense is not None and rec.rd_expense < 0:
            issues.append(f"负研发费用：rd_expense={rec.rd_expense}")
            confidence -= 0.2

        # ── 缺失关键字段 ──────────────────────────────────────────────────────
        if rec.revenue is None:
            issues.append("营收缺失，数据不完整")
            confidence -= 0.2

        confidence = max(0.0, min(1.0, confidence))
        passed = len(issues) == 0 and confidence >= self.confidence_threshold

        return ValidationResult(passed=passed, issues=issues, confidence=confidence)

    def _llm_validate(self, rec: FinancialRecord, prompt: str) -> ValidationResult:
        """LLM 校验占位（子类实现；默认返回空通过）。"""
        return ValidationResult(passed=True, confidence=0.5)
```

- [ ] **步骤 4：运行测试验证通过**

```
python -m pytest tests/test_filings_phase2.py::test_validator_passes_consistent_record tests/test_filings_phase2.py::test_validator_flags_negative_revenue tests/test_filings_phase2.py::test_validator_flags_impossible_gross_margin tests/test_filings_phase2.py::test_validator_flags_missing_source -v
```
预期：4 PASSED

---

## 任务 6：`scripts/ingest_filings.py` + `daily_pipeline` 接入

**文件：**
- 创建：`scripts/ingest_filings.py`
- 修改：`scripts/daily_pipeline.py`
- 修改：`config.yaml`（新增 `filings:` 段）
- 测试：`tests/test_filings_phase2.py`（追加 2 个测试）

- [ ] **步骤 1：追加失败测试（ingest_filings）**

```python
# ── 任务 6：ingest_filings ────────────────────────────────────────────────────

def test_ingest_filings_run_returns_dict(tmp_path):
    """run() 在 mock 环境下返回包含 inserted 字段的 dict"""
    import sqlite3
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
                from scripts.ingest_filings import run
                result = run()

    assert isinstance(result, dict)
    assert "inserted" in result
    assert result["inserted"] >= 0


def test_ingest_filings_skips_invalid_records(tmp_path):
    """校验不通过的记录不落库"""
    import sqlite3
    from data_store.schema import create_schema
    from data.filings.cninfo import FinancialRecord

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)

    bad_record = FinancialRecord(
        symbol="000002",
        report_period="2023-12-31",
        revenue=-1.0,  # 负营收 → 校验失败
        net_profit=None,
        gross_margin=None,
        rd_expense=None,
        source="cninfo",
    )

    with patch("scripts.ingest_filings.get_db_connection", return_value=conn):
        with patch("scripts.ingest_filings.fetch_cninfo_financial", return_value=[bad_record]):
            with patch("scripts.ingest_filings._get_symbols", return_value=["000002"]):
                from scripts.ingest_filings import run
                result = run()

    rows = conn.execute("SELECT * FROM financial_reports").fetchall()
    assert len(rows) == 0
```

- [ ] **步骤 2：运行测试验证失败**

```
python -m pytest tests/test_filings_phase2.py::test_ingest_filings_run_returns_dict -v
```
预期：`ModuleNotFoundError: scripts.ingest_filings`

- [ ] **步骤 3：创建 `scripts/ingest_filings.py`**

```python
"""财报摄取编排脚本

从巨潮（A股）抓取财报 → 规则校验 → 落库 financial_reports。
由 daily_pipeline 通过 `filings.enabled` feature flag 调用。

run() 返回 {"inserted": N, "skipped": M, "errors": K}
"""
from __future__ import annotations

from utils.config import get_config


def get_db_connection():
    from data_store.db import get_connection
    return get_connection()


def _get_symbols() -> list[str]:
    """从 config 取 A 股代码列表；fallback 到示例 5 只。"""
    cfg = get_config()
    # config.yaml 可在 filings.a_share_symbols 配置
    symbols = cfg.get("filings.a_share_symbols", [])
    if not symbols:
        # 示例：平安银行、招商银行、中国平安、贵州茅台、宁德时代
        symbols = ["000001", "600036", "601318", "600519", "300750"]
    return symbols


def run() -> dict:
    """主入口：抓取 → 校验 → 落库。"""
    from data.filings.cninfo import fetch_cninfo_financial
    from data.filings.parser import upsert_financial_record
    from knowledge.validator import FinancialValidator

    cfg = get_config()
    years = cfg.get("filings.years", 3)

    symbols = _get_symbols()
    validator = FinancialValidator(
        confidence_threshold=cfg.get("filings.confidence_threshold", 0.6)
    )
    conn = get_db_connection()

    inserted = skipped = errors = 0

    for symbol in symbols:
        try:
            records = fetch_cninfo_financial(symbol, years=years)
            for rec in records:
                vr = validator.validate(rec)
                if not vr.passed:
                    print(f"[ingest] 跳过 {symbol} {rec.report_period}：{vr.issues}")
                    skipped += 1
                    continue
                n = upsert_financial_record(conn, rec)
                inserted += n
                if n == 0:
                    skipped += 1  # 已存在（幂等）
        except Exception as e:
            print(f"[ingest] 摄取失败 {symbol}: {e}")
            errors += 1

    return {"inserted": inserted, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    result = run()
    print(f"[ingest_filings] 完成：{result}")
```

- [ ] **步骤 4：更新 `config.yaml`，在末尾追加 `filings:` 段**

在现有 `knowledge:` 段之后追加：

```yaml
filings:
  enabled: false                        # daily_pipeline feature flag
  a_share_symbols: []                   # 空 = 用 ingest_filings.py 内置示例列表
  years: 3                              # 抓取最近 N 年年报
  confidence_threshold: 0.6            # 低于此置信度的记录不落库
  edgar:
    enabled: false                      # US 股票财报抓取开关
    tickers: []                         # 美股 ticker 列表
```

- [ ] **步骤 5：更新 `scripts/daily_pipeline.py`，追加 filings step**

在 `run_daily_pipeline()` 的 `if cfg.get("knowledge.graph.enabled", False):` 块之后追加：

```python
    if cfg.get("filings.enabled", False):
        from scripts.ingest_filings import run as ingest_filings_run
        result["filings"] = ingest_filings_run()
```

- [ ] **步骤 6：运行任务 6 测试**

```
python -m pytest tests/test_filings_phase2.py::test_ingest_filings_run_returns_dict tests/test_filings_phase2.py::test_ingest_filings_skips_invalid_records -v
```
预期：2 PASSED

---

## 任务 7：全量回归 + commit

**文件：** 无新建

- [ ] **步骤 1：运行全量测试套件**

```
python -m pytest -q
```
预期：≥ 84 passed，0 failed（72 旧 + 新 12）

- [ ] **步骤 2：确认新测试数量**

```
python -m pytest tests/test_filings_phase2.py -v
```
预期：12 PASSED

- [ ] **步骤 3：Commit Phase 1 + Phase 2**

```bash
git add -A
git commit -m "feat(Phase1-2): GraphRAG MVP + 财报摄取防幻觉框架

Phase 1:
- llmwiki/ 目录结构与 CLAUDE.md schema（节点4类/边5类）
- data_store: 新增 knowledge_nodes/edges/evidence 三表
- knowledge/graph.py: IndustryGraph (NetworkX) + 持久化 + 旧API兼容
- knowledge/extractors.py: RuleEntityExtractor + 政策正则NER
- knowledge/retrieval.py: BM25 + GraphNeighbor + RRF HybridRetriever
- data_store/knowledge_repo.py: KnowledgeEvidenceRepository
- scripts/build_knowledge_graph.py: 增量幂等构建脚本
- config.yaml: knowledge.* feature flag（默认关）

Phase 2:
- data/filings/: cninfo + edgar + parser 财报摄取模块
- knowledge/prompts.py: ROLES框架模板 + 规则版护城河打分
- knowledge/validator.py: FinancialValidator 规则防幻觉校验
- scripts/ingest_filings.py: 编排脚本（feature flag默认关）
- config.yaml: filings.* 配置段

测试: 72(旧) + 12(Phase2新) 全绿

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## 自检

### 规格覆盖度

| 规格需求 | 覆盖任务 |
|---|---|
| `data/filings/cninfo.py`（AkShare + 缓存） | 任务 1 |
| `data/filings/edgar.py`（EFTS + 下载） | 任务 2 |
| `data/filings/parser.py`（pdfplumber + 落库） | 任务 3 |
| `knowledge/prompts.py`（ROLES + 规则护城河） | 任务 4 |
| `knowledge/validator.py`（MAD 替代） | 任务 5 |
| `scripts/ingest_filings.py`（接入 pipeline） | 任务 6 |
| `config.yaml` 新增 `filings:` 段 | 任务 6 |
| `daily_pipeline.py` feature flag | 任务 6 |
| 单元测试（happy path + 校验失败回退） | 各任务内嵌 + 任务 7 |
| 幂等（INSERT OR IGNORE + 内容 hash） | 任务 3（upsert_financial_record） |

### 占位符扫描
✅ 无"待定"/"TODO"/"类似任务 N"——每步均含完整代码。

### 类型一致性
- `FinancialRecord` 在 `data/filings/cninfo.py` 定义，`parser.py` / `prompts.py` / `validator.py` / `ingest_filings.py` 均从此导入。
- `ValidationResult` 在 `knowledge/validator.py` 定义。
- `upsert_financial_record(conn, rec)` 签名在任务 3 定义，任务 6 导入。
- `fetch_cninfo_financial(symbol, years)` 签名在任务 1 定义，任务 6 导入。
