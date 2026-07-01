from __future__ import annotations

from typing import Any, Protocol, Sequence

from .models import MarketStock, NewsItem


class NewsSource(Protocol):
    """新闻/热搜源 seam。调用方穿过此接口取新闻，测试可注入内存替身。"""

    def collect(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """返回 (news_items, source_statuses)。news_item: {source,title,summary,published_at}。"""
        ...


class MarketSource(Protocol):
    """行情源 seam。调用方穿过此接口取行情快照，测试可注入内存替身。"""

    def fetch_rows(self) -> list[dict[str, Any]]:
        """返回原始行情行列表（clist diff 格式）。"""
        ...

    def build_snapshot(self, rows: list[dict[str, Any]], hot_terms: list[str]) -> tuple[list[MarketStock], dict[str, Any]]:
        """根据热点词筛选并构造 MarketStock 快照 + meta。"""
        ...

    def fetch_market_total_amount(self) -> float:
        """两市成交额（元）。"""
        ...


class LLMAnalyzer(Protocol):
    """LLM 分析 seam。DeepSeek/豆包等实现此接口。"""

    def analyze_news(self, news_items: list[dict[str, Any]]) -> dict[str, Any]:
        """返回 {hot_themes, mentioned_stocks, summary}。"""
        ...

    def check(self) -> tuple[bool, str]:
        """健康检查。"""
        ...
