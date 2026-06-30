import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "strategy_governance.py"
SPEC = importlib.util.spec_from_file_location("strategy_governance", MODULE_PATH)
strategy_governance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = strategy_governance
SPEC.loader.exec_module(strategy_governance)


class StrategyGovernanceTest(unittest.TestCase):
    def test_data_cache_failure_blocks_parameter_search(self):
        payload = strategy_governance.governance_from_review(
            {
                "run_date": "2026-06-11",
                "failure_bucket": "data_cache_unhealthy",
                "order_count": 0,
                "equity": {},
            }
        )

        self.assertEqual(payload["profile"], "blocked_data")
        self.assertFalse(payload["permissions"]["allow_parameter_search"])
        self.assertFalse(payload["permissions"]["allow_promotion"])

    def test_stop_risk_uses_defensive_profile_without_promotion(self):
        payload = strategy_governance.governance_from_review(
            {
                "run_date": "2026-06-11",
                "failure_bucket": "pipeline_ok",
                "order_count": 1,
                "equity": {"risk_state": "STOP"},
            }
        )

        self.assertEqual(payload["profile"], "defensive")
        self.assertTrue(payload["permissions"]["allow_parameter_search"])
        self.assertFalse(payload["permissions"]["allow_new_entries"])
        self.assertFalse(payload["permissions"]["allow_promotion"])

    def test_pipeline_ok_without_orders_uses_exploration_profile(self):
        payload = strategy_governance.governance_from_review(
            {
                "run_date": "2026-06-11",
                "failure_bucket": "pipeline_ok",
                "order_count": 0,
                "equity": {},
            }
        )

        self.assertEqual(payload["profile"], "exploration")
        self.assertTrue(payload["permissions"]["allow_parameter_search"])

    def test_review_and_govern_uses_latest_available_record_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            day = root / "2026-06-10"
            day.mkdir(parents=True)
            (day / "preopen.json").write_text(
                json.dumps({"ok": False, "cache_health": {"ok": False}}),
                encoding="utf-8",
            )

            payload = strategy_governance.review_and_govern("2026-06-11", root=root)

        self.assertEqual(payload["source_run_date"], "2026-06-10")
        self.assertEqual(payload["requested_run_date"], "2026-06-11")
        self.assertEqual(payload["profile"], "blocked_data")

    def test_apply_strategy_feedback_probation_for_single_bad_day_and_logs_single_ledger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            registry = root / "strategies.json"
            ledger = root / "portfolio_ledger.csv"
            registry.write_text(
                json.dumps(
                    {
                        "active_paper_strategy_id": "weak",
                        "strategies": [
                            {
                                "id": "weak",
                                "name": "弱策略",
                                "score_profile": "trend",
                                "paper_weight": 1.0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            review = {
                "run_date": "2026-06-12",
                "failure_bucket": "pipeline_ok",
                "order_count": 1,
                "equity": {
                    "daily_pnl": "-15000",
                    "daily_return_pct": "-1.5",
                    "risk_state": "STOP",
                },
            }

            result = strategy_governance.apply_strategy_feedback(
                review,
                registry_path=registry,
                ledger_path=ledger,
            )
            payload = json.loads(registry.read_text(encoding="utf-8"))
            ledger_rows = ledger.read_text(encoding="utf-8")

        self.assertEqual(result["strategy_status"], "probation")
        self.assertEqual(payload["strategies"][0]["strategy_status"], "probation")
        self.assertEqual(payload["active_paper_strategy_id"], "weak")
        self.assertLess(payload["strategies"][0]["paper_weight"], 1.0)
        self.assertIn("STRATEGY_FEEDBACK", ledger_rows)
        self.assertIn("weak", ledger_rows)

    def test_strategy_feedback_retires_only_after_repeated_failures(self):
        decision = strategy_governance.strategy_feedback_decision(
            {
                "run_date": "2026-06-12",
                "failure_bucket": "pipeline_ok",
                "order_count": 1,
                "equity": {
                    "daily_pnl": "-15000",
                    "daily_return_pct": "-1.5",
                    "risk_state": "STOP",
                },
            },
            {
                "id": "weak",
                "paper_weight": 1.0,
                "failure_count": 2,
                "success_count": 0,
                "strategy_status": "probation",
            },
        )

        self.assertEqual(decision["strategy_status"], "retired")
        self.assertEqual(decision["failure_count"], 3)


if __name__ == "__main__":
    unittest.main()
