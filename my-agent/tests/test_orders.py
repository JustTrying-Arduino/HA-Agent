import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))

from agent import db, degiro, orders  # noqa: E402
from agent.config import cfg  # noqa: E402


class OrdersTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.original_db_path = cfg.db_path
        self.original_orders_enabled = cfg.degiro_orders_enabled
        cfg.db_path = str(Path(self.tmpdir.name) / "agent.db")
        cfg.degiro_orders_enabled = True
        db.close()
        db.init_db()
        self._original_place = degiro.place_limit_gtc
        self._original_cancel = degiro.cancel_order
        self.place_calls = []
        self.cancel_calls = []
        degiro.place_limit_gtc = lambda **kw: (
            self.place_calls.append(kw) or "ORDER-1"
        )
        degiro.cancel_order = lambda order_id: self.cancel_calls.append(order_id)

    def tearDown(self):
        degiro.place_limit_gtc = self._original_place
        degiro.cancel_order = self._original_cancel
        db.close()
        cfg.db_path = self.original_db_path
        cfg.degiro_orders_enabled = self.original_orders_enabled
        self.tmpdir.cleanup()

    def _create_buy(self, **overrides):
        params = dict(
            chat_id=42, product_id="123", isin="FR0", label="X",
            side="BUY", size=1, limit_price=10.0, currency="EUR",
        )
        params.update(overrides)
        return orders.create_pending_place(**params)

    def test_buy_amount_cap(self):
        with self.assertRaises(orders.OrderGuardError):
            self._create_buy(size=10, limit_price=200.0)  # 2000 EUR

    def test_kill_switch_blocks(self):
        cfg.degiro_orders_enabled = False
        with self.assertRaises(orders.OrderGuardError):
            self._create_buy()

    def test_sell_no_amount_cap(self):
        pid, _ = self._create_buy(side="SELL", size=100, limit_price=200.0)
        self.assertGreater(pid, 0)

    def test_resolve_confirm_then_idempotent(self):
        pid, _ = self._create_buy(size=2, limit_price=50.0)
        first = orders.resolve_pending(pending_id=pid, chat_id=42, decision="ok")
        second = orders.resolve_pending(pending_id=pid, chat_id=42, decision="ok")
        self.assertEqual(first.status, orders.CONFIRMED)
        self.assertEqual(second.status, "noop")
        self.assertEqual(len(self.place_calls), 1)

    def test_resolve_wrong_chat(self):
        pid, _ = self._create_buy()
        result = orders.resolve_pending(pending_id=pid, chat_id=999, decision="ok")
        self.assertEqual(result.status, "noop")
        self.assertEqual(len(self.place_calls), 0)

    def test_resolve_decline(self):
        pid, _ = self._create_buy()
        result = orders.resolve_pending(pending_id=pid, chat_id=42, decision="no")
        self.assertEqual(result.status, orders.CANCELLED)
        self.assertEqual(len(self.place_calls), 0)

    def test_quota_enforced_after_4_confirmed_buys(self):
        for _ in range(orders.BUY_QUOTA_PER_24H):
            pid, _ = self._create_buy()
            orders.resolve_pending(pending_id=pid, chat_id=42, decision="ok")
        with self.assertRaises(orders.OrderGuardError):
            self._create_buy()

    def test_cancel_flow_round_trip(self):
        pid, _ = orders.create_pending_cancel(
            chat_id=42, order_id="OID-99", label="SELL 1 X @ 10",
        )
        result = orders.resolve_pending(pending_id=pid, chat_id=42, decision="ok")
        self.assertEqual(result.status, orders.CONFIRMED)
        self.assertEqual(self.cancel_calls, ["OID-99"])

    def test_expire_due_pending(self):
        pid, _ = self._create_buy()
        db.execute(
            "UPDATE pending_actions SET expires_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (pid,),
        )
        db.commit()
        expired = orders.expire_due_pending()
        self.assertEqual(len(expired), 1)
        result = orders.resolve_pending(pending_id=pid, chat_id=42, decision="ok")
        self.assertEqual(result.status, "noop")


if __name__ == "__main__":
    unittest.main()
