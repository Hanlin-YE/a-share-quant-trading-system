import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "ops_report.py"
SPEC = importlib.util.spec_from_file_location("ops_report", MODULE_PATH)
ops_report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ops_report
SPEC.loader.exec_module(ops_report)


class OpsReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.ledger = self.root / "ledger"
        self.reviews = self.root / "reviews"
        self.strategy_runs = self.root / "strategy-runs"
        self.ledger.mkdir()
        self.strategy_runs.mkdir()
        (self.root / "portfolio_ledger.csv").write_text(
            "date,section,row_type,time,symbol,name,side,action,quantity,price,avg_cost,gross_amount,commission,stamp_tax,transfer_fee,total_cost,net_amount,cash,stock_value,market_value,start_equity,end_equity,daily_pnl,daily_return_pct,realized_pnl,unrealized_pnl,unrealized_pnl_pct,total_exposure_pct,weight_pct,max_drawdown_pct,risk_state,strategy_tag,strategy_id,score_profile,factor_weights,strategy_status,reason,thesis,review_date,status,notes\n"
            "2026-06-05,2026-06-05 组合汇总,DAY_SUMMARY,,,,,,,,,,,,,,,997616.47,0,,1000000,997616.47,-2383.53,-0.2384,,,,0,,-0.2384,OK,,,,,,,,,,test\n"
            "2026-06-05,2026-06-05 交易,TRADE,13:00,600000,浦发银行,BUY,买入,100,9.23,,923,5,0,0.01,5.01,-928.01,,,,,,,,,,,,,,,stable,stable,,,,test,,,filled,\n",
            encoding="utf-8",
        )
        (self.ledger / "equity_curve.csv").write_text(
            "date,start_equity,end_equity,daily_pnl,daily_return_pct,cash,stock_value,total_exposure_pct,max_drawdown_pct,risk_state,notes\n"
            "2026-06-05,1000000,997616.47,-2383.53,-0.2384,997616.47,0,0,-0.2384,OK,test\n",
            encoding="utf-8",
        )
        (self.ledger / "positions.csv").write_text(
            "date,symbol,name,side,quantity,avg_cost,last_price,market_value,unrealized_pnl,unrealized_pnl_pct,weight_pct,thesis,status,review_date,notes\n",
            encoding="utf-8",
        )
        (self.ledger / "orders.csv").write_text(
            "date,time,symbol,name,action,side,quantity,price,gross_amount,commission,stamp_tax,transfer_fee,total_cost,net_amount,reason,strategy_tag,status,notes\n"
            "2026-06-05,13:00,600000,浦发银行,买入,BUY,100,9.23,923,5,0,0.01,5.01,-928.01,test,stable,filled,\n",
            encoding="utf-8",
        )
        (self.strategy_runs / "latest.csv").write_text(
            "strategy_id,strategy_name,total_return_pct,annualized_return_pct,max_drawdown_pct,daily_win_rate_pct,sharpe,trade_count,avg_exposure_pct,final_equity,notes\n"
            "score-standard-v1,评分标准策略 v1,1.2,2.3,3.4,55,0.8,10,20,1012000,\n",
            encoding="utf-8",
        )
        self.patches = [
            patch.object(ops_report.paper_account, "PORTFOLIO_LEDGER_PATH", self.root / "portfolio_ledger.csv"),
            patch.object(ops_report.paper_account, "EQUITY_PATH", self.ledger / "equity_curve.csv"),
            patch.object(ops_report.paper_account, "POSITIONS_PATH", self.ledger / "positions.csv"),
            patch.object(ops_report.paper_account, "ORDERS_PATH", self.ledger / "orders.csv"),
            patch.object(ops_report, "STRATEGY_RUNS_DIR", self.strategy_runs),
            patch.object(ops_report, "REVIEWS_DIR", self.reviews),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_render_ops_report_includes_account_and_strategy(self):
        report = ops_report.render_ops_report("2026-06-05")

        self.assertIn("期末权益: 997616.47", report)
        self.assertIn("score-standard-v1", report)
        self.assertIn("600000", report)

    def test_write_report_creates_markdown_file(self):
        path = ops_report.write_report("2026-06-05", "hello")

        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), "hello")


if __name__ == "__main__":
    unittest.main()
