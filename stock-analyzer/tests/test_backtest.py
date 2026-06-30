import importlib.util
import pathlib
import sys
import unittest

import numpy as np
import pandas as pd


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "backtest.py"
SPEC = importlib.util.spec_from_file_location("backtest", MODULE_PATH)
backtest = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = backtest
SPEC.loader.exec_module(backtest)


def make_frame(start_price=10.0, drift=0.02, periods=120):
    steps = np.arange(periods, dtype=float)
    close = start_price + steps * drift
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=periods, freq="B"),
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1000 + steps * 10,
        }
    )


class BacktestEngineTest(unittest.TestCase):
    def test_signals_use_previous_day_history_only(self):
        seen = []

        def score_func(symbol, history):
            seen.append((symbol, history["date"].iloc[-1]))
            return 70.0, "test entry"

        result = backtest.run_backtest_from_frames(
            {"600519": make_frame()},
            backtest.BacktestConfig(min_history=80, max_total_exposure_pct=50),
            score_func=score_func,
        )

        first_trade_date = pd.Timestamp(result.trades.iloc[0]["date"])
        self.assertLess(pd.Timestamp(seen[0][1]), first_trade_date)
        self.assertGreater(result.metrics["trade_count"], 0)

    def test_transaction_costs_reduce_return(self):
        frames = {"600519": make_frame(drift=0.05)}
        cheap = backtest.run_backtest_from_frames(
            frames,
            backtest.BacktestConfig(
                fee_bps=0,
                min_commission=0,
                tax_bps=0,
                transfer_bps=0,
                slippage_bps=0,
                min_history=80,
            ),
            score_func=lambda symbol, history: (70.0, "always long"),
        )
        expensive = backtest.run_backtest_from_frames(
            frames,
            backtest.BacktestConfig(fee_bps=30, tax_bps=50, slippage_bps=20, min_history=80),
            score_func=lambda symbol, history: (70.0, "always long"),
        )

        self.assertLess(expensive.metrics["final_equity"], cheap.metrics["final_equity"])

    def test_cost_breakdown_applies_min_commission_and_sell_tax_only(self):
        buy_costs = backtest.trade_cost_breakdown(
            1000,
            "BUY",
            fee_bps=3,
            min_commission=5,
            tax_bps=5,
            transfer_bps=0.1,
        )
        sell_costs = backtest.trade_cost_breakdown(
            1000,
            "SELL",
            fee_bps=3,
            min_commission=5,
            tax_bps=5,
            transfer_bps=0.1,
        )

        self.assertEqual(buy_costs["commission"], 5)
        self.assertEqual(buy_costs["stamp_tax"], 0)
        self.assertEqual(sell_costs["commission"], 5)
        self.assertGreater(sell_costs["stamp_tax"], 0)
        self.assertGreater(sell_costs["total_cost"], buy_costs["total_cost"])

    def test_trade_log_contains_cost_breakdown_columns(self):
        result = backtest.run_backtest_from_frames(
            {"600519": make_frame()},
            backtest.BacktestConfig(min_history=80),
            score_func=lambda symbol, history: (70.0, "always long"),
        )

        for column in ["commission", "stamp_tax", "transfer_fee", "cost"]:
            self.assertIn(column, result.trades.columns)

    def test_exit_score_closes_position(self):
        calls = []

        def score_func(symbol, history):
            calls.append(history["date"].iloc[-1])
            return (70.0, "enter") if len(calls) == 1 else (20.0, "exit")

        result = backtest.run_backtest_from_frames(
            {"600519": make_frame()},
            backtest.BacktestConfig(min_history=80),
            score_func=score_func,
        )

        self.assertIn("BUY", set(result.trades["action"]))
        self.assertIn("SELL", set(result.trades["action"]))
        self.assertTrue(result.positions.empty)


if __name__ == "__main__":
    unittest.main()
