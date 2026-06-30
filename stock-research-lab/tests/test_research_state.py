import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "research_state.py"
SPEC = importlib.util.spec_from_file_location("research_state", MODULE_PATH)
research_state = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = research_state
SPEC.loader.exec_module(research_state)


class ResearchStateTest(unittest.TestCase):
    def run_cli(self, args):
        buf = StringIO()
        with redirect_stdout(buf):
            code = research_state.main(args)
        self.assertEqual(code, 0)
        return json.loads(buf.getvalue())

    def test_watchlist_and_thesis_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = pathlib.Path(tmp)
            self.run_cli(["--state-dir", str(state_dir), "watchlist", "add", "--ticker", "sh600519", "--note", "核心资产"])
            self.run_cli(
                [
                    "--state-dir",
                    str(state_dir),
                    "thesis",
                    "add",
                    "--ticker",
                    "600519",
                    "--thesis",
                    "品牌与现金流优势",
                    "--sell",
                    "ROE连续下滑",
                ]
            )

            health = self.run_cli(["--state-dir", str(state_dir), "health"])

            self.assertEqual(health["counts"]["watchlist"], 1)
            self.assertEqual(health["counts"]["active_theses"], 1)
            self.assertEqual(health["counts"]["theses_missing_sell_conditions"], 0)
            self.assertGreaterEqual(health["score"], 85)

    def test_health_flags_missing_sell_conditions(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = pathlib.Path(tmp)
            self.run_cli(["--state-dir", str(state_dir), "thesis", "add", "--ticker", "000001", "--thesis", "银行修复"])

            health = self.run_cli(["--state-dir", str(state_dir), "health"])

            self.assertEqual(health["counts"]["theses_missing_sell_conditions"], 1)
            self.assertTrue(health["top_actions"])


if __name__ == "__main__":
    unittest.main()
