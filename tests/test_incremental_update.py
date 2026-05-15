import pandas as pd

from data_store.db import get_connection
from data_store.repositories import MarketBarRepository


def test_incremental_update_only_inserts_new_dates(tmp_path):
    db_path = tmp_path / "quant.db"

    first_batch = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "open": [1.0, 1.1],
            "high": [1.2, 1.3],
            "low": [0.9, 1.0],
            "close": [1.1, 1.2],
            "volume": [1000, 1200],
        }
    )
    second_batch = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-03", "2024-01-04"]),
            "open": [1.1, 1.2],
            "high": [1.3, 1.4],
            "low": [1.0, 1.1],
            "close": [1.2, 1.3],
            "volume": [1200, 1300],
        }
    )

    with get_connection(str(db_path)) as conn:
        repo = MarketBarRepository(conn)
        assert repo.upsert_dataframe(symbol="159915", source="sina", bars=first_batch) == 2
        assert repo.upsert_dataframe(symbol="159915", source="sina", bars=second_batch) == 1

        rows = repo.fetch(symbol="159915")
        assert [r["date"] for r in rows] == ["2024-01-02", "2024-01-03", "2024-01-04"]
