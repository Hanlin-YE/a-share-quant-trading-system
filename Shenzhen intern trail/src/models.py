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
    # V1.0 扩展字段
    amount: float = 0.0  # 个股成交额（元）
    active_buy_ratio: float = 0.0  # 大单主动买盘占比（0-1），用 f184/100 近似
    main_force_net_5d: float = 0.0  # 近5日主力净流入累计
    main_force_net_10d: float = 0.0  # 近10日主力净流入累计
    main_force_net_20d: float = 0.0  # 近20日主力净流入累计
    dif_value: float = 0.0  # MACD DIF 值（背离判断）
    dif_prev_peak: float = 0.0  # 上一轮 DIF 峰值（顶背离比较）
    is_consolidating: bool = False  # 是否处于盘整
    business_ratio: float = 0.0  # 主营业务占比（0-1），>0.15 达标；暂用行业命中近似
    is_bottom_divergence: bool = False  # DIF 底背离（买点信号）


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
    slot: int = 0  # 建议仓位槽位 1-4


@dataclass
class PoolEntry:
    """三层股池条目。layer: hot / screened / trade。"""
    code: str
    name: str
    layer: str
    entered_at: str  # ISO 日期，进入该层时间
    last_seen_at: str  # 最近一次扫描仍存在的时间
    days_in_pool: int = 0
    themes: List[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Position:
    """持仓记录（分4仓滚动）。"""
    code: str
    name: str
    slot: int  # 1-4
    shares: int
    cost: float
    entry_date: str
    leader_code: str  # 同板块龙一代码，用于“龙一躺则全躺”止损
    stop_loss: float  # 止损价
    trend_line: float  # 趋势线（破则卖）


@dataclass(frozen=True)
class SellSignal:
    code: str
    name: str
    slot: int
    reason: str
    suggested_price: float
    urgency: str  # immediate / normal
