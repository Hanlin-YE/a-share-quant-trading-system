import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "import_shenzhen_trail.py"
SPEC = importlib.util.spec_from_file_location("import_shenzhen_trail", MODULE_PATH)
import_shenzhen_trail = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = import_shenzhen_trail
SPEC.loader.exec_module(import_shenzhen_trail)


class ImportShenzhenTrailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)
        self.ledger = self.root / "ledger"
        self.account_path = self.root / "account.json"
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
        self.run_path = self.root / "latest.json"
        self.run_path.write_text(
            json.dumps(
                {
                    "system": "Shenzhen intern trail",
                    "strict_status": "PASS",
                    "run_date": "2026-06-30",
                    "run_slot": "1002",
                    "production_note": "test production scan",
                    "thresholds": {"large_order_ratio_min": 0.12},
                    "buy_plans": [
                        {
                            "code": "603019",
                            "name": "中科曙光",
                            "trigger": "A_BREAKOUT",
                            "limit_price": 104.87,
                            "pct_change_at_plan": 7.26,
                            "leader_rank": 2,
                            "fallback_from": "",
                            "reason": "龙二跟随计划",
                            "risk_note": "研究计划，不自动下单。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        pa = import_shenzhen_trail.paper_account
        self.patches = [
            patch.object(pa, "JOURNAL_DIR", self.root),
            patch.object(pa, "LEDGER_DIR", self.ledger),
            patch.object(pa, "ACCOUNT_PATH", self.account_path),
            patch.object(pa, "PORTFOLIO_LEDGER_PATH", self.root / "portfolio_ledger.csv"),
            patch.object(pa, "WORKBOOK_PATH", self.root / "book.xlsx"),
            patch.object(pa, "ORDERS_PATH", self.ledger / "orders.csv"),
            patch.object(pa, "POSITIONS_PATH", self.ledger / "positions.csv"),
            patch.object(pa, "EQUITY_PATH", self.ledger / "equity_curve.csv"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_import_adds_trade_plan_only_and_deduplicates(self):
        first = import_shenzhen_trail.import_plans(self.run_path)
        second = import_shenzhen_trail.import_plans(self.run_path)

        self.assertEqual(first["appended_count"], 1)
        self.assertEqual(second["appended_count"], 0)
        rows = import_shenzhen_trail.paper_account.read_rows(
            import_shenzhen_trail.paper_account.PORTFOLIO_LEDGER_PATH
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["row_type"], "TRADE_PLAN")
        self.assertEqual(row["symbol"], "603019")
        self.assertEqual(row["side"], "BUY")
        self.assertEqual(row["strategy_id"], "shenzhen-intern-trail-v1")
        self.assertEqual(row["status"], "pending")
        self.assertIn("仅导入为TRADE_PLAN", row["notes"])
        self.assertTrue(import_shenzhen_trail.paper_account.WORKBOOK_PATH.exists())


if __name__ == "__main__":
    unittest.main()
