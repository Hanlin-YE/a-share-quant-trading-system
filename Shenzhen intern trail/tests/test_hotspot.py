from __future__ import annotations

import unittest

from src.adapters.eastmoney import is_limit_up
from src.hotspot import extract_hotspots, extract_news_keywords, extract_limit_up_themes, cross_validate_hotspots


def _row(code, name, pct, themes_str):
    return {"f12": code, "f14": name, "f3": pct, "f100": "", "f103": themes_str}


class HotspotEngineTests(unittest.TestCase):
    def test_news_keyword_extraction(self):
        news = [
            {"title": "机器人产业链活跃 汇川技术涨停", "summary": "人形机器人方向走强"},
            {"title": "光伏板块拉升 多股涨停", "summary": "光伏储能概念火热"},
            {"title": "机器人概念持续发酵", "summary": ""},
        ]
        kws = extract_news_keywords(news, top_n=10)
        kw_names = [k[0] for k in kws]
        self.assertIn("机器人", kw_names)
        self.assertIn("光伏", kw_names)
        self.assertGreater(kws[0][1], 1)  # 机器人命中3次

    def test_limit_up_theme_clustering(self):
        rows = [
            _row("300999", "机器人龙一", 20.0, "机器人概念,人形机器人"),  # 创业板20%涨停
            _row("300998", "机器人龙二", 20.0, "机器人概念"),  # 创业板20%涨停
            _row("600001", "光伏锚", 10.0, "光伏概念"),  # 沪市10%涨停
            _row("600002", "跌的", -3.0, "光伏概念"),  # 非涨停不计入
        ]
        themes = extract_limit_up_themes(rows, is_limit_up)
        theme_names = [t[0] for t in themes]
        self.assertIn("机器人概念", theme_names)
        self.assertIn("光伏概念", theme_names)
        robot = [t for t in themes if t[0] == "机器人概念"][0]
        self.assertEqual(robot[1], 2)  # 2只涨停
        pv = [t for t in themes if t[0] == "光伏概念"][0]
        self.assertEqual(pv[1], 1)

    def test_cross_validation_strong_vs_fund_only(self):
        news_kw = [("机器人", 3, ["t1"]), ("光伏", 1, ["t2"])]
        limit_up = [("机器人概念", 5, ["300999", "300998"]), ("光伏概念", 3, ["600001"])]
        hotspots = cross_validate_hotspots(news_kw, limit_up, news_threshold=2, limit_up_threshold=3)
        types = {h["term"]: h["type"] for h in hotspots}
        # 机器人：新闻3次 + 涨停5次 = strong
        self.assertEqual(types.get("机器人"), "strong")
        # 光伏：新闻1次(<2) + 涨停3次 = fund_only
        self.assertEqual(types.get("光伏"), "fund_only")

    def test_extract_hotspots_returns_terms_and_details(self):
        news = [
            {"title": "机器人产业链活跃", "summary": "人形机器人走强"},
            {"title": "机器人概念持续", "summary": ""},
            {"title": "机器人板块大涨", "summary": ""},
        ]
        rows = [
            _row("300999", "机器人龙一", 20.0, "机器人概念"),
            _row("300998", "机器人龙二", 20.0, "机器人概念"),
            _row("300997", "机器人龙三", 20.0, "机器人概念"),
            _row("600001", "光伏锚", 10.0, "光伏概念"),
        ]
        terms, details = extract_hotspots(news, rows, is_limit_up, top_n=10)
        self.assertIn("机器人", terms)
        self.assertTrue(any(d["term"] == "机器人" and d["type"] == "strong" for d in details))

    def test_empty_inputs_return_empty(self):
        terms, details = extract_hotspots([], [], is_limit_up)
        self.assertEqual(terms, [])
        self.assertEqual(details, [])


if __name__ == "__main__":
    unittest.main()
