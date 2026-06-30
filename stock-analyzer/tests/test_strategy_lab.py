import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "strategy_lab.py"
SPEC = importlib.util.spec_from_file_location("strategy_lab", MODULE_PATH)
strategy_lab = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = strategy_lab
SPEC.loader.exec_module(strategy_lab)


def make_frame(periods=130):
    steps = np.arange(periods, dtype=float)
    close = 10 + steps * 0.03
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


class StrategyLabTest(unittest.TestCase):
    def test_load_strategies_from_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "strategies.json"
            path.write_text(
                '{"strategies":[{"id":"s1","entry_score":60,"exit_score":45,"max_position_pct":10,"max_total_exposure_pct":20}]}',
                encoding="utf-8",
            )

            strategies = strategy_lab.load_strategies(path)

        self.assertEqual(strategies[0].id, "s1")
        self.assertEqual(strategies[0].config.entry_score, 60)

    def test_compare_strategies_returns_metrics(self):
        strategies = strategy_lab.load_strategies()
        rows = strategy_lab.compare_strategies_from_frames({"600519": make_frame()}, strategies[:2])

        self.assertEqual(len(rows), 2)
        self.assertIn("total_return_pct", rows[0])
        self.assertIn("strategy_id", rows[0])

    def test_sort_strategy_rows_prefers_return_then_lower_drawdown(self):
        rows = [
            {"strategy_id": "a", "total_return_pct": 1.0, "max_drawdown_pct": 4.0, "sharpe": 0.1},
            {"strategy_id": "b", "total_return_pct": 1.0, "max_drawdown_pct": 2.0, "sharpe": 0.0},
        ]

        sorted_rows = strategy_lab.sort_strategy_rows(rows)

        self.assertEqual(sorted_rows[0]["strategy_id"], "b")

    def test_generate_parameter_grid_skips_invalid_threshold_pairs(self):
        optimization = strategy_lab.OptimizationConfig(
            score_profiles=("balanced",),
            entry_scores=(50.0, 60.0),
            exit_scores=(55.0,),
            max_position_pcts=(10.0,),
            max_total_exposure_pcts=(40.0,),
        )

        rows = strategy_lab.generate_parameter_grid(optimization=optimization)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].config.entry_score, 60.0)
        self.assertEqual(rows[0].config.exit_score, 55.0)

    def test_split_frames_by_time_keeps_test_out_of_selection_window(self):
        frame = make_frame(periods=120)

        splits = strategy_lab.split_frames_by_time(
            {"600519": frame},
            train_pct=0.5,
            validation_pct=0.25,
        )

        self.assertEqual(len(splits["train"]["600519"]), 60)
        self.assertEqual(len(splits["validation"]["600519"]), 30)
        self.assertEqual(len(splits["test"]["600519"]), 30)
        self.assertLess(
            splits["validation"]["600519"]["date"].iloc[-1],
            splits["test"]["600519"]["date"].iloc[0],
        )

    def test_rank_optimization_rows_uses_validation_before_test(self):
        rows = [
            {
                "strategy_id": "overfit-test",
                "status": "ok",
                "validation_objective": 1.0,
                "validation_total_return_pct": 1.0,
                "validation_max_drawdown_pct": 1.0,
                "test_objective": 100.0,
                "train_objective": 1.0,
            },
            {
                "strategy_id": "better-validation",
                "status": "ok",
                "validation_objective": 2.0,
                "validation_total_return_pct": 2.0,
                "validation_max_drawdown_pct": 1.0,
                "test_objective": -10.0,
                "train_objective": 1.0,
            },
        ]

        sorted_rows = strategy_lab.rank_optimization_rows(rows)

        self.assertEqual(sorted_rows[0]["strategy_id"], "better-validation")

    def test_optimize_strategies_returns_split_metrics(self):
        optimization = strategy_lab.OptimizationConfig(
            score_profiles=("balanced",),
            entry_scores=(50.0, 60.0),
            exit_scores=(40.0,),
            max_position_pcts=(10.0,),
            max_total_exposure_pcts=(40.0,),
            train_pct=0.5,
            validation_pct=0.25,
            min_history=20,
            walk_forward_top_n=1,
        )
        strategies = strategy_lab.generate_parameter_grid(optimization=optimization)

        rows = strategy_lab.optimize_strategies_from_frames(
            {"600519": make_frame(periods=180)},
            strategies,
            optimization,
            score_func=lambda symbol, history: (70.0, "always long"),
        )

        self.assertEqual(rows[0]["status"], "ok")
        self.assertIn("validation_total_return_pct", rows[0])
        self.assertIn("test_total_return_pct", rows[0])
        self.assertEqual(rows[0]["selection_basis"], "validation_objective")
        self.assertEqual(rows[0]["score_profile"], "balanced")
        self.assertIn("walk_forward_traded_windows", rows[0])
        self.assertGreaterEqual(rows[0]["walk_forward_window_count"], 1)
        if len(rows) > 1:
            if rows[1]["validation_objective"] == rows[0]["validation_objective"]:
                self.assertGreaterEqual(rows[1]["walk_forward_window_count"], 1)
            else:
                self.assertEqual(rows[1]["walk_forward_window_count"], 0)

    def test_evaluate_walk_forward_from_frames_returns_window_metrics(self):
        optimization = strategy_lab.OptimizationConfig(
            walk_forward_windows=2,
            min_history=20,
        )
        strategy = strategy_lab.Strategy(
            id="s",
            name="s",
            description="",
            config=strategy_lab.backtest.BacktestConfig(min_history=20),
        )

        row = strategy_lab.evaluate_walk_forward_from_frames(
            {"600519": make_frame(periods=100)},
            strategy,
            optimization,
            score_func=lambda symbol, history: (70.0, "always long"),
        )

        self.assertGreaterEqual(row["walk_forward_window_count"], 1)
        self.assertGreaterEqual(row["walk_forward_traded_windows"], 1)

    def test_memoized_score_func_reuses_same_history_window(self):
        calls = []
        cached = strategy_lab.memoized_score_func(
            lambda symbol, history: calls.append((symbol, len(history))) or (70.0, "cached")
        )
        frame = make_frame(periods=90)

        first = cached("600519", frame.iloc[:80].copy())
        second = cached("600519", frame.iloc[:80].copy())

        self.assertEqual(first, second)
        self.assertEqual(calls, [("600519", 80)])

    def test_profile_score_func_changes_reason_label(self):
        frame = make_frame(periods=100)

        score, reason = strategy_lab.score_symbol_history_with_profile("600519", frame, "trend")

        self.assertIsInstance(score, float)
        self.assertIn("trend", reason)

    def test_require_market_frames_fails_when_all_data_sources_fail(self):
        with self.assertRaises(RuntimeError) as context:
            strategy_lab.require_market_frames({}, ["600519", "300750"])

        self.assertIn("没有可用行情数据", str(context.exception))

    def test_require_cache_health_raises_with_rendered_report(self):
        original_inspect = strategy_lab.analyze.inspect_market_cache
        original_render = strategy_lab.analyze.render_market_cache_health
        try:
            strategy_lab.analyze.inspect_market_cache = lambda *args, **kwargs: {"ok": False}
            strategy_lab.analyze.render_market_cache_health = lambda payload: "缓存失败报告"

            with self.assertRaises(RuntimeError) as context:
                strategy_lab.require_cache_health(["600519"], days=120, min_rows=80, max_age_hours=36)
        finally:
            strategy_lab.analyze.inspect_market_cache = original_inspect
            strategy_lab.analyze.render_market_cache_health = original_render

        self.assertEqual(str(context.exception), "缓存失败报告")

    def test_healthy_stocks_from_cache_health_returns_only_usable_symbols(self):
        health = {
            "results": [
                {"stock_code": "600519", "usable": True},
                {"stock_code": "300750", "usable": False},
                {"stock_code": "000001", "usable": True},
            ]
        }

        stocks = strategy_lab.healthy_stocks_from_cache_health(health)

        self.assertEqual(stocks, ["600519", "000001"])

    def test_build_recommendation_payload_marks_paper_gate(self):
        rows = [
            {
                "strategy_id": "candidate",
                "status": "ok",
                "score_profile": "trend",
                "entry_score": 58.0,
                "exit_score": 42.0,
                "max_position_pct": 10.0,
                "max_total_exposure_pct": 40.0,
                "selection_basis": "validation_objective",
                "validation_objective": 2.0,
                "validation_total_return_pct": 3.0,
                "validation_max_drawdown_pct": 4.0,
                "validation_sharpe": 1.1,
                "validation_trade_count": 3,
                "test_objective": 1.0,
                "test_total_return_pct": 2.0,
                "test_max_drawdown_pct": 5.0,
                "test_sharpe": 0.8,
                "test_trade_count": 2,
                "walk_forward_traded_windows": 2,
                "walk_forward_avg_return_pct": 1.0,
            }
        ]

        payload = strategy_lab.build_recommendation_payload(rows)

        self.assertEqual(payload["status"], "candidate_found")
        self.assertTrue(payload["promotion_gate"]["eligible_for_paper_trading"])
        self.assertEqual(payload["recommended_candidate"]["strategy_id"], "candidate")
        self.assertEqual(payload["recommended_candidate"]["score_profile"], "trend")
        self.assertEqual(payload["promotion_gate"]["failed_rules"], [])
        self.assertEqual(payload["next_search"]["recommended_next"], "paper_trade_observation")

    def test_build_recommendation_payload_explains_failed_rules(self):
        rows = [
            {
                "strategy_id": "candidate",
                "status": "ok",
                "score_profile": "trend",
                "entry_score": 58.0,
                "exit_score": 42.0,
                "max_position_pct": 10.0,
                "max_total_exposure_pct": 40.0,
                "selection_basis": "validation_objective",
                "validation_objective": 2.0,
                "validation_total_return_pct": 3.0,
                "validation_max_drawdown_pct": 4.0,
                "validation_sharpe": 1.1,
                "validation_trade_count": 3,
                "test_objective": -10.0,
                "test_total_return_pct": 0.0,
                "test_max_drawdown_pct": 0.0,
                "test_sharpe": 0.0,
                "test_trade_count": 0,
                "walk_forward_traded_windows": 2,
                "walk_forward_avg_return_pct": -1.0,
            }
        ]

        payload = strategy_lab.build_recommendation_payload(rows)

        self.assertFalse(payload["promotion_gate"]["eligible_for_paper_trading"])
        self.assertIn("test_trade_count >= 2", payload["promotion_gate"]["failed_rules"])
        self.assertIn("walk_forward_avg_return_pct > 0", payload["promotion_gate"]["failed_rules"])
        self.assertEqual(payload["next_search"]["recommended_next"], "expand_cache_pool")

    def test_write_recommendation_outputs_json(self):
        rows = [{"status": "failed", "strategy_id": "bad"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            output = pathlib.Path(tmpdir) / "recommendation.json"
            strategy_lab.write_recommendation(rows, output)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "no_candidate")

    def test_strategy_item_from_recommendation_requires_promotion_gate(self):
        payload = {
            "status": "candidate_found",
            "recommended_candidate": {
                "strategy_id": "candidate",
                "entry_score": 58.0,
                "exit_score": 42.0,
                "max_position_pct": 10.0,
                "max_total_exposure_pct": 40.0,
                "validation": {"total_return_pct": 1.0, "max_drawdown_pct": 2.0},
                "test": {"total_return_pct": 1.0, "max_drawdown_pct": 2.0},
            },
            "promotion_gate": {"eligible_for_paper_trading": False},
        }

        with self.assertRaises(ValueError):
            strategy_lab.strategy_item_from_recommendation(payload)

    def test_promote_recommendation_updates_registry_active_paper_strategy(self):
        rows = [
            {
                "strategy_id": "candidate",
                "status": "ok",
                "score_profile": "mean_reversion",
                "entry_score": 58.0,
                "exit_score": 42.0,
                "max_position_pct": 10.0,
                "max_total_exposure_pct": 40.0,
                "selection_basis": "validation_objective",
                "validation_objective": 2.0,
                "validation_total_return_pct": 3.0,
                "validation_max_drawdown_pct": 4.0,
                "validation_sharpe": 1.1,
                "validation_trade_count": 3,
                "test_objective": 1.0,
                "test_total_return_pct": 2.0,
                "test_max_drawdown_pct": 5.0,
                "test_sharpe": 0.8,
                "test_trade_count": 2,
                "walk_forward_traded_windows": 2,
                "walk_forward_avg_return_pct": 1.0,
            }
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = pathlib.Path(tmpdir)
            recommendation = tmp / "recommendation.json"
            registry = tmp / "strategies.json"
            registry.write_text('{"strategies":[]}', encoding="utf-8")
            strategy_lab.write_recommendation(rows, recommendation)
            item = strategy_lab.promote_recommendation_to_registry(
                recommendation,
                registry,
                strategy_id="paper-test",
            )
            payload = json.loads(registry.read_text(encoding="utf-8"))

        self.assertEqual(item["id"], "paper-test")
        self.assertEqual(item["score_profile"], "mean_reversion")
        self.assertEqual(payload["active_paper_strategy_id"], "paper-test")
        self.assertEqual(payload["strategies"][0]["source_strategy_id"], "candidate")


if __name__ == "__main__":
    unittest.main()
