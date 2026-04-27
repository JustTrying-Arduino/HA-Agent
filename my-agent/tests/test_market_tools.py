"""Tests for agent.indicators and agent.tools.market (Degiro-backed)."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from agent import db, indicators  # noqa: E402
from agent.config import cfg  # noqa: E402


class IndicatorTests(unittest.TestCase):
    def test_sma(self):
        self.assertEqual(indicators.sma([1, 2, 3, 4, 5], 5), 3.0)
        self.assertEqual(indicators.sma([1, 2, 3, 4, 5], 3), 4.0)
        self.assertIsNone(indicators.sma([1, 2], 5))

    def test_rsi_monotonic_rise_saturates_high(self):
        closes = list(range(1, 30))
        rsi = indicators.rsi14(closes)
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, 80)

    def test_rsi_monotonic_drop_saturates_low(self):
        closes = [float(x) for x in range(30, 0, -1)]
        rsi = indicators.rsi14(closes)
        self.assertIsNotNone(rsi)
        self.assertLess(rsi, 20)

    def test_breakout_20d(self):
        closes = [10.0] * 20 + [11.0]
        self.assertTrue(indicators.breakout_20d(closes))
        closes2 = [10.0] * 20 + [10.0]
        self.assertFalse(indicators.breakout_20d(closes2))
        self.assertFalse(indicators.breakout_20d([1, 2, 3]))

    def test_variation(self):
        closes = [100.0, 110.0]
        self.assertAlmostEqual(indicators.variation(closes, 1), 10.0)
        self.assertIsNone(indicators.variation([100.0], 1))

    def test_support_levels_dense_cluster(self):
        closes = [100.0, 101.0, 99.5, 100.5, 150.0, 151.0, 149.5]
        levels = indicators.support_levels(closes, tol=0.02, min_count=3)
        self.assertEqual(len(levels), 2)
        # densest bucket first
        self.assertGreaterEqual(levels[0].count, levels[1].count)

    def test_drawdown_from_high(self):
        self.assertAlmostEqual(indicators.drawdown_from_high(80.0, 100.0), -20.0)
        self.assertIsNone(indicators.drawdown_from_high(None, 100.0))
        self.assertIsNone(indicators.drawdown_from_high(80.0, None))

    def test_evaluate_rebound_reject_falling_knife(self):
        # Dense support around 100, then sharp break below with RSI falling and SMA50 turning down.
        closes = [100.0 + (i % 3) * 0.2 for i in range(80)]
        closes += [100.0 - i * 1.5 for i in range(1, 41)]
        verdict = indicators.evaluate_rebound(closes, high_52w=105.0)
        self.assertEqual(verdict.signal, "reject")
        self.assertTrue(any("falling knife" in r for r in verdict.reasons))

    def test_evaluate_swing_requires_long_history(self):
        verdict = indicators.evaluate_swing([1.0] * 100)
        self.assertEqual(verdict.signal, "neutral")
        self.assertTrue(any("not enough history" in r for r in verdict.reasons))

    def test_evaluate_swing_trend_up_candidate(self):
        # 220 closes rising linearly then a small pullback and recovery.
        closes = [float(i) for i in range(1, 211)]
        closes.append(closes[-1] * 0.99)  # pullback
        closes.append(closes[-1] * 1.02)  # recovery — also triggers breakout
        verdict = indicators.evaluate_swing(closes)
        self.assertEqual(verdict.signal, "candidate")
        self.assertGreaterEqual(verdict.score, 3)

    def test_unknown_strategy_raises(self):
        with self.assertRaises(ValueError):
            indicators.evaluate("unknown", [1.0, 2.0, 3.0])


# ---------------------------------------------------------------------------
# market_watch integration test with fake DegiroClient
# ---------------------------------------------------------------------------


@dataclass
class FakeProduct:
    id: str
    symbol: str | None
    name: str | None
    isin: str | None
    currency: str | None
    vwd_id: str | None
    product_type: str | None = None
    exchange_id: str | None = None
    vwd_identifier_type: str | None = "issueid"


@dataclass
class FakeCandle:
    timestamp: object
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


class FakeDegiroClient:
    def __init__(self, series: dict[str, list[float]]):
        self._series = series
        self.session = object()  # non-None → get_client skips login

    @staticmethod
    def _product_for(query: str) -> FakeProduct:
        q = query.upper()
        return FakeProduct(
            id=f"id-{q}",
            symbol=q,
            name=f"Name {q}",
            isin=q if len(q) == 12 else None,
            currency="EUR",
            vwd_id=f"vwd-{q}",
            exchange_id="710",
        )

    def search_products(self, query, limit=10):
        return [self._product_for(query)]

    def price_history(
        self, vwd_id, *, period="P1Y", resolution="P1D", vwd_identifier_type=None
    ):
        closes = self._series.get(vwd_id, [])
        if not closes:
            return []
        from datetime import datetime, timedelta
        start = datetime(2026, 1, 1)
        return [
            FakeCandle(timestamp=start + timedelta(days=i), close=c)
            for i, c in enumerate(closes)
        ]

    def price_metadata(self, vwd_id, vwd_identifier_type=None):
        closes = self._series.get(vwd_id, [])
        if not closes:
            return {}
        return {"highPriceP1Y": max(closes), "lowPriceP1Y": min(closes)}

    def login(self, *a, **kw):
        return None

    def get_portfolio(self, only_open=True):
        return []

    def get_cash(self):
        return {}


class MarketWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = cfg.db_path
        self.old_workspace_path = cfg.workspace_path
        self.old_username = cfg.degiro_username
        self.old_password = cfg.degiro_password
        cfg.db_path = str(Path(self.tmpdir.name) / "agent.db")
        cfg.workspace_path = str(Path(self.tmpdir.name) / "workspace")
        cfg.degiro_username = "testuser"
        cfg.degiro_password = "testpass"
        db.close()
        db.init_db()

        skill_dir = Path(cfg.workspace_path) / "skills" / "market-watch"
        skill_dir.mkdir(parents=True)
        (skill_dir / "watchlist.json").write_text(
            json.dumps(
                {
                    "default_group": "test_group",
                    "groups": {
                        "test_group": [
                            {"isin": "US0000000AAA", "label": "Alpha", "currency": "EUR"},
                            {"isin": "US0000000BBB", "label": "Beta", "currency": "EUR"},
                        ]
                    },
                }
            )
        )

        from agent import degiro as degiro_mod

        self.degiro_mod = importlib.reload(degiro_mod)
        import agent.tools.market as market_tools

        self.market_tools = importlib.reload(market_tools)

    def tearDown(self):
        db.close()
        cfg.db_path = self.old_db_path
        cfg.workspace_path = self.old_workspace_path
        cfg.degiro_username = self.old_username
        cfg.degiro_password = self.old_password
        self.tmpdir.cleanup()

    def test_market_watch_runs_swing_screen(self):
        # Alpha: strong rising trend over 220 days → swing candidate.
        # Beta: flat series → neutral.
        alpha_closes = [float(i) + 50 for i in range(220)]
        beta_closes = [100.0] * 220
        fake_client = FakeDegiroClient(
            {"vwd-US0000000AAA": alpha_closes, "vwd-US0000000BBB": beta_closes}
        )

        with patch.object(self.degiro_mod, "get_client", return_value=fake_client), \
             patch.object(self.market_tools.degiro, "get_client", return_value=fake_client):
            result = self.market_tools.market_watch(strategy="swing", group="test_group")

        self.assertIn("Market watch — strategy=swing", result)
        self.assertIn("Candidates", result)
        self.assertIn("US0000000AAA", result)


class ResolveProductCacheTests(unittest.TestCase):
    """Regression: same ISIN with different listing filters must not collide in cache."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_db_path = cfg.db_path
        self.old_username = cfg.degiro_username
        self.old_password = cfg.degiro_password
        cfg.db_path = str(Path(self.tmpdir.name) / "agent.db")
        cfg.degiro_username = "testuser"
        cfg.degiro_password = "testpass"
        db.close()
        db.init_db()

        from agent import degiro as degiro_mod
        self.degiro_mod = importlib.reload(degiro_mod)

    def tearDown(self):
        db.close()
        cfg.db_path = self.old_db_path
        cfg.degiro_username = self.old_username
        cfg.degiro_password = self.old_password
        self.tmpdir.cleanup()

    def test_same_isin_different_exchange_do_not_collide(self):
        isin = "FR0000121014"
        listings = {
            "710": FakeProduct(id="p-xpar", symbol="MC", name="LVMH XPAR",
                               isin=isin, currency="EUR", vwd_id="vwd-xpar",
                               exchange_id="710"),
            "194": FakeProduct(id="p-xetra", symbol="MOH", name="LVMH XETRA",
                               isin=isin, currency="EUR", vwd_id="vwd-xetra",
                               exchange_id="194"),
        }

        class MultiListingClient(FakeDegiroClient):
            def search_products(self, query, limit=10):
                return list(listings.values())

        fake = MultiListingClient({"vwd-xpar": [100.0] * 30, "vwd-xetra": [200.0] * 30})

        with patch.object(self.degiro_mod, "get_client", return_value=fake):
            ref_xpar = self.degiro_mod.resolve_product(isin, exchange_id="710")
            ref_xetra = self.degiro_mod.resolve_product(isin, exchange_id="194")

        self.assertEqual(ref_xpar.exchange_id, "710")
        self.assertEqual(ref_xetra.exchange_id, "194")
        self.assertNotEqual(ref_xpar.vwd_id, ref_xetra.vwd_id)
        self.assertNotEqual(ref_xpar.query_norm, ref_xetra.query_norm)

        from agent.db import fetchall
        rows = fetchall(
            "SELECT query_norm, exchange_id FROM degiro_products WHERE isin = ?",
            (isin,),
        )
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
