import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "analyze.py"
SPEC = importlib.util.spec_from_file_location("analyze", MODULE_PATH)
analyze = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = analyze
SPEC.loader.exec_module(analyze)


class AnalyzerRiskControlsTest(unittest.TestCase):
    def test_build_ml_dataset_uses_min_edge_threshold(self):
        days = 160
        steps = np.arange(days)
        close = 100 + 0.02 * steps + np.sin(steps / 5) * 0.4
        close[-1] = close[-2] * 1.001
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=days),
                "open": close,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 1000 + (steps % 17) * 20,
            }
        )
        df = analyze.add_indicators(frame)

        _, target, _, forward_return = analyze.build_ml_dataset(df, horizon=1, min_edge=0.003)

        self.assertGreaterEqual(len(target), 80)
        self.assertEqual(int(target.iloc[-1]), 0)
        self.assertGreater(forward_return.iloc[-1], 0)

    def test_time_series_splitter_uses_horizon_gap(self):
        splitter = analyze.make_time_series_splitter(horizon=5)
        x = pd.DataFrame({"value": range(150)})

        for train_idx, test_idx in splitter.split(x):
            self.assertGreaterEqual(test_idx[0] - train_idx[-1], 6)

    def test_position_advice_blocks_low_score_and_large_drawdown(self):
        self.assertIn("0%", analyze.position_advice(44.9, 10, 0.20))
        self.assertIn("0%", analyze.position_advice(80.0, 36, 0.20))

    def test_validate_ohlcv_frame_drops_bad_and_duplicate_rows(self):
        frame = pd.DataFrame(
            [
                ["2024-01-01", 10, 11, 12, 9, 1000],
                ["2024-01-01", 10, 10.5, 11, 9.5, 900],
                ["2024-01-02", 10, 10, 9, 11, 800],
            ],
            columns=["date", "open", "close", "high", "low", "volume"],
        )

        clean, notes = analyze.validate_ohlcv_frame(frame)

        self.assertEqual(len(clean), 1)
        self.assertIn("重复日期", "；".join(notes))
        self.assertIn("OHLC异常", "；".join(notes))

    def test_auto_a_share_prefers_tencent_curl_before_requests(self):
        calls = []

        def fake_curl(stock_code, days):
            calls.append(("curl", stock_code, days))
            return analyze.DataResult(
                pd.DataFrame(
                    {
                        "date": pd.date_range("2026-01-01", periods=80),
                        "open": np.arange(80) + 10,
                        "high": np.arange(80) + 11,
                        "low": np.arange(80) + 9,
                        "close": np.arange(80) + 10,
                        "volume": np.arange(80) + 1000,
                    }
                ),
                stock_code,
                "测试股票",
                "腾讯财经 前复权日线（curl兜底）",
            )

        original_curl = analyze.get_tencent_data_via_curl
        original_requests = analyze.get_tencent_data
        try:
            analyze.get_tencent_data_via_curl = fake_curl
            analyze.get_tencent_data = lambda stock_code, days: calls.append(("requests", stock_code, days))

            result = analyze.get_stock_data("600519", 120, "auto")
        finally:
            analyze.get_tencent_data_via_curl = original_curl
            analyze.get_tencent_data = original_requests

        self.assertIsNotNone(result)
        self.assertEqual(calls[0][0], "curl")
        self.assertNotIn(("requests", "600519", 120), calls)

    def test_premium_source_prefers_tushare_before_fallbacks(self):
        calls = []

        def fake_tushare(stock_code, days):
            calls.append(("tushare", stock_code, days))
            return analyze.DataResult(
                pd.DataFrame(
                    {
                        "date": pd.date_range("2026-01-01", periods=90),
                        "open": np.arange(90) + 10,
                        "high": np.arange(90) + 11,
                        "low": np.arange(90) + 9,
                        "close": np.arange(90) + 10,
                        "volume": np.arange(90) + 1000,
                    }
                ),
                stock_code,
                "测试股票",
                "Tushare Pro A股日线",
            )

        original_tushare = analyze.get_tushare_data
        original_curl = analyze.get_tencent_data_via_curl
        try:
            analyze.get_tushare_data = fake_tushare
            analyze.get_tencent_data_via_curl = lambda stock_code, days: calls.append(("curl", stock_code, days))

            result = analyze.get_stock_data("600519", 120, "premium")
        finally:
            analyze.get_tushare_data = original_tushare
            analyze.get_tencent_data_via_curl = original_curl

        self.assertIsNotNone(result)
        self.assertEqual(calls, [("tushare", "600519", 120)])
        self.assertIn("高质量源策略", result.source_note)

    def test_premium_source_falls_back_when_tushare_unavailable(self):
        calls = []

        def fake_curl(stock_code, days):
            calls.append(("curl", stock_code, days))
            return analyze.DataResult(
                pd.DataFrame(
                    {
                        "date": pd.date_range("2026-01-01", periods=90),
                        "open": np.arange(90) + 10,
                        "high": np.arange(90) + 11,
                        "low": np.arange(90) + 9,
                        "close": np.arange(90) + 10,
                        "volume": np.arange(90) + 1000,
                    }
                ),
                stock_code,
                "测试股票",
                "腾讯财经 前复权日线（curl兜底）",
            )

        original_tushare = analyze.get_tushare_data
        original_curl = analyze.get_tencent_data_via_curl
        try:
            analyze.get_tushare_data = lambda stock_code, days: None
            analyze.get_tencent_data_via_curl = fake_curl

            result = analyze.get_stock_data("600519", 120, "premium")
        finally:
            analyze.get_tushare_data = original_tushare
            analyze.get_tencent_data_via_curl = original_curl

        self.assertIsNotNone(result)
        self.assertEqual(calls, [("curl", "600519", 120)])
        self.assertIn("高质量源策略", result.source_note)

    def test_save_and_read_pushed_market_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(analyze, "PUSH_CACHE_DIR", pathlib.Path(tmpdir)):
                result = analyze.save_pushed_market_data(
                    {
                        "provider": "VendorPush",
                        "stock_code": "600519",
                        "stock_name": "贵州茅台",
                        "bars": [
                            {
                                "trade_date": "20260605",
                                "open": 10,
                                "high": 11,
                                "low": 9,
                                "close": 10.5,
                                "vol": 1000,
                            }
                        ],
                    }
                )
                pushed = analyze.get_pushed_data("600519", days=10, max_age_hours=48)

        self.assertTrue(result["ok"])
        self.assertIsNotNone(pushed)
        self.assertEqual(pushed.source, "VendorPush 推送缓存")
        self.assertEqual(float(pushed.frame.iloc[-1]["close"]), 10.5)

    def test_premium_source_uses_pushed_cache_before_pull_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(analyze, "PUSH_CACHE_DIR", pathlib.Path(tmpdir)):
                analyze.save_pushed_market_data(
                    {
                        "provider": "VendorPush",
                        "stock_code": "600519",
                        "bars": [
                            {"date": "2026-06-05", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000}
                        ],
                    }
                )
                original_tushare = analyze.get_tushare_data
                try:
                    analyze.get_tushare_data = lambda stock_code, days: self.fail("premium should read push cache first")
                    result = analyze.get_stock_data("600519", 120, "premium")
                finally:
                    analyze.get_tushare_data = original_tushare

        self.assertIsNotNone(result)
        self.assertIn("推送缓存", result.source)

    def test_refresh_market_cache_saves_pull_result_as_push_cache(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2026-06-01", periods=3),
                "open": [10, 11, 12],
                "high": [11, 12, 13],
                "low": [9, 10, 11],
                "close": [10.5, 11.5, 12.5],
                "volume": [1000, 1100, 1200],
            }
        )
        original_get_stock_data = analyze.get_stock_data
        try:
            analyze.get_stock_data = lambda stock_code, days, source: analyze.DataResult(
                frame,
                stock_code,
                "测试股票",
                "Tushare Pro A股日线",
                "自动刷新测试",
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                with patch.object(analyze, "PUSH_CACHE_DIR", pathlib.Path(tmpdir)):
                    result = analyze.refresh_market_cache(["600519"], days=120, source="pull")
                    pushed = analyze.get_pushed_data("600519", days=10, max_age_hours=48)
        finally:
            analyze.get_stock_data = original_get_stock_data

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertIsNotNone(pushed)

    def test_import_market_csv_to_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            csv_path = root / "600519.csv"
            csv_path.write_text(
                "date,open,high,low,close,volume\n"
                "2026-06-01,10,11,9,10.5,1000\n"
                "2026-06-02,10.5,11.5,10,11,1100\n",
                encoding="utf-8",
            )
            with patch.object(analyze, "PUSH_CACHE_DIR", root / "cache"):
                result = analyze.import_market_csv_to_cache(
                    csv_path=csv_path,
                    stock_code="600519",
                    stock_name="贵州茅台",
                )
                pushed = analyze.get_pushed_data("600519", days=10, max_age_hours=48)

        self.assertTrue(result["ok"])
        self.assertIsNotNone(pushed)
        self.assertEqual(len(pushed.frame), 2)
        self.assertEqual(float(pushed.frame.iloc[-1]["close"]), 11.0)

    def test_import_market_csv_to_cache_accepts_chinese_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            csv_path = root / "600519_cn.csv"
            csv_path.write_text(
                "日期,开盘价,最高价,最低价,收盘价,成交量\n"
                "2026-06-01,10,11,9,10.5,1000\n",
                encoding="utf-8",
            )
            with patch.object(analyze, "PUSH_CACHE_DIR", root / "cache"):
                result = analyze.import_market_csv_to_cache(csv_path=csv_path, stock_code="600519")

        self.assertTrue(result["ok"])
        self.assertEqual(result["rows"], 1)

    def test_inspect_market_cache_accepts_fresh_pushed_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(analyze, "PUSH_CACHE_DIR", pathlib.Path(tmpdir)):
                analyze.save_pushed_market_data(
                    {
                        "provider": "VendorPush",
                        "stock_code": "600519",
                        "stock_name": "贵州茅台",
                        "bars": [
                            {
                                "date": f"2026-06-{day:02d}",
                                "open": 10 + day,
                                "high": 11 + day,
                                "low": 9 + day,
                                "close": 10.5 + day,
                                "volume": 1000 + day,
                            }
                            for day in range(1, 6)
                        ],
                    }
                )
                result = analyze.inspect_market_cache(["600519"], days=120, min_rows=5, max_age_hours=48)

        self.assertTrue(result["ok"])
        self.assertTrue(result["results"][0]["usable"])
        self.assertIn("推送快照缓存", result["results"][0]["source_hint"])

    def test_render_market_cache_health_reports_missing_cache(self):
        with tempfile.TemporaryDirectory() as push_dir, tempfile.TemporaryDirectory() as pull_dir:
            with patch.object(analyze, "PUSH_CACHE_DIR", pathlib.Path(push_dir)):
                with patch.object(analyze, "CACHE_DIR", pathlib.Path(pull_dir)):
                    result = analyze.inspect_market_cache(["600519"], days=120, min_rows=5, max_age_hours=48)
                    report = analyze.render_market_cache_health(result)

        self.assertFalse(result["ok"])
        self.assertIn("总体结论: 失败", report)
        self.assertIn("推送缓存不存在", report)

    def test_inspect_market_cache_accepts_longer_pull_cache(self):
        with tempfile.TemporaryDirectory() as push_dir, tempfile.TemporaryDirectory() as pull_dir:
            cache_dir = pathlib.Path(pull_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "tencent_600519_360.json").write_text(
                '{"saved_at":"2099-01-01T00:00:00","text":"stub"}',
                encoding="utf-8",
            )
            with patch.object(analyze, "PUSH_CACHE_DIR", pathlib.Path(push_dir)):
                with patch.object(analyze, "CACHE_DIR", cache_dir):
                    result = analyze.inspect_market_cache(["600519"], days=260, min_rows=5, max_age_hours=48)

        self.assertTrue(result["ok"])
        pull = result["results"][0]["pull_caches"][0]
        self.assertEqual(pull["cache_days"], 360)
        self.assertIn("tencent_600519_360.json", pull["path"])

    def test_discover_cached_stock_pool_returns_usable_symbols(self):
        with tempfile.TemporaryDirectory() as push_dir, tempfile.TemporaryDirectory() as pull_dir:
            cache_dir = pathlib.Path(pull_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "tencent_600519_360.json").write_text(
                '{"saved_at":"2099-01-01T00:00:00","text":"stub"}',
                encoding="utf-8",
            )
            (cache_dir / "tencent_300750_120.json").write_text(
                '{"saved_at":"2099-01-01T00:00:00","text":"stub"}',
                encoding="utf-8",
            )
            with patch.object(analyze, "PUSH_CACHE_DIR", pathlib.Path(push_dir)):
                with patch.object(analyze, "CACHE_DIR", cache_dir):
                    result = analyze.discover_cached_stock_pool(days=260, min_rows=5, max_age_hours=48)

        self.assertTrue(result["ok"])
        self.assertEqual(result["stocks"], ["600519"])

    def test_failed_history_report_includes_fetch_errors_and_realtime_quote(self):
        original_get_stock_data = analyze.get_stock_data
        original_realtime = analyze.get_tencent_realtime_quote
        try:
            def fake_get_stock_data(stock_code, days, source):
                analyze.record_fetch_error("腾讯curl", "未返回qfqday/day K线")
                return None

            analyze.get_stock_data = fake_get_stock_data
            analyze.get_tencent_realtime_quote = (
                lambda stock_code: "实时行情兜底: sh600519 贵州茅台 当前价=1281.91"
            )

            report = analyze.check_stock_data("600519", days=120, source="auto")
        finally:
            analyze.get_stock_data = original_get_stock_data
            analyze.get_tencent_realtime_quote = original_realtime

        self.assertIn("数据检查失败", report)
        self.assertIn("腾讯curl", report)
        self.assertIn("实时行情兜底", report)

    def test_health_check_blocks_product_gate_when_any_probe_fails(self):
        original_probe = analyze.probe_stock_data
        try:
            analyze.probe_stock_data = lambda stock, days, source: analyze.DataCheckProbe(
                passed=(stock == "600519"),
                stock_code=stock,
                stock_name="贵州茅台" if stock == "600519" else "未知",
                source="腾讯财经 前复权日线（curl兜底）" if stock == "600519" else "",
                row_count=120 if stock == "600519" else 0,
                start_date="2025-12-01" if stock == "600519" else "",
                end_date="2026-06-03" if stock == "600519" else "",
                error_summary="" if stock == "600519" else "腾讯curl: 退出码6",
                staged_error_summary="" if stock == "600519" else "腾讯curl[1]: 退出码6",
                realtime_quote="" if stock == "600519" else "实时行情兜底也失败",
            )

            report = analyze.render_health_check(["600519", "000001"], days=120, source="auto")
        finally:
            analyze.probe_stock_data = original_probe

        self.assertIn("总体结论: 失败 (1/2 通过)", report)
        self.assertIn("产品门禁: 不建议继续跑完整分析", report)
        self.assertIn("FAIL 000001", report)

    def test_health_check_passes_when_all_probes_pass(self):
        original_probe = analyze.probe_stock_data
        try:
            analyze.probe_stock_data = lambda stock, days, source: analyze.DataCheckProbe(
                passed=True,
                stock_code=stock,
                stock_name="测试股票",
                source="腾讯财经 前复权日线（curl兜底）",
                row_count=120,
                start_date="2025-12-01",
                end_date="2026-06-03",
            )

            report = analyze.render_health_check(["600519", "000001"], days=120, source="auto")
        finally:
            analyze.probe_stock_data = original_probe

        self.assertIn("总体结论: 通过 (2/2 通过)", report)
        self.assertIn("产品门禁: 可以继续跑完整单票分析", report)

    def test_split_stock_list_accepts_chinese_comma(self):
        self.assertEqual(analyze.split_stock_list("600519， 000001,300750"), ["600519", "000001", "300750"])

    def test_observe_scan_keeps_passed_symbols_when_others_fail(self):
        original_probe = analyze.probe_stock_data
        try:
            analyze.probe_stock_data = lambda stock, days, source: analyze.DataCheckProbe(
                passed=(stock == "600519"),
                stock_code=stock,
                stock_name="贵州茅台" if stock == "600519" else "未知",
                source="腾讯财经 前复权日线（curl兜底）" if stock == "600519" else "",
                row_count=121 if stock == "600519" else 0,
                start_date="2025-12-03" if stock == "600519" else "",
                end_date="2026-06-05" if stock == "600519" else "",
                staged_error_summary="" if stock == "600519" else "curl[1]: 退出码6",
                realtime_quote=(
                    "实时行情兜底: sh600519 贵州茅台 当前价=1271.50"
                    if stock == "600519"
                    else ""
                ),
            )

            report = analyze.render_observe_scan(["600519", "300750"], days=120, source="auto")
        finally:
            analyze.probe_stock_data = original_probe

        self.assertIn("当前可观测: 1/2", report)
        self.assertIn("600519 贵州茅台", report)
        self.assertIn("暂不纳入观察", report)
        self.assertIn("300750", report)

    def test_pool_scan_builds_pool_and_reports_failed_symbols(self):
        original_get_stock_data = analyze.get_stock_data
        original_preflight = analyze.a_share_network_preflight
        try:
            def fake_get_stock_data(stock_code, days, source):
                if stock_code == "300750":
                    analyze.record_fetch_error("腾讯curl", "退出码6")
                    return None
                steps = np.arange(100)
                close = 100 + steps * 0.2
                frame = pd.DataFrame(
                    {
                        "date": pd.date_range("2026-01-01", periods=100),
                        "open": close,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 1000 + steps,
                    }
                )
                return analyze.DataResult(frame, stock_code, "测试股票", "测试源")

            analyze.get_stock_data = fake_get_stock_data
            analyze.a_share_network_preflight = lambda: (True, "腾讯行情域名预检通过")

            report = analyze.render_pool_scan(["600519", "300750"], days=120, source="auto")
        finally:
            analyze.get_stock_data = original_get_stock_data
            analyze.a_share_network_preflight = original_preflight

        self.assertIn("A股训练股票池构建", report)
        self.assertIn("可评分: 1", report)
        self.assertIn("600519 测试股票", report)
        self.assertIn("取数失败剔除", report)
        self.assertIn("300750", report)

    def test_pool_scan_uses_cache_only_when_network_preflight_fails(self):
        original_preflight = analyze.a_share_network_preflight
        original_tencent_curl = analyze.get_tencent_data_via_curl
        calls = []
        try:
            analyze.a_share_network_preflight = lambda: (False, "curl[1]: 退出码6")

            def fake_tencent_curl(stock_code, days, allow_network=True):
                calls.append((stock_code, allow_network))
                if stock_code != "600519":
                    analyze.record_fetch_error("行情缓存", f"tencent_{stock_code}_{days}.json 不存在")
                    return None
                frame = pd.DataFrame(
                    {
                        "date": pd.date_range("2026-01-01", periods=100),
                        "open": np.linspace(100, 120, 100),
                        "high": np.linspace(101, 121, 100),
                        "low": np.linspace(99, 119, 100),
                        "close": np.linspace(100, 120, 100),
                        "volume": np.linspace(1000, 1200, 100),
                    }
                )
                return analyze.DataResult(frame, stock_code, "贵州茅台", "腾讯缓存")

            analyze.get_tencent_data_via_curl = fake_tencent_curl

            report = analyze.render_pool_scan(
                ["600519", "300750"],
                days=120,
                source="auto",
                allow_cache_pool=True,
            )
        finally:
            analyze.a_share_network_preflight = original_preflight
            analyze.get_tencent_data_via_curl = original_tencent_curl

        self.assertIn("网络预检: 失败", report)
        self.assertIn("600519 贵州茅台", report)
        self.assertIn("300750", report)
        self.assertEqual(calls, [("600519", False), ("300750", False)])

    def test_pool_scan_blocks_when_network_preflight_fails_by_default(self):
        original_preflight = analyze.a_share_network_preflight
        original_tencent_curl = analyze.get_tencent_data_via_curl
        try:
            analyze.a_share_network_preflight = lambda: (False, "curl[1]: 退出码6")
            analyze.get_tencent_data_via_curl = lambda *args, **kwargs: self.fail(
                "pool scan should not read cache unless explicitly allowed"
            )

            report = analyze.render_pool_scan(["600519"], days=120, source="auto")
        finally:
            analyze.a_share_network_preflight = original_preflight
            analyze.get_tencent_data_via_curl = original_tencent_curl

        self.assertIn("股票池构建失败", report)
        self.assertIn("实盘训练门禁", report)
        self.assertIn("--allow-cache-pool", report)

    def test_sector_representative_universe_covers_multiple_sectors(self):
        stocks, note = analyze.build_sector_representative_universe(
            include_dynamic=False,
            dynamic_limit=10,
        )

        self.assertIn("板块代表池", note)
        self.assertGreaterEqual(len(stocks), 30)
        for code in ["600519", "000001", "300750", "688981", "300308", "600760", "300760"]:
            self.assertIn(code, stocks)


if __name__ == "__main__":
    unittest.main()
