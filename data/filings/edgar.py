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
    filed_at: str       # "YYYY-MM-DD"
    url: str            # 归档目录 URL
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
        cik_int = int(cik) if cik.isdigit() else 0
        url = f"{EDGAR_ARCHIVE}/{cik_int}/{acc_path}/"
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

    existing = list(acc_dir.glob("*.htm")) + list(acc_dir.glob("*.html"))
    if existing and not force:
        filing.local_path = existing[0]
        return existing[0]

    try:
        cik_int = int(filing.cik) if filing.cik.isdigit() else 0
        acc_nodash = filing.accession.replace("-", "")
        raw = _http_get_json(
            f"https://data.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/index.json"
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
