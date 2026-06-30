import importlib.util
import pathlib
import sys
import unittest

import pandas as pd


MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "theme_scan.py"
SPEC = importlib.util.spec_from_file_location("theme_scan", MODULE_PATH)
theme_scan = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = theme_scan
SPEC.loader.exec_module(theme_scan)


class ThemeScanTest(unittest.TestCase):
    def test_scan_recommends_only_non_limit_table_stocks(self):
        frame = pd.DataFrame(
            [
                ["600001", "中国航天A", "商业航天", "商业航天订单催化", 10.01, 10.5, "1.2亿", 8.0, 2.2, 90, "200亿", 1.2],
                ["002149", "西部材料", "商业航天", "航空航天材料受益", 8.2, 33.8, "6500万", 9.0, 2.5, 88, "150亿", 0.8],
                ["300123", "弹性科技", "商业航天", "卫星互联网共振", 12.5, 22.1, "5000万", 12.0, 2.8, 88, "80亿", 0.7],
                ["600002", "中国低空A", "低空经济", "低空经济政策催化", 9.8, 18.0, "9000万", 7.0, 2.1, 80, "120亿", 0.9],
                ["600003", "中国低空B", "低空经济", "无人机订单驱动", 6.4, 16.5, "5200万", 8.0, 2.0, 80, "110亿", 0.7],
                ["600004", "中国算力A", "算力", "算力租赁订单", 10.0, 12.0, "8000万", 6.0, 2.0, 70, "100亿", 0.6],
                ["600005", "中国算力B", "算力", "AI服务器需求", 7.1, 15.0, "4100万", 7.0, 1.9, 70, "100亿", 0.5],
                ["600006", "弱票", "商业航天", "跟风上涨", 7.0, 8.0, "-100万", 7.0, 2.0, 88, "20亿", 0.4],
            ],
            columns=[
                "股票代码",
                "股票名称",
                "概念名称",
                "涨停分析",
                "今日涨幅",
                "当前价格",
                "资金净额",
                "换手率",
                "量比",
                "概念强度值",
                "流通市值",
                "封单强度",
            ],
        )

        result = theme_scan.scan_theme_table(frame, analysis_date="2026-05-31", capital=100000)

        self.assertEqual(result["analysis_date"], "2026-05-31")
        self.assertEqual(len(result["theme_analyses"]), 3)
        codes = {item["股票代码"] for item in result["alpha_picks"]}
        self.assertIn("002149", codes)
        self.assertNotIn("600001", codes)
        self.assertNotIn("600006", codes)
        self.assertLessEqual(len(result["alpha_picks"]), 3)
        self.assertIn("position_plan", result)
        self.assertGreater(result["position_plan"][0]["目标仓位%"], 0)
        self.assertEqual(result["position_plan"][0]["目标仓位区间%"], "3.0-8.0")
        self.assertGreater(result["position_plan"][0]["目标金额"], 0)
        self.assertIsNone(result["position_plan"][0]["止损距离%"])
        self.assertIsNone(result["position_plan"][0]["组合最大亏损%"])
        self.assertEqual(result["position_plan"][0]["仓位profile"], "llmquant-long-biased")
        self.assertEqual(result["portfolio_controls"]["strategy_profile"], "llmquant-long-biased")
        self.assertIn("LLMQuant", result["portfolio_controls"]["profile_source"])
        self.assertEqual(result["portfolio_controls"]["capital"], 100000)

    def test_local_a_share_theme_profile_keeps_risk_budget_math_explicit(self):
        frame = pd.DataFrame(
            [
                ["600001", "中国航天A", "商业航天", "商业航天订单催化", 10.01, 10.5, "1.2亿", 8.0, 2.2, 90, "200亿", 1.2],
                ["002149", "西部材料", "商业航天", "航空航天材料受益", 8.2, 33.8, "6500万", 9.0, 2.5, 88, "150亿", 0.8],
            ],
            columns=[
                "股票代码",
                "股票名称",
                "概念名称",
                "涨停分析",
                "今日涨幅",
                "当前价格",
                "资金净额",
                "换手率",
                "量比",
                "概念强度值",
                "流通市值",
                "封单强度",
            ],
        )

        result = theme_scan.scan_theme_table(frame, capital=100000, strategy_profile="local-a-share-theme")

        self.assertEqual(result["position_plan"][0]["仓位profile"], "local-a-share-theme")
        self.assertLessEqual(result["position_plan"][0]["组合最大亏损%"], 0.5)
        self.assertEqual(result["portfolio_controls"]["per_trade_risk_budget_pct"], 0.5)
        self.assertIn("not copied from LLMQuant", result["portfolio_controls"]["profile_source"])

    def test_quant_paper_profile_allocates_zero_before_validation(self):
        frame = pd.DataFrame(
            [
                ["600001", "中国航天A", "商业航天", "商业航天订单催化", 10.01, 10.5, "1.2亿", 8.0, 2.2, 90, "200亿", 1.2],
                ["002149", "西部材料", "商业航天", "航空航天材料受益", 8.2, 33.8, "6500万", 9.0, 2.5, 88, "150亿", 0.8],
            ],
            columns=[
                "股票代码",
                "股票名称",
                "概念名称",
                "涨停分析",
                "今日涨幅",
                "当前价格",
                "资金净额",
                "换手率",
                "量比",
                "概念强度值",
                "流通市值",
                "封单强度",
            ],
        )

        result = theme_scan.scan_theme_table(frame, capital=100000, strategy_profile="quant-paper")

        self.assertEqual(result["position_plan"][0]["仓位profile"], "quant-paper")
        self.assertEqual(result["position_plan"][0]["动作"], "仅观察")
        self.assertEqual(result["position_plan"][0]["目标仓位%"], 0.0)
        self.assertIn("paper trading for 3-6 months", result["portfolio_controls"]["source_rules"][1])

    def test_serenity_chokepoint_profile_is_observation_only_research_gate(self):
        frame = pd.DataFrame(
            [
                ["600001", "中国航天A", "商业航天", "商业航天订单催化", 10.01, 10.5, "1.2亿", 8.0, 2.2, 90, "200亿", 1.2],
                ["002149", "西部材料", "商业航天", "航空航天材料受益", 8.2, 33.8, "6500万", 9.0, 2.5, 88, "150亿", 0.8],
            ],
            columns=[
                "股票代码",
                "股票名称",
                "概念名称",
                "涨停分析",
                "今日涨幅",
                "当前价格",
                "资金净额",
                "换手率",
                "量比",
                "概念强度值",
                "流通市值",
                "封单强度",
            ],
        )

        result = theme_scan.scan_theme_table(frame, capital=100000, strategy_profile="serenity-chokepoint")

        self.assertEqual(result["position_plan"][0]["仓位profile"], "serenity-chokepoint")
        self.assertEqual(result["position_plan"][0]["动作"], "仅观察")
        self.assertEqual(result["position_plan"][0]["目标仓位%"], 0.0)
        self.assertIn("supply chain", result["portfolio_controls"]["source_rules"][0])
        self.assertIn("结构性胜率", result["position_plan"][0]["仓位理由"])

    def test_volume_ratio_is_optional_when_column_missing(self):
        frame = pd.DataFrame(
            [
                ["600010", "中国主题龙", "机器人", "机器人产业政策", 10.0, "1亿", 7.0, 60, "150亿"],
                ["600011", "中国主题伴侣", "机器人", "机器人产业链受益", 6.2, "5000万", 8.0, 60, "120亿"],
            ],
            columns=["股票代码", "股票名称", "概念名称", "涨停分析", "涨幅", "资金净额", "换手率", "概念强度值", "流通市值"],
        )

        result = theme_scan.scan_theme_table(frame)

        self.assertEqual(result["alpha_picks"][0]["股票代码"], "600011")

    def test_high_risk_theme_generates_observe_only_position(self):
        rows = []
        for i in range(11):
            rows.append([f"6001{i:02d}", f"中国高热{i}", "高热题材", "题材集体高潮", 10.0, "5000万", 6.0, 90, "120亿"])
        rows.append(["600222", "中国候选", "高热题材", "题材补涨", 6.5, "6000万", 8.0, 90, "120亿"])
        frame = pd.DataFrame(
            rows,
            columns=["股票代码", "股票名称", "概念名称", "涨停分析", "涨幅", "资金净额", "换手率", "概念强度值", "流通市值"],
        )

        result = theme_scan.scan_theme_table(frame, capital=100000)

        self.assertEqual(result["theme_analyses"][0]["risk_level"], "高")
        self.assertEqual(result["position_plan"][0]["动作"], "仅观察")
        self.assertEqual(result["position_plan"][0]["目标仓位%"], 0.0)

    def test_missing_required_columns_raise_clear_error(self):
        frame = pd.DataFrame([["600001", "测试"]], columns=["股票代码", "股票名称"])

        with self.assertRaisesRegex(ValueError, "CSV缺少必要字段"):
            theme_scan.scan_theme_table(frame)


if __name__ == "__main__":
    unittest.main()
