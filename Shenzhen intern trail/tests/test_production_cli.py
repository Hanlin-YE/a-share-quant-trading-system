from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.cli import command_scan
from src.config import Settings


class ProductionCliTests(unittest.TestCase):
    def settings_without_key(self, root: Path) -> Settings:
        return Settings(
            project_root=root,
            deepseek_api_key="",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="deepseek-chat",
            deepseek_timeout_seconds=1,
            scan_interval_minutes=30,
            run_during_market_hours_only=True,
            strict_news_required=True,
            enable_jin10=False,
            enable_wind=False,
            enable_baidu_hot=False,
            enable_google_trends=False,
            enable_official_media=False,
            jin10_mode="disabled",
            jin10_api_url="",
            jin10_api_key="",
            wind_mode="disabled",
            wind_csv_path="",
        )

    def test_scan_blocks_without_deepseek_key(self) -> None:
        root = Path("test-output-production")
        with patch("src.cli.load_settings", return_value=self.settings_without_key(root)):
            with patch("src.cli.persist_scan_outputs", lambda *args, **kwargs: None):
                result = command_scan(root / "runs", "Asia/Shanghai")
        self.assertEqual(result["strict_status"], "BLOCKED")
        self.assertIn("DEEPSEEK_API_KEY", result["blocked_reason"])
        self.assertEqual(result["buy_plans"], [])

    def test_production_scan_does_not_accept_example_defaults(self) -> None:
        # Production command_scan has no news/market default file arguments; it must use adapters.
        import inspect
        from src import cli

        source = inspect.getsource(cli.command_scan)
        self.assertNotIn("Path(\"data/examples", source)
        self.assertIn("collect_news", source)
        self.assertIn("fetch_realtime_rows", source)


if __name__ == "__main__":
    unittest.main()
