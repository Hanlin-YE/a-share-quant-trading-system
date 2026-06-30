import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "paper_execute.py"
SPEC = importlib.util.spec_from_file_location("paper_execute", MODULE_PATH)
paper_execute = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = paper_execute
SPEC.loader.exec_module(paper_execute)


def make_frame(periods=100, start=10.0, drift=0.05):
    steps = np.arange(periods, dtype=float)
    close = start + steps * drift
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=periods, freq="B"),
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + steps,
        }
    )


class PaperExecuteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.ledger = self.root / "ledger"
        self.account_path = self.root / "account.json"
        self.strategy_path = self.root / "strategies.json"
        self.account_path.write_text(
            json.dumps(
                {
                    "initial_cash": 1000000,
                    "fee_bps": 3,
                    "min_commission": 5,
                    "tax_bps": 5,
                    "transfer_bps": 0.1,
                    "slippage_bps": 0,
                    "risk_limits": {
                        "max_position_pct": 20,
                        "max_total_exposure_pct": 80,
                        "daily_loss_stop_pct": 1,
                        "max_drawdown_alert_pct": 5,
                        "max_drawdown_stop_pct": 10,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.strategy_path.write_text(
            json.dumps(
                {
                    "active_paper_strategy_id": "test-active",
                    "state_machine": {
                        "allow_direct_trade_from_watch": False,
                        "min_trade_state": "TRADE_PLAN",
                    },
                    "strategies": [
                        {
                            "id": "test-active",
                            "name": "测试纸面策略",
                            "entry_score": 50,
                            "exit_score": 45,
                            "max_position_pct": 10,
                            "max_total_exposure_pct": 40,
                            "partial_exit_pct": 0.33,
                            "min_actionable_history": 180,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.patches = [
            patch.object(paper_execute.paper_account, "JOURNAL_DIR", self.root),
            patch.object(paper_execute.paper_account, "LEDGER_DIR", self.ledger),
            patch.object(paper_execute.paper_account, "ACCOUNT_PATH", self.account_path),
            patch.object(paper_execute.paper_account, "PORTFOLIO_LEDGER_PATH", self.root / "portfolio_ledger.csv"),
            patch.object(paper_execute.paper_account, "WORKBOOK_PATH", self.root / "book.xlsx"),
            patch.object(paper_execute.paper_account, "ORDERS_PATH", self.ledger / "orders.csv"),
            patch.object(paper_execute.paper_account, "POSITIONS_PATH", self.ledger / "positions.csv"),
            patch.object(paper_execute.paper_account, "EQUITY_PATH", self.ledger / "equity_curve.csv"),
        ]
        for item in self.patches:
            item.start()
        paper_execute.paper_account.ensure_ledger_files()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_build_decision_package_blocks_watch_to_buy_without_trade_plan(self):
        original_get_stock_data = paper_execute.analyze.get_stock_data
        try:
            paper_execute.analyze.get_stock_data = lambda stock_code, days, source: paper_execute.analyze.DataResult(
                make_frame(periods=220),
                stock_code,
                "测试股票",
                "测试源",
            )
            package = paper_execute.build_decision_package(
                ["600519"],
                days=100,
                source="auto",
                strategy_path=self.strategy_path,
            )
        finally:
            paper_execute.analyze.get_stock_data = original_get_stock_data

        orders = paper_execute.paper_account.read_rows(paper_execute.paper_account.ORDERS_PATH)
        self.assertTrue(package["ok"])
        self.assertEqual(package["decisions"][0]["action"], "WATCH")
        self.assertIn("TRADE_PLAN", package["decisions"][0]["reason"])
        self.assertEqual(orders, [])

    def test_build_decision_package_generates_buy_from_trade_plan_without_writing_order(self):
        original_get_stock_data = paper_execute.analyze.get_stock_data
        try:
            paper_execute.analyze.get_stock_data = lambda stock_code, days, source: paper_execute.analyze.DataResult(
                make_frame(periods=220),
                stock_code,
                "测试股票",
                "测试源",
            )
            package = paper_execute.build_decision_package(
                ["600519"],
                days=220,
                source="auto",
                strategy_path=self.strategy_path,
                symbol_states={"600519": "TRADE_PLAN"},
            )
        finally:
            paper_execute.analyze.get_stock_data = original_get_stock_data

        orders = paper_execute.paper_account.read_rows(paper_execute.paper_account.ORDERS_PATH)
        self.assertTrue(package["ok"])
        self.assertEqual(package["decisions"][0]["action"], "BUY")
        self.assertEqual(orders, [])

    def test_insufficient_history_downgrades_action_to_watch(self):
        original_get_stock_data = paper_execute.analyze.get_stock_data
        try:
            paper_execute.analyze.get_stock_data = lambda stock_code, days, source: paper_execute.analyze.DataResult(
                make_frame(periods=120),
                stock_code,
                "测试股票",
                "测试源",
            )
            package = paper_execute.build_decision_package(
                ["600519"],
                days=120,
                source="auto",
                strategy_path=self.strategy_path,
                symbol_states={"600519": "TRADE_PLAN"},
            )
        finally:
            paper_execute.analyze.get_stock_data = original_get_stock_data

        self.assertEqual(package["decisions"][0]["action"], "WATCH")
        self.assertIn("样本不足", package["decisions"][0]["reason"])

    def test_low_score_position_uses_partial_reduce_not_full_exit(self):
        original_get_stock_data = paper_execute.analyze.get_stock_data
        original_active = paper_execute.paper_account.active_positions
        original_score = paper_execute.score_data_result
        try:
            paper_execute.analyze.get_stock_data = lambda stock_code, days, source: paper_execute.analyze.DataResult(
                make_frame(periods=220),
                stock_code,
                "测试股票",
                "测试源",
            )
            paper_execute.paper_account.active_positions = lambda: {
                "600519": {"quantity": "900", "last_price": "10"}
            }
            paper_execute.score_data_result = lambda data: {
                "stock_code": data.stock_code,
                "stock_name": data.stock_name,
                "source": data.source,
                "source_note": data.source_note,
                "latest_date": "2026-06-11",
                "close": 10.0,
                "final_score": 30.0,
                "suggestion": "减仓或回避",
                "signals": [],
            }
            package = paper_execute.build_decision_package(
                ["600519"],
                days=220,
                source="auto",
                strategy_path=self.strategy_path,
                symbol_states={"600519": "EXECUTED"},
            )
        finally:
            paper_execute.analyze.get_stock_data = original_get_stock_data
            paper_execute.paper_account.active_positions = original_active
            paper_execute.score_data_result = original_score

        decision = package["decisions"][0]
        self.assertEqual(decision["action"], "REDUCE")
        self.assertEqual(decision["side"], "SELL")
        self.assertEqual(decision["quantity"], 200)
        self.assertLess(decision["quantity"], decision["current_quantity"])
        self.assertIn("preflight", decision)

    def test_low_score_one_lot_position_exits_full_lot(self):
        original_get_stock_data = paper_execute.analyze.get_stock_data
        original_active = paper_execute.paper_account.active_positions
        original_score = paper_execute.score_data_result
        try:
            paper_execute.analyze.get_stock_data = lambda stock_code, days, source: paper_execute.analyze.DataResult(
                make_frame(periods=220),
                stock_code,
                "测试股票",
                "测试源",
            )
            paper_execute.paper_account.active_positions = lambda: {
                "600519": {"quantity": "100", "last_price": "10"}
            }
            paper_execute.score_data_result = lambda data: {
                "stock_code": data.stock_code,
                "stock_name": data.stock_name,
                "source": data.source,
                "source_note": data.source_note,
                "latest_date": "2026-06-11",
                "close": 10.0,
                "final_score": 30.0,
                "suggestion": "减仓或回避",
                "signals": [],
            }
            package = paper_execute.build_decision_package(
                ["600519"],
                days=220,
                source="auto",
                strategy_path=self.strategy_path,
                symbol_states={"600519": "EXECUTED"},
            )
        finally:
            paper_execute.analyze.get_stock_data = original_get_stock_data
            paper_execute.paper_account.active_positions = original_active
            paper_execute.score_data_result = original_score

        decision = package["decisions"][0]
        self.assertEqual(decision["action"], "SELL")
        self.assertEqual(decision["side"], "SELL")
        self.assertEqual(decision["quantity"], 100)

    def test_low_score_existing_odd_lot_position_exits_full_odd_lot(self):
        original_get_stock_data = paper_execute.analyze.get_stock_data
        original_active = paper_execute.paper_account.active_positions
        original_score = paper_execute.score_data_result
        try:
            paper_execute.analyze.get_stock_data = lambda stock_code, days, source: paper_execute.analyze.DataResult(
                make_frame(periods=220),
                stock_code,
                "测试股票",
                "测试源",
            )
            paper_execute.paper_account.active_positions = lambda: {
                "600519": {"quantity": "70", "last_price": "10"}
            }
            paper_execute.score_data_result = lambda data: {
                "stock_code": data.stock_code,
                "stock_name": data.stock_name,
                "source": data.source,
                "source_note": data.source_note,
                "latest_date": "2026-06-11",
                "close": 10.0,
                "final_score": 30.0,
                "suggestion": "减仓或回避",
                "signals": [],
            }
            package = paper_execute.build_decision_package(
                ["600519"],
                days=220,
                source="auto",
                strategy_path=self.strategy_path,
                symbol_states={"600519": "EXECUTED"},
            )
        finally:
            paper_execute.analyze.get_stock_data = original_get_stock_data
            paper_execute.paper_account.active_positions = original_active
            paper_execute.score_data_result = original_score

        decision = package["decisions"][0]
        self.assertEqual(decision["action"], "SELL")
        self.assertEqual(decision["side"], "SELL")
        self.assertEqual(decision["quantity"], 70)

    def test_execute_decisions_blocks_failed_preflight(self):
        package = {
            "decisions": [
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "action": "BUY",
                    "side": "BUY",
                    "quantity": 30,
                    "price": 100.0,
                    "reason": "test",
                    "strategy_id": "test-active",
                    "preflight": {
                        "actionable": False,
                        "blocking_reasons": ["BUY 数量必须为 100 股整数倍"],
                    },
                }
            ]
        }

        rows = paper_execute.execute_decisions(package, "2026-06-11", "09:30", dry_run=False)
        orders = paper_execute.paper_account.read_rows(paper_execute.paper_account.ORDERS_PATH)

        self.assertTrue(rows[0]["blocked"])
        self.assertEqual(orders, [])

    def test_execute_decisions_dry_run_does_not_write_order(self):
        package = {
            "decisions": [
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "action": "BUY",
                    "side": "BUY",
                    "quantity": 100,
                    "price": 100.0,
                    "reason": "test",
                    "strategy_id": "test-active",
                }
            ]
        }

        rows = paper_execute.execute_decisions(package, "2026-06-11", "09:30", dry_run=True)
        orders = paper_execute.paper_account.read_rows(paper_execute.paper_account.ORDERS_PATH)

        self.assertTrue(rows[0]["dry_run"])
        self.assertEqual(orders, [])

    def test_execute_decisions_writes_order_when_explicit(self):
        package = {
            "decisions": [
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "action": "BUY",
                    "side": "BUY",
                    "quantity": 100,
                    "price": 100.0,
                    "reason": "test",
                    "strategy_id": "test-active",
                }
            ]
        }

        paper_execute.execute_decisions(package, "2026-06-11", "09:30", dry_run=False)
        orders = paper_execute.paper_account.read_rows(paper_execute.paper_account.ORDERS_PATH)

        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["side"], "BUY")

    def test_build_decision_package_stops_on_cache_health_failure(self):
        original_health = paper_execute.analyze.inspect_market_cache
        original_render = paper_execute.analyze.render_market_cache_health
        original_get_stock_data = paper_execute.analyze.get_stock_data
        try:
            paper_execute.analyze.inspect_market_cache = lambda *args, **kwargs: {"ok": False}
            paper_execute.analyze.render_market_cache_health = lambda payload: "缓存门禁失败"
            paper_execute.analyze.get_stock_data = lambda *args, **kwargs: self.fail("should stop before fetching")

            package = paper_execute.build_decision_package(
                ["600519"],
                days=100,
                source="auto",
                strategy_path=self.strategy_path,
                require_cache_health=True,
            )
        finally:
            paper_execute.analyze.inspect_market_cache = original_health
            paper_execute.analyze.render_market_cache_health = original_render
            paper_execute.analyze.get_stock_data = original_get_stock_data

        self.assertFalse(package["ok"])
        self.assertEqual(package["decisions"], [])
        self.assertIn("缓存门禁失败", package["failures"][0]["error"])


if __name__ == "__main__":
    unittest.main()
