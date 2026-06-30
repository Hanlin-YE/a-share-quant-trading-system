import importlib.util
import os
import pathlib
import sys
import unittest
from unittest.mock import patch


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "web_app.py"
SPEC = importlib.util.spec_from_file_location("web_app", MODULE_PATH)
web_app = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = web_app
SPEC.loader.exec_module(web_app)


class WebConsultingPayloadTest(unittest.TestCase):
    def test_build_analysis_response_extracts_consulting_summary(self):
        original_analyze_stock = web_app.analyze.analyze_stock
        try:
            web_app.analyze.analyze_stock = lambda stock, days, source, horizon: """
量化研究决策报告 - 600519 (贵州茅台)
============================================================
分析时间: 2026-06-06 10:30:00
数据源: 腾讯财经 前复权日线
数据范围: 2025-06-01 至 2026-06-05 (245个交易日)
当前价格: 1281.91 (+1.23%)
综合评分: 68.5/100
交易建议: 偏积极观察 / 等待确认

评分拆解
- 技术指标分: 72.0/100
- 机器学习分: 61.0/100，未来5日收益超过0.30%的概率=61.0%
- 风险韧性分: 74.0/100

信号解释
- 均线结构: MA5>MA10, MA10>MA20
- RSI(14)=56.20，处于中性区

技术指标
- MA5=1287.92, MA10=1290.38, MA20=1310.12, MA60=1388.07
- RSI(14)=35.78, KDJ-J=28.86, MACD柱=0.7296
- 20日年化波动率=21.78%, ATR(14)/收盘价=2.21%

风控
- 近360日最大回撤: 18.20% OK
- 单标的仓位建议 ≤12.0%，仅适合回测验证后的分批试错，跌破风控位减仓。
风险提示: 本报告只用于量化研究和辅助决策，不构成投资建议或自动交易信号。
""".strip()

            payload = web_app.build_analysis_response("600519", days=360, source="auto", horizon=5)
        finally:
            web_app.analyze.analyze_stock = original_analyze_stock

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["stock_code"], "600519")
        self.assertEqual(payload["stock_name"], "贵州茅台")
        self.assertEqual(payload["suggestion"], "偏积极观察 / 等待确认")
        self.assertEqual(payload["scores"]["final"], 68.5)
        self.assertEqual(payload["scores"]["technical"], 72.0)
        self.assertEqual(payload["scores"]["machine_learning"], 61.0)
        self.assertEqual(payload["scores"]["risk"], 74.0)
        self.assertEqual(payload["price"]["close"], 1281.91)
        self.assertEqual(payload["price"]["change_pct"], 1.23)
        self.assertIn("单标的仓位建议", payload["risk_controls"][1])
        self.assertEqual(payload["signals"][0], "均线结构: MA5>MA10, MA10>MA20")
        self.assertEqual(payload["technical_metrics"]["ma_5"], 1287.92)
        self.assertEqual(payload["technical_metrics"]["rsi_14"], 35.78)
        self.assertEqual(payload["technical_metrics"]["kdj_j"], 28.86)
        self.assertEqual(payload["technical_metrics"]["macd_hist"], 0.7296)
        self.assertEqual(payload["technical_metrics"]["volatility_20_pct"], 21.78)
        self.assertEqual(payload["technical_metrics"]["atr_pct_14"], 2.21)
        self.assertEqual(payload["technical_metrics"]["max_drawdown_pct"], 18.2)

    def test_build_analysis_response_marks_analysis_errors(self):
        original_analyze_stock = web_app.analyze.analyze_stock
        try:
            web_app.analyze.analyze_stock = lambda stock, days, source, horizon: "股票代码格式错误：当前 A 股模式请输入 6 位代码"

            payload = web_app.build_analysis_response("abc", days=360, source="auto", horizon=5)
        finally:
            web_app.analyze.analyze_stock = original_analyze_stock

        self.assertFalse(payload["ok"])
        self.assertIn("股票代码格式错误", payload["error"])

    def test_disabled_machine_learning_score_is_not_parsed_from_sample_warning(self):
        report = """
量化研究决策报告 - 600519 (贵州茅台)
============================================================
综合评分: 45.0/100
交易建议: 观望

评分拆解
- 技术指标分: 43.0/100
- 机器学习分: 未启用，可训练样本不足，建议至少 180 个交易日。
- 风险韧性分: 51.1/100
""".strip()

        payload = web_app.parse_report_summary(report)

        self.assertIsNone(payload["scores"]["machine_learning"])

    def test_parse_technical_metrics_converts_nan_to_none(self):
        report = """
技术指标
- MA5=nan, MA10=1290.38, MA20=1310.12, MA60=1388.07
- RSI(14)=nan, KDJ-J=28.86, MACD柱=-0.7296
- 20日年化波动率=nan%, ATR(14)/收盘价=2.21%

风控
- 近120日最大回撤: 18.46% OK
""".strip()

        metrics = web_app.parse_technical_metrics(report)

        self.assertIsNone(metrics["ma_5"])
        self.assertIsNone(metrics["rsi_14"])
        self.assertIsNone(metrics["volatility_20_pct"])
        self.assertEqual(metrics["ma_10"], 1290.38)
        self.assertEqual(metrics["macd_hist"], -0.7296)
        self.assertEqual(metrics["atr_pct_14"], 2.21)
        self.assertEqual(metrics["max_drawdown_pct"], 18.46)

    def test_env_int_reads_cloud_platform_port(self):
        with patch.dict(os.environ, {"PORT": "10000"}):
            self.assertEqual(web_app.env_int("PORT", 8765), 10000)

    def test_env_int_falls_back_for_invalid_port(self):
        with patch.dict(os.environ, {"PORT": "not-a-port"}):
            self.assertEqual(web_app.env_int("PORT", 8765), 8765)

    def test_data_source_catalog_exposes_premium_source_status(self):
        with patch.dict(os.environ, {}, clear=True):
            catalog = web_app.data_source_catalog()

        sources = {source["id"]: source for source in catalog["sources"]}
        self.assertIn("供应商推送优先", catalog["policy"])
        self.assertTrue(sources["premium"]["enabled"])
        self.assertFalse(sources["push"]["enabled"])
        self.assertFalse(sources["tushare"]["enabled"])
        self.assertTrue(sources["tencent"]["enabled"])

    def test_data_source_catalog_marks_tushare_enabled_when_token_exists(self):
        with patch.dict(os.environ, {"TUSHARE_TOKEN": "test-token", "DATA_WEBHOOK_SECRET": "push-secret"}):
            catalog = web_app.data_source_catalog()

        sources = {source["id"]: source for source in catalog["sources"]}
        self.assertTrue(sources["push"]["enabled"])
        self.assertTrue(sources["tushare"]["enabled"])

    def test_split_symbols_accepts_commas_and_spaces(self):
        self.assertEqual(web_app.split_symbols("600519， 000001 300750"), ["600519", "000001", "300750"])

    def test_expected_secret_prefers_refresh_secret_for_refresh_endpoint(self):
        with patch.dict(os.environ, {"DATA_WEBHOOK_SECRET": "push-secret", "REFRESH_SECRET": "refresh-secret"}):
            self.assertEqual(web_app.expected_secret_for("/api/webhooks/market-data"), "push-secret")
            self.assertEqual(web_app.expected_secret_for("/api/refresh"), "refresh-secret")


if __name__ == "__main__":
    unittest.main()
