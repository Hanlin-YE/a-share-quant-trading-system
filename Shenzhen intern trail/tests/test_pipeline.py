from __future__ import annotations

import unittest

from src.models import MarketStock, NewsItem
from src.pipeline import run_pipeline

MARKET_TOTAL = 1.5e12  # 两市成交额 1.5 万亿
AMOUNT_OK = 5e8  # 个股成交额 5 亿 > 两市 1/7500(2亿)


def _stock(**overrides) -> MarketStock:
    base = dict(
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
        active_buy_ratio=0.20,
        main_force_net=1000000.0,
        main_force_net_5d=1000000.0,
        main_force_net_10d=1000000.0,
        main_force_net_20d=1000000.0,
        turnover=4.0,
        amount=AMOUNT_OK,
        business_ratio=0.5,
        breakout_a=True,
        leader_rank=2,
    )
    base.update(overrides)
    return MarketStock(**base)


def _anchor(**overrides) -> MarketStock:
    defaults = dict(code="300999", name="机器人龙一", pct_change=10.0, close=50.0, is_limit_up=True, is_fast_sealed=True, leader_rank=1, breakout_a=False)
    defaults.update(overrides)
    return _stock(**defaults)


class PipelineTests(unittest.TestCase):
    def test_four_layer_pipeline_emits_breakout_plan(self) -> None:
        news = [NewsItem(source="official_media", title="机器人产业链活跃", summary="机器人方向走强")]
        stocks = [_stock(), _anchor()]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(len(result["buy_plans"]), 1)
        self.assertEqual(result["buy_plans"][0]["trigger"], "A_BREAKOUT")
        self.assertEqual(result["buy_plans"][0]["leader_rank"], 2)

    def test_risk_flag_blocks_candidate(self) -> None:
        news = [NewsItem(source="wind", title="机器人产业链活跃", summary="机器人个股走强")]
        stocks = [_stock(code="002000", name="风险样例", risk_flags=["st"], breakout_b=True), _anchor()]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"], [])
        self.assertFalse(result["layer_results"][0]["layer2"]["passed"])

    def test_board_chase_plan_requires_above_7_5_percent(self) -> None:
        news = [NewsItem(source="jin10", title="液冷服务器热度升温", summary="液冷方向活跃")]
        stocks = [
            _stock(code="300999", name="液冷样例", themes=["液冷"], pct_change=7.6, breakout_a=False, breakout_b=False),
            _anchor(code="300998", name="液冷涨停锚", themes=["液冷"]),
        ]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"][0]["trigger"], "BOARD_CHASE_7_5")

    def test_no_follow_buy_without_same_theme_limit_up_peer(self) -> None:
        news = [NewsItem(source="official_media", title="AI算力政策推进", summary="光模块活跃")]
        stocks = [_stock(code="300308", name="中际旭创", themes=["AI算力", "光模块"], breakout_a=True)]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"], [])
        self.assertIn("同板块未出现涨停锚点", result["layer_results"][0]["layer4"]["reason"])

    def test_fast_sealed_rank2_falls_back_to_rank3(self) -> None:
        news = [NewsItem(source="jin10", title="机器人产业链活跃", summary="机器人方向走强")]
        stocks = [
            _anchor(code="300111", name="机器人龙一"),
            _stock(code="300222", name="机器人龙二", pct_change=10.0, is_limit_up=True, is_fast_sealed=True, leader_rank=2, breakout_a=False, breakout_b=False),
            _stock(code="300333", name="机器人龙三", pct_change=7.6, leader_rank=3, breakout_a=False, breakout_b=False),
        ]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"][0]["code"], "300333")
        self.assertEqual(result["buy_plans"][0]["leader_rank"], 3)
        self.assertEqual(result["buy_plans"][0]["fallback_from"], "300222 机器人龙二")

    def test_consecutive_down_and_bearish_price_ma_rejected(self) -> None:
        news = [NewsItem(source="official_media", title="AI算力政策推进", summary="光模块活跃")]
        stocks = [
            _stock(code="300308", name="中际旭创", themes=["AI算力", "光模块"], pct_change=-5.0, close=150.0, close_ma5=148.0, close_ma10=155.0, close_ma20=160.0, consecutive_down_days=4, breakout_a=True),
            _anchor(code="300999", name="算力龙头", themes=["AI算力"]),
        ]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"], [])
        self.assertFalse(result["layer_results"][0]["layer3"]["passed"])
        self.assertIn("连续下跌", result["layer_results"][0]["layer3"]["reason"])

    def test_large_order_ratio_above_50_pct_rejected(self) -> None:
        news = [NewsItem(source="official_media", title="机器人活跃", summary="机器人走强")]
        stocks = [_stock(active_buy_ratio=0.55), _anchor()]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"], [])
        self.assertIn("大单主动买盘占比", result["layer_results"][0]["layer3"]["reason"])

    def test_business_ratio_below_15_pct_rejected(self) -> None:
        news = [NewsItem(source="official_media", title="机器人活跃", summary="机器人走强")]
        stocks = [_stock(business_ratio=0.10), _anchor()]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"], [])
        self.assertIn("业务占比", result["layer_results"][0]["layer2"]["reason"])

    def test_consolidation_rejected(self) -> None:
        news = [NewsItem(source="official_media", title="机器人活跃", summary="机器人走强")]
        stocks = [_stock(is_consolidating=True), _anchor()]
        result = run_pipeline(news, stocks, market_total_amount=MARKET_TOTAL)
        self.assertEqual(result["buy_plans"], [])
        self.assertIn("盘整", result["layer_results"][0]["layer3"]["reason"])


if __name__ == "__main__":
    unittest.main()
