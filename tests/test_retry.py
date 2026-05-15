import logging

from utils.retry import FallbackChain


def test_fallback_chain_execute_safe_logs_and_returns_default(caplog):
    def fail_source():
        raise RuntimeError("boom")

    chain = FallbackChain([(fail_source, {})])
    with caplog.at_level(logging.ERROR):
        result = chain.execute_safe(default="fallback")

    assert result == "fallback"
    assert any("All 1 sources failed" in record.message for record in caplog.records)
