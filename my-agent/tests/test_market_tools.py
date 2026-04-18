import importlib
import json
import sys
import tempfile
import types
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import db  # noqa: E402
from agent.config import cfg  # noqa: E402

sys.modules.setdefault("requests", types.SimpleNamespace(get=None))


class _FakeResponse:
    def __init__(self, payload: dict, *, status_code: int = 200, text: str | None = None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)

    def raise_for_status(self):
        return None

    def json(self) -> dict:
        return self._payload


class MarketWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = cfg.db_path
        self.old_workspace_path = cfg.workspace_path
        self.old_marketstack_api_key = cfg.marketstack_api_key
        cfg.db_path = str(Path(self.tmpdir.name) / "agent.db")
        cfg.workspace_path = str(Path(self.tmpdir.name) / "workspace")
        cfg.marketstack_api_key = "test-marketstack-key"
        db.close()
        db.init_db()

        skill_dir = Path(cfg.workspace_path) / "skills" / "market-watch"
        skill_dir.mkdir(parents=True)
        (skill_dir / "watchlist.json").write_text(
            json.dumps(
                {
                    "default_group": "test_group",
                    "monthly_symbol_budget": 80,
                    "groups": {
                        "test_group": [
                            {"symbol": "AAA", "exchange": "XPAR", "name": "Alpha"},
                            {"symbol": "BBB", "exchange": "XPAR", "name": "Beta"},
                            {"symbol": "CCC", "exchange": "XPAR", "name": "Gamma"},
                        ]
                    },
                }
            )
        )

        import agent.tools.market as market_tools  # noqa: E402

        self.market_tools = importlib.reload(market_tools)

    def tearDown(self):
        db.close()
        cfg.db_path = self.old_db_path
        cfg.workspace_path = self.old_workspace_path
        cfg.marketstack_api_key = self.old_marketstack_api_key
        self.tmpdir.cleanup()

    def _insert_bars(self, symbol: str, closes: list[float], *, exchange: str = "XPAR", low_offset: float = 1.0):
        db_conn = db.get_db()
        base_date = date(2026, 3, 19)
        payload = []
        for idx, close in enumerate(closes):
            current_date = (base_date + timedelta(days=idx)).isoformat()
            payload.append(
                (
                    symbol,
                    exchange,
                    current_date,
                    symbol,
                    "eur",
                    close + 0.5,
                    close + 1.0,
                    close - low_offset,
                    close,
                    1000 + (idx * 50),
                    "2026-04-18T20:00:00Z",
                )
            )
        db_conn.executemany(
            """
            INSERT INTO market_eod_prices(
                symbol, exchange, date, name, currency, open, high, low, close, volume, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        db.commit()

    def test_market_watch_uses_cache_only_when_refresh_is_disabled(self):
        self._insert_bars("AAA", [120, 118, 117, 115, 112, 110, 108, 107, 106, 104, 102, 101, 100, 97, 95, 94, 92, 90, 88, 87, 85, 84, 82, 81, 80, 78, 77, 76, 74, 79], low_offset=3.0)
        self._insert_bars("BBB", [50 + i for i in range(30)])
        self._insert_bars("CCC", [80 for _ in range(30)])

        with patch.object(self.market_tools, "_today_utc", return_value=date(2026, 4, 18)):
            result = self.market_tools.market_watch(
                group="test_group",
                refresh=False,
                history_days=30,
                max_movers=3,
                max_candidates=3,
            )

        self.assertIn("Market watch group: test_group", result)
        self.assertIn("Top drops:", result)
        self.assertIn("Top gains:", result)
        self.assertIn("AAA (XPAR)", result)

    def test_market_watch_refreshes_from_marketstack_and_logs_usage(self):
        payload = {
            "pagination": {"limit": 1000, "offset": 0, "count": 6, "total": 6},
            "data": [
                {
                    "symbol": "AAA",
                    "exchange": "XPAR",
                    "date": "2026-04-17T00:00:00+0000",
                    "name": "Alpha",
                    "price_currency": "eur",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 90.0,
                    "close": 92.0,
                    "volume": 2000.0,
                },
                {
                    "symbol": "AAA",
                    "exchange": "XPAR",
                    "date": "2026-04-18T00:00:00+0000",
                    "name": "Alpha",
                    "price_currency": "eur",
                    "open": 92.0,
                    "high": 94.0,
                    "low": 80.0,
                    "close": 88.0,
                    "volume": 5000.0,
                },
                {
                    "symbol": "BBB",
                    "exchange": "XPAR",
                    "date": "2026-04-17T00:00:00+0000",
                    "name": "Beta",
                    "price_currency": "eur",
                    "open": 50.0,
                    "high": 52.0,
                    "low": 49.0,
                    "close": 51.0,
                    "volume": 1500.0,
                },
                {
                    "symbol": "BBB",
                    "exchange": "XPAR",
                    "date": "2026-04-18T00:00:00+0000",
                    "name": "Beta",
                    "price_currency": "eur",
                    "open": 51.0,
                    "high": 57.0,
                    "low": 50.0,
                    "close": 56.0,
                    "volume": 2500.0,
                },
                {
                    "symbol": "CCC",
                    "exchange": "XPAR",
                    "date": "2026-04-17T00:00:00+0000",
                    "name": "Gamma",
                    "price_currency": "eur",
                    "open": 70.0,
                    "high": 71.0,
                    "low": 68.0,
                    "close": 69.0,
                    "volume": 1800.0,
                },
                {
                    "symbol": "CCC",
                    "exchange": "XPAR",
                    "date": "2026-04-18T00:00:00+0000",
                    "name": "Gamma",
                    "price_currency": "eur",
                    "open": 69.0,
                    "high": 70.0,
                    "low": 67.0,
                    "close": 68.0,
                    "volume": 1700.0,
                },
            ],
        }

        with patch.object(self.market_tools, "_today_utc", return_value=date(2026, 4, 18)), patch.object(
            self.market_tools.requests, "get", return_value=_FakeResponse(payload)
        ) as get_mock:
            result = self.market_tools.market_watch(
                group="test_group",
                refresh=True,
                force_refresh=True,
                history_days=30,
            )

        self.assertIn("Last refresh: 3 symbol(s) from Marketstack", result)
        self.assertEqual(get_mock.call_count, 1)
        rows = db.fetchall("SELECT symbol, exchange, date FROM market_eod_prices ORDER BY symbol, date")
        self.assertEqual(len(rows), 6)
        usage = db.fetchall("SELECT symbols_count, status, row_count FROM market_api_usage")
        self.assertEqual(
            [(row["symbols_count"], row["status"], row["row_count"]) for row in usage],
            [(3, "ok", 6)],
        )

    def test_market_watch_requires_api_key_for_refresh(self):
        cfg.marketstack_api_key = ""
        result = self.market_tools.market_watch(group="test_group", refresh=True)
        self.assertIn("MARKETSTACK_API_KEY is not configured", result)

    def test_market_watch_falls_back_to_single_symbol_refresh_after_batch_error(self):
        error_payload = {
            "error": {
                "code": "validation_error",
                "message": "Request failed with validation error",
                "context": {
                    "symbols": [
                        {
                            "key": "invalid_symbol",
                            "message": "BBB is not supported on XPAR",
                        }
                    ]
                },
            }
        }

        def fake_get(_url, params=None, **_kwargs):
            symbols = params["symbols"]
            if symbols == "AAA,BBB,CCC":
                return _FakeResponse(error_payload, status_code=406)
            if symbols == "BBB":
                return _FakeResponse(error_payload, status_code=406)

            payload = {
                "pagination": {"limit": 1000, "offset": 0, "count": 2, "total": 2},
                "data": [
                    {
                        "symbol": symbols,
                        "exchange": "XPAR",
                        "date": "2026-04-17T00:00:00+0000",
                        "name": symbols,
                        "price_currency": "eur",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 95.0,
                        "close": 96.0,
                        "volume": 2000.0,
                    },
                    {
                        "symbol": symbols,
                        "exchange": "XPAR",
                        "date": "2026-04-18T00:00:00+0000",
                        "name": symbols,
                        "price_currency": "eur",
                        "open": 96.0,
                        "high": 98.0,
                        "low": 90.0,
                        "close": 92.0,
                        "volume": 2600.0,
                    },
                ],
            }
            return _FakeResponse(payload)

        with patch.object(self.market_tools, "_today_utc", return_value=date(2026, 4, 18)), patch.object(
            self.market_tools.requests, "get", side_effect=fake_get
        ) as get_mock:
            result = self.market_tools.market_watch(
                group="test_group",
                refresh=True,
                force_refresh=True,
                history_days=30,
            )

        self.assertIn("Refresh issues: BBB:XPAR", result)
        self.assertIn("HTTP 406 | validation_error", result)
        self.assertIn("Missing cache rows:\n- BBB:XPAR", result)
        self.assertEqual(get_mock.call_count, 4)
        rows = db.fetchall("SELECT symbol, exchange, date FROM market_eod_prices ORDER BY symbol, date")
        self.assertEqual([(row["symbol"], row["date"]) for row in rows], [("AAA", "2026-04-17"), ("AAA", "2026-04-18"), ("CCC", "2026-04-17"), ("CCC", "2026-04-18")])


if __name__ == "__main__":
    unittest.main()
