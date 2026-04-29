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

    def test_evaluate_rebound_rsi_gate_blocks_recovered(self):
        """AIR-like case: drawdown big, near support, but RSI no longer oversold.
        The RSI gate must short-circuit to `neutral`."""
        # Long balanced sequence so the recent RSI sits above 35.
        closes = [100.0]
        for i in range(1, 80):
            # Slight uptrend with high noise → RSI should land in 40-60 range.
            closes.append(closes[-1] + ((-1) ** i) * 0.6 + 0.05)
        verdict = indicators.evaluate_rebound(closes, high_52w=120.0)
        rsi = verdict.metrics.get("rsi14")
        self.assertIsNotNone(rsi)
        self.assertGreater(rsi, 35.0)
        self.assertEqual(verdict.signal, "neutral")
        self.assertTrue(any("not oversold" in r for r in verdict.reasons))

    def test_evaluate_rebound_recovery_already_advanced(self):
        """RSI still in oversold range but var_3d already > +4% on the last 3
        sessions → signal `recovery` (ticket parti)."""
        closes = [100.0] * 5
        # 20-day steep drop (-1.5/day) — RSI deep oversold.
        for i in range(1, 21):
            closes.append(100.0 - i * 1.5)  # ends at 70
        # Consolidation at the bottom forms a cluster (no support break later).
        closes += [70.0] * 10
        # 3-day strong bounce: 70 → 71.5 → 72.5 → 73.0 (var_3d ≈ +4.29%).
        closes += [71.5, 72.5, 73.0]
        verdict = indicators.evaluate_rebound(closes, high_52w=100.0)
        self.assertEqual(verdict.signal, "recovery")
        self.assertTrue(any("already in progress" in r for r in verdict.reasons))

    def test_evaluate_rebound_clean_candidate(self):
        """RSI deep oversold + drawdown ≤ -20% + near support cluster + small
        early bounce in [+0.3%, +2%] → candidate with score 4."""
        closes = [100.0] * 5
        # 8-day big drop (steep, builds heavy avg_loss in RSI).
        closes += [99.0, 97.5, 95.0, 92.0, 89.0, 86.0, 83.0, 80.0]
        # 30-day consolidation at 78 — densest cluster, support holds.
        closes += [78.0] * 30
        # Tiny bounce today.
        closes.append(78.5)
        verdict = indicators.evaluate_rebound(closes, high_52w=100.0)
        self.assertEqual(verdict.signal, "candidate")
        self.assertGreaterEqual(verdict.score, 3)
        self.assertTrue(any("early bounce" in r for r in verdict.reasons))

    def test_evaluate_rebound_stretched_bounce_no_point(self):
        """RSI deep oversold + DD ≤ -20% + near support, but the last bar jumps
        +2.1% — over the bounce ceiling. The bounce contributes 0 point and the
        verdict carries a 'too stretched' reason."""
        # Same shape as the clean candidate but with a shorter consolidation
        # so the RSI stays oversold even after a +2.1% bounce.
        closes = [100.0] * 5
        closes += [99.0, 97.5, 95.0, 92.0, 89.0, 86.0, 83.0, 80.0]
        closes += [78.0] * 17
        closes.append(78.0 * 1.021)  # +2.1% — just over the +2% bounce ceiling
        verdict = indicators.evaluate_rebound(closes, high_52w=100.0)
        self.assertNotEqual(verdict.signal, "recovery")
        self.assertTrue(
            any("too stretched" in r for r in verdict.reasons),
            f"reasons did not flag stretched bounce: {verdict.reasons}",
        )

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


class FreshnessHelpersTests(unittest.TestCase):
    def test_is_today_bar_settled_eu(self):
        from datetime import datetime
        from agent.degiro import PARIS_TZ, is_today_bar_settled

        before = datetime(2026, 4, 29, 17, 30, tzinfo=PARIS_TZ)
        self.assertFalse(is_today_bar_settled("EUR", now=before))
        boundary = datetime(2026, 4, 29, 18, 5, tzinfo=PARIS_TZ)
        self.assertTrue(is_today_bar_settled("EUR", now=boundary))

    def test_is_today_bar_settled_us(self):
        from datetime import datetime
        from agent.degiro import PARIS_TZ, is_today_bar_settled

        before = datetime(2026, 4, 29, 22, 0, tzinfo=PARIS_TZ)
        self.assertFalse(is_today_bar_settled("USD", now=before))
        after = datetime(2026, 4, 29, 22, 30, tzinfo=PARIS_TZ)
        self.assertTrue(is_today_bar_settled("USD", now=after))

    def test_is_today_bar_settled_defaults_to_eu(self):
        from datetime import datetime
        from agent.degiro import PARIS_TZ, is_today_bar_settled

        before = datetime(2026, 4, 29, 17, 0, tzinfo=PARIS_TZ)
        self.assertFalse(is_today_bar_settled(None, now=before))
        after = datetime(2026, 4, 29, 18, 5, tzinfo=PARIS_TZ)
        self.assertTrue(is_today_bar_settled(None, now=after))


class BuildCloseSeriesTests(unittest.TestCase):
    def setUp(self):
        from agent.tools import degiro as tools_degiro
        self.tools_degiro = tools_degiro

    def _row(self, ts: str, close: float):
        from agent.degiro import CandleRow
        return CandleRow(ts=ts, close=close)

    def test_settled_bar_today_no_intraday_call(self):
        from datetime import datetime
        from agent.degiro import PARIS_TZ

        now = datetime(2026, 4, 29, 19, 0, tzinfo=PARIS_TZ)
        rows = [
            self._row("2026-04-28T15:30:00Z", 100.0),
            self._row("2026-04-29T15:30:00Z", 101.0),
        ]
        with patch.object(self.tools_degiro, "_latest_intraday_close") as mock_intraday:
            series = self.tools_degiro.build_close_series(
                rows,
                vwd_id="vwd-X",
                vwd_identifier_type="issueid",
                currency="EUR",
                now=now,
            )
        self.assertFalse(series.is_provisional)
        self.assertEqual(series.closes, [100.0, 101.0])
        mock_intraday.assert_not_called()

    def test_unsettled_today_bar_replaced_with_intraday(self):
        from datetime import datetime
        from agent.degiro import PARIS_TZ

        now = datetime(2026, 4, 29, 17, 30, tzinfo=PARIS_TZ)  # before EU settle
        rows = [
            self._row("2026-04-28T15:30:00Z", 100.0),
            self._row("2026-04-29T13:00:00Z", 101.0),  # cached but stale today bar
        ]
        with patch.object(
            self.tools_degiro,
            "_latest_intraday_close",
            return_value=(103.5, "2026-04-29T15:35:00Z"),
        ):
            series = self.tools_degiro.build_close_series(
                rows,
                vwd_id="vwd-X",
                vwd_identifier_type="issueid",
                currency="EUR",
                now=now,
            )
        self.assertTrue(series.is_provisional)
        self.assertEqual(series.closes[-1], 103.5)
        self.assertEqual(series.last_bar_ts, "2026-04-29T15:35:00Z")

    def test_no_today_bar_intraday_appended(self):
        from datetime import datetime
        from agent.degiro import PARIS_TZ

        now = datetime(2026, 4, 29, 14, 0, tzinfo=PARIS_TZ)
        rows = [
            self._row("2026-04-27T15:30:00Z", 99.0),
            self._row("2026-04-28T15:30:00Z", 100.0),
        ]
        with patch.object(
            self.tools_degiro,
            "_latest_intraday_close",
            return_value=(102.2, "2026-04-29T13:50:00Z"),
        ):
            series = self.tools_degiro.build_close_series(
                rows,
                vwd_id="vwd-X",
                vwd_identifier_type="issueid",
                currency="EUR",
                now=now,
            )
        self.assertTrue(series.is_provisional)
        self.assertEqual(series.closes[-1], 102.2)
        self.assertEqual(len(series.closes), 3)

    def test_no_today_bar_intraday_unavailable(self):
        from datetime import datetime
        from agent.degiro import PARIS_TZ

        now = datetime(2026, 4, 29, 14, 0, tzinfo=PARIS_TZ)
        rows = [self._row("2026-04-28T15:30:00Z", 100.0)]
        with patch.object(
            self.tools_degiro,
            "_latest_intraday_close",
            return_value=(None, None),
        ):
            series = self.tools_degiro.build_close_series(
                rows,
                vwd_id="vwd-X",
                vwd_identifier_type="issueid",
                currency="EUR",
                now=now,
            )
        # No intraday data → fall back to the last cached bar; not provisional
        # because the cached bar isn't today (no today-bar-staleness to flag).
        self.assertFalse(series.is_provisional)
        self.assertEqual(series.closes, [100.0])


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
