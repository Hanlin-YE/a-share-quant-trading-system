from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class NewsItem:
    source: str
    title: str
    summary: str = ""
    published_at: str = ""


@dataclass(frozen=True)
class MarketStock:
    code: str
    name: str
    themes: List[str]
    pct_change: float
    close: float
    volume: float
    volume_ma4: float
    volume_ma11: float
    volume_ma117: float
    large_order_ratio: float
    main_force_net: float
    turnover: float
    close_ma5: float = 0.0
    close_ma10: float = 0.0
    close_ma20: float = 0.0
    consecutive_down_days: int = 0
    risk_flags: List[str] = field(default_factory=list)
    breakout_a: bool = False
    breakout_b: bool = False
    is_limit_up: bool = False
    is_fast_sealed: bool = False
    leader_rank: int = 0
@dataclass(frozen=True)
class HotCandidate:
    stock: MarketStock
    hot_score: float
    matched_terms: List[str]
    news_reasons: List[str]


@dataclass(frozen=True)
class LayerDecision:
    passed: bool
    reason: str
    metrics: Dict[str, float | str | bool]


@dataclass(frozen=True)
class ScreenedStock:
    stock: MarketStock
    hot_score: float
    matched_terms: List[str]
    news_reasons: List[str]
    layer1: LayerDecision
    layer2: LayerDecision
    layer3: LayerDecision
    layer4: Optional[LayerDecision] = None


@dataclass(frozen=True)
class BuyPlan:
    code: str
    name: str
    trigger: str
    limit_price: float
    pct_change_at_plan: float
    leader_rank: int
    fallback_from: str
    reason: str
    risk_note: str
