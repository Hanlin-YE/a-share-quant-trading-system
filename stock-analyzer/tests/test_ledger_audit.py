import importlib.util
import pathlib
import sys
import unittest


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "ledger_audit.py"
SPEC = importlib.util.spec_from_file_location("ledger_audit", MODULE_PATH)
ledger_audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ledger_audit
SPEC.loader.exec_module(ledger_audit)


class LedgerAuditTest(unittest.TestCase):
    def test_detects_equity_continuity_break(self):
        rows = [
            {"date": "2026-06-23", "row_type": "DAY_SUMMARY", "start_equity": "100", "end_equity": "110"},
            {"date": "2026-06-24", "row_type": "DAY_SUMMARY", "start_equity": "109", "end_equity": "120"},
        ]

        issues = ledger_audit.audit_equity_continuity(rows)

        self.assertEqual(issues[0]["type"], "equity_continuity_break")
        self.assertEqual(issues[0]["difference"], -1.0)

    def test_detects_non_summary_equity_values(self):
        rows = [
            {"date": "2026-06-23", "row_type": "BACKTEST", "start_equity": "1000000", "end_equity": "1080000"},
        ]

        issues = ledger_audit.audit_non_summary_equity(rows)

        self.assertEqual(issues[0]["type"], "non_summary_equity_values")
        self.assertEqual(issues[0]["row_type"], "BACKTEST")

    def test_detects_sell_that_creates_odd_lot(self):
        rows = [
            {"date": "2026-06-23", "row_type": "TRADE", "time": "13:00", "symbol": "300750", "side": "BUY", "quantity": "100"},
            {"date": "2026-06-24", "row_type": "TRADE", "time": "10:07", "symbol": "300750", "side": "SELL", "quantity": "30"},
        ]

        issues = ledger_audit.audit_trade_rules(rows)
        types = {issue["type"] for issue in issues}

        self.assertIn("invalid_sell_lot", types)
        self.assertIn("odd_lot_remainder", types)

    def test_detects_invalid_trade_time_and_t_plus_one(self):
        rows = [
            {"date": "2026-06-23", "row_type": "TRADE", "time": "13:00", "symbol": "600000", "side": "BUY", "quantity": "100"},
            {"date": "2026-06-23", "row_type": "TRADE", "time": "12:00", "symbol": "600000", "side": "SELL", "quantity": "100"},
        ]

        issues = ledger_audit.audit_trade_rules(rows)
        types = {issue["type"] for issue in issues}

        self.assertIn("invalid_trade_time", types)
        self.assertIn("t_plus_one_violation", types)

    def test_audit_finding_rows_do_not_put_audit_label_in_stock_name(self):
        result = {
            "issues": [
                {
                    "type": "odd_lot_remainder",
                    "csv_line": 38,
                    "date": "2026-06-24",
                    "symbol": "300750",
                    "quantity": 30,
                    "remaining": 70,
                }
            ]
        }

        rows = ledger_audit.audit_finding_rows(result, "2026-06-26")

        self.assertEqual(rows[0]["symbol"], "300750")
        self.assertEqual(rows[0]["name"], "")
        self.assertEqual(rows[0]["action"], "审计发现")


if __name__ == "__main__":
    unittest.main()
