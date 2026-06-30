from __future__ import annotations

import unittest

from src.models import MarketStock, NewsItem
from src.pipeline import run_pipeline


class PipelineTests(unittest.TestCase):
    def test_four_layer_pipeline_emits_breakout_plan(self) -> None:
        news = [NewsItem(source="official_media", title="机器人产业链活跃", summary="机器人方向走强")]
        stocks = [
            MarketStock(
                code="300124",
                name="汇川技术",
                themes=["机器人"],
                pct_change=6.8,
                close=100.0,
                volume=200.0,
                volume_ma4=160.0,
                volume_ma11=120.0,
                volume_ma117=80.0,
                close_ma5=98.0,
                close_ma10=95.0,
                close_ma20=90.0,
                large_order_ratio=0.18,
                main_force_net=1000000.0,
                turnover=4.0,
                breakout_a=True,
                leader_rank=2,
            ),
            MarketStock(
                code="300999",
                name="机器人龙一",
                themes=["机器人"],
                pct_change=10.0,
                close=50.0,
                volume=300.0,
                volume_ma4=200.0,
                volume_ma11=120.0,
                volume_ma117=90.0,
                close_ma5=48.0,
                close_ma10=45.0,
                close_ma20=40.0,
                large_order_ratio=0.2,
                main_force_net=2000000.0,
                turnover=8.0,
                is_limit_up=True,
                is_fast_sealed=True,
                leader_rank=1,
            )
        ]

        result = run_pipeline(news, stocks)

        self.assertEqual(len(result["buy_plans"]), 1)
        self.assertEqual(result["buy_plans"][0]["trigger"], "A_BREAKOUT")
        self.assertEqual(result["buy_plans"][0]["limit_price"], 100.3)
        self.assertEqual(result["buy_plans"][0]["leader_rank"], 2)

    def test_risk_flag_blocks_candidate(self) -> None:
        news = [NewsItem(source="wind", title="机器人产业链活跃", summary="机器人个股走强")]
        stocks = [
            MarketStock(
                code="002000",
                name="风险样例",
                themes=["机器人"],
                pct_change=7.5,
                close=10.0,
                volume=200.0,
                volume_ma4=160.0,
                volume_ma11=120.0,
                volume_ma117=80.0,
                close_ma5=0.0,
                close_ma10=0.0,
                close_ma20=0.0,
                large_order_ratio=0.18,
                main_force_net=1000000.0,
                turnover=5.0,
                risk_flags=["st"],
                breakout_b=True,
                leader_rank=2,
            ),
            MarketStock(
                code="300111",
                name="机器人涨停锚",
                themes=["机器人"],
                pct_change=10.0,
                close=12.0,
                volume=300.0,
                volume_ma4=200.0,
                volume_ma11=120.0,
                volume_ma117=90.0,
                close_ma5=0.0,
                close_ma10=0.0,
                close_ma20=0.0,
                large_order_ratio=0.2,
                main_force_net=2000000.0,
                turnover=8.0,
                is_limit_up=True,
                is_fast_sealed=True,
                leader_rank=1,
            )
        ]

        result = run_pipeline(news, stocks)

        self.assertEqual(result["buy_plans"], [])
        self.assertFalse(result["layer_results"][0]["layer2"]["passed"])

    def test_board_chase_plan_requires_7_to_8_percent_zone(self) -> None:
        news = [NewsItem(source="jin10", title="液冷服务器热度升温", summary="液冷方向活跃")]
        stocks = [
            MarketStock(
                code="300999",
                name="液冷样例",
                themes=["液冷"],
                pct_change=7.6,
                close=20.0,
                volume=300.0,
                volume_ma4=140.0,
                volume_ma11=100.0,
                volume_ma117=90.0,
                close_ma5=19.0,
                close_ma10=18.0,
                close_ma20=17.0,
                large_order_ratio=0.2,
                main_force_net=500000.0,
                turnover=6.0,
                leader_rank=2,
            ),
            MarketStock(
                code="300998",
                name="液冷涨停锚",
                themes=["液冷"],
                pct_change=10.0,
                close=22.0,
                volume=300.0,
                volume_ma4=180.0,
                volume_ma11=120.0,
                volume_ma117=80.0,
                close_ma5=0.0,
                close_ma10=0.0,
                close_ma20=0.0,
                large_order_ratio=0.2,
                main_force_net=800000.0,
                turnover=8.0,
                is_limit_up=True,
                is_fast_sealed=True,
                leader_rank=1,
            )
        ]

        result = run_pipeline(news, stocks)

        self.assertEqual(result["buy_plans"][0]["trigger"], "BOARD_CHASE_7_8")
        self.assertEqual(result["buy_plans"][0]["limit_price"], 20.16)

    def test_no_follow_buy_without_same_theme_limit_up_peer(self) -> None:
        news = [NewsItem(source="official_media", title="AI算力政策推进", summary="光模块活跃")]
        stocks = [
            MarketStock(
                code="300308",
                name="中际旭创",
                themes=["AI算力", "光模块"],
                pct_change=6.8,
                close=100.0,
                volume=200.0,
                volume_ma4=160.0,
                volume_ma11=120.0,
                volume_ma117=80.0,
                close_ma5=98.0,
                close_ma10=95.0,
                close_ma20=90.0,
                large_order_ratio=0.18,
                main_force_net=1000000.0,
                turnover=4.0,
                breakout_a=True,
                leader_rank=2,
            )
        ]

        result = run_pipeline(news, stocks)

        self.assertEqual(result["buy_plans"], [])
        self.assertIn("同板块未出现涨停个股", result["layer_results"][0]["layer4"]["reason"])

    def test_fast_sealed_rank2_falls_back_to_rank3(self) -> None:
        news = [NewsItem(source="jin10", title="机器人产业链活跃", summary="机器人方向走强")]
        stocks = [
            MarketStock(
                code="300111",
                name="机器人龙一",
                themes=["机器人"],
                pct_change=10.0,
                close=30.0,
                volume=300.0,
                volume_ma4=200.0,
                volume_ma11=120.0,
                volume_ma117=90.0,
                close_ma5=29.0,
                close_ma10=28.0,
                close_ma20=27.0,
                large_order_ratio=0.2,
                main_force_net=2000000.0,
                turnover=8.0,
                is_limit_up=True,
                is_fast_sealed=True,
                leader_rank=1,
            ),
            MarketStock(
                code="300222",
                name="机器人龙二",
                themes=["机器人"],
                pct_change=10.0,
                close=40.0,
                volume=300.0,
                volume_ma4=200.0,
                volume_ma11=120.0,
                volume_ma117=90.0,
                close_ma5=39.0,
                close_ma10=38.0,
                close_ma20=37.0,
                large_order_ratio=0.2,
                main_force_net=2000000.0,
                turnover=8.0,
                is_limit_up=True,
                is_fast_sealed=True,
                leader_rank=2,
            ),
            MarketStock(
                code="300333",
                name="机器人龙三",
                themes=["机器人"],
                pct_change=7.3,
                close=20.0,
                volume=260.0,
                volume_ma4=160.0,
                volume_ma11=110.0,
                volume_ma117=80.0,
                close_ma5=19.5,
                close_ma10=19.0,
                close_ma20=18.5,
                large_order_ratio=0.18,
                main_force_net=900000.0,
                turnover=6.0,
                leader_rank=3,
            ),
        ]

        result = run_pipeline(news, stocks)

        self.assertEqual(result["buy_plans"][0]["code"], "300333")
        self.assertEqual(result["buy_plans"][0]["leader_rank"], 3)
        self.assertEqual(result["buy_plans"][0]["fallback_from"], "300222 机器人龙二")
        self.assertEqual(result["buy_plans"][0]["trigger"], "BOARD_CHASE_7_8")

    def test_consecutive_down_and_bearish_price_ma_rejected(self) -> None:
        news = [NewsItem(source="official_media", title="AI算力政策推进", summary="光模块活跃")]
        stocks = [
            MarketStock(
                code="300308",
                name="中际旭创",
                themes=["AI算力", "光模块"],
                pct_change=-5.0,
                close=150.0,
                volume=200.0,
                volume_ma4=160.0,
                volume_ma11=120.0,
                volume_ma117=80.0,
                close_ma5=148.0,
                close_ma10=155.0,
                close_ma20=160.0,
                consecutive_down_days=4,
                large_order_ratio=0.18,
                main_force_net=1000000.0,
                turnover=4.0,
                breakout_a=True,
                leader_rank=2,
            ),
            MarketStock(
                code="300999",
                name="算力龙头",
                themes=["AI算力"],
                pct_change=10.0,
                close=50.0,
                volume=300.0,
                volume_ma4=200.0,
                volume_ma11=120.0,
                volume_ma117=90.0,
                close_ma5=48.0,
                close_ma10=45.0,
                close_ma20=40.0,
                large_order_ratio=0.2,
                main_force_net=2000000.0,
                turnover=8.0,
                is_limit_up=True,
                is_fast_sealed=True,
                leader_rank=1,
            )
        ]

        result = run_pipeline(news, stocks)

        self.assertEqual(result["buy_plans"], [])
        self.assertFalse(result["layer_results"][0]["layer3"]["passed"])
        self.assertIn("连续下跌", result["layer_results"][0]["layer3"]["reason"])


if __name__ == "__main__":
    unittest.main()
