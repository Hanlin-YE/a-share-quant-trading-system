import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "daily_pipeline.py"
SPEC = importlib.util.spec_from_file_location("daily_pipeline", MODULE_PATH)
daily_pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = daily_pipeline
SPEC.loader.exec_module(daily_pipeline)


class DailyPipelineTest(unittest.TestCase):
    def test_write_and_read_stage_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            payload = {"stage": "open", "run_date": "2026-06-11", "ok": True}
            path = daily_pipeline.write_stage_record(payload, root=root)
            loaded = daily_pipeline.read_stage_record("2026-06-11", "open", root=root)

        self.assertEqual(path.name, "open.json")
        self.assertEqual(loaded["stage"], "open")
        self.assertTrue(loaded["ok"])

    def test_preopen_stops_when_cache_unhealthy(self):
        original_health = daily_pipeline.analyze.inspect_market_cache
        original_govern = daily_pipeline.strategy_governance.review_and_govern
        try:
            daily_pipeline.analyze.inspect_market_cache = lambda *args, **kwargs: {"ok": False}
            daily_pipeline.strategy_governance.review_and_govern = lambda run_date, **kwargs: {
                "profile": "blocked_data",
                "permissions": {"allow_parameter_search": False, "allow_promotion": False},
                "reason": "blocked",
            }

            result = daily_pipeline.run_stage(
                stage="preopen",
                stocks=["600519"],
                days=120,
                source="premium",
                run_date="2026-06-11",
            )
        finally:
            daily_pipeline.analyze.inspect_market_cache = original_health
            daily_pipeline.strategy_governance.review_and_govern = original_govern

        self.assertFalse(result["ok"])
        self.assertIn("next_action", result)

    def test_preopen_reads_previous_close_summary_when_record_exists(self):
        original_health = daily_pipeline.analyze.inspect_market_cache
        original_read = daily_pipeline.read_stage_record
        original_govern = daily_pipeline.strategy_governance.review_and_govern
        try:
            daily_pipeline.analyze.inspect_market_cache = lambda *args, **kwargs: {"ok": False}
            daily_pipeline.strategy_governance.review_and_govern = lambda run_date, **kwargs: {
                "profile": "blocked_data",
                "permissions": {"allow_parameter_search": False, "allow_promotion": False},
                "reason": "blocked",
            }
            daily_pipeline.read_stage_record = lambda run_date, stage: {
                "ok": True,
                "generated_at": "2026-06-11T15:10:00",
                "settlement": {"end_equity": 1},
            } if stage == "close" else None

            result = daily_pipeline.run_stage(
                stage="preopen",
                stocks=["600519"],
                days=120,
                source="premium",
                run_date="2026-06-11",
            )
        finally:
            daily_pipeline.analyze.inspect_market_cache = original_health
            daily_pipeline.read_stage_record = original_read
            daily_pipeline.strategy_governance.review_and_govern = original_govern

        self.assertIn("previous_close_summary", result)
        self.assertTrue(result["previous_close_summary"]["has_settlement"])

    def test_preopen_blocks_optimization_when_governance_disallows_search(self):
        original_health = daily_pipeline.analyze.inspect_market_cache
        original_govern = daily_pipeline.strategy_governance.review_and_govern
        original_optimize = daily_pipeline.optimize_and_optionally_promote
        try:
            daily_pipeline.analyze.inspect_market_cache = lambda *args, **kwargs: {"ok": True}
            daily_pipeline.strategy_governance.review_and_govern = lambda run_date, **kwargs: {
                "profile": "blocked_data",
                "permissions": {"allow_parameter_search": False, "allow_promotion": False},
                "reason": "governance blocked",
            }
            daily_pipeline.optimize_and_optionally_promote = lambda *args, **kwargs: self.fail("must not optimize")

            result = daily_pipeline.run_stage(
                stage="preopen",
                stocks=["600519"],
                days=120,
                source="premium",
                run_date="2026-06-11",
            )
        finally:
            daily_pipeline.analyze.inspect_market_cache = original_health
            daily_pipeline.strategy_governance.review_and_govern = original_govern
            daily_pipeline.optimize_and_optionally_promote = original_optimize

        self.assertFalse(result["ok"])
        self.assertEqual(result["next_action"], "governance blocked")

    def test_open_stage_dry_run_does_not_write_orders(self):
        package = {
            "ok": True,
            "decisions": [
                {
                    "symbol": "600519",
                    "name": "贵州茅台",
                    "action": "BUY",
                    "side": "BUY",
                    "quantity": 100,
                    "price": 100.0,
                    "strategy_id": "test",
                    "reason": "test",
                }
            ],
        }
        calls = []
        original_build = daily_pipeline.paper_execute.build_decision_package
        original_execute = daily_pipeline.paper_execute.execute_decisions
        try:
            daily_pipeline.paper_execute.build_decision_package = lambda *args, **kwargs: package

            def fake_execute(payload, trade_date, trade_time, dry_run=True):
                calls.append((trade_date, trade_time, dry_run))
                return [{"dry_run": dry_run}]

            daily_pipeline.paper_execute.execute_decisions = fake_execute
            result = daily_pipeline.run_stage(
                stage="open",
                stocks=["600519"],
                days=120,
                source="premium",
                run_date="2026-06-11",
            )
        finally:
            daily_pipeline.paper_execute.build_decision_package = original_build
            daily_pipeline.paper_execute.execute_decisions = original_execute

        self.assertTrue(result["ok"])
        self.assertIn("风险暴露", result["monitoring_note"])
        self.assertEqual(calls, [("2026-06-11", "09:30", True)])

    def test_close_stage_execute_settles_and_writes_report(self):
        package = {
            "ok": True,
            "decisions": [{"symbol": "600519", "name": "贵州茅台", "price": 100.0}],
        }
        original_build = daily_pipeline.paper_execute.build_decision_package
        original_settle = daily_pipeline.paper_account.settle_day
        original_active = daily_pipeline.paper_account.active_positions
        original_write = daily_pipeline.ops_report.write_report
        original_render = daily_pipeline.ops_report.render_ops_report
        original_review = daily_pipeline.pipeline_review.review_pipeline_day
        try:
            daily_pipeline.paper_execute.build_decision_package = lambda *args, **kwargs: package
            daily_pipeline.paper_account.active_positions = lambda: {}
            daily_pipeline.paper_account.settle_day = lambda **kwargs: {"date": kwargs["settle_date"], "end_equity": 1}
            daily_pipeline.ops_report.render_ops_report = lambda report_date: f"report {report_date}"
            daily_pipeline.pipeline_review.review_pipeline_day = lambda run_date: {"run_date": run_date, "failure_bucket": "pipeline_ok"}
            with tempfile.TemporaryDirectory() as tmpdir:
                output = pathlib.Path(tmpdir) / "report.md"
                daily_pipeline.ops_report.write_report = lambda report_date, content: output
                result = daily_pipeline.run_stage(
                    stage="close",
                    stocks=["600519"],
                    days=120,
                    source="premium",
                    run_date="2026-06-11",
                    execute=True,
                )
        finally:
            daily_pipeline.paper_execute.build_decision_package = original_build
            daily_pipeline.paper_account.settle_day = original_settle
            daily_pipeline.paper_account.active_positions = original_active
            daily_pipeline.ops_report.write_report = original_write
            daily_pipeline.ops_report.render_ops_report = original_render
            daily_pipeline.pipeline_review.review_pipeline_day = original_review

        self.assertTrue(result["ok"])
        self.assertEqual(result["settlement"]["date"], "2026-06-11")
        self.assertTrue(result["ops_report"].endswith("report.md"))
        self.assertEqual(result["pipeline_review"]["failure_bucket"], "pipeline_ok")


if __name__ == "__main__":
    unittest.main()
