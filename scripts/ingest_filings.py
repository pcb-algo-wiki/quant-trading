"""财报摄取编排脚本

从巨潮（A股）抓取财报 → 规则校验 → 落库 financial_reports。
由 daily_pipeline 通过 `filings.enabled` feature flag 调用。

run() 返回 {"inserted": N, "skipped": M, "errors": K}
"""
from __future__ import annotations

from utils.config import get_config
from data.filings.cninfo import fetch_cninfo_financial
from data.filings.parser import upsert_financial_record
from knowledge.validator import FinancialValidator


def get_db_connection():
    from data_store.db import get_connection
    return get_connection()


def _get_symbols() -> list[str]:
    """从 config 取 A 股代码列表；fallback 到示例 5 只。"""
    cfg = get_config()
    symbols = cfg.get("filings.a_share_symbols", [])
    if not symbols:
        symbols = ["000001", "600036", "601318", "600519", "300750"]
    return symbols


def run() -> dict:
    """主入口：抓取 → 校验 → 落库。"""
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
                    skipped += 1
        except Exception as e:
            print(f"[ingest] 摄取失败 {symbol}: {e}")
            errors += 1

    return {"inserted": inserted, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    result = run()
    print(f"[ingest_filings] 完成：{result}")
