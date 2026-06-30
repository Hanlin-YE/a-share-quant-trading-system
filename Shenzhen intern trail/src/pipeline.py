from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .models import BuyPlan, HotCandidate, LayerDecision, MarketStock, NewsItem, ScreenedStock


DEFAULT_THRESHOLDS = {
    "news_hot_score": 1.0,
    "main_force_net_min": 0.0,
    "large_order_ratio_min": 0.12,
    "volume_burst_multiple": 1.8,
    "board_chase_min_pct": 7.0,
    "board_chase_max_pct": 8.0,
}

RISK_FLAGS = {
    "st",
    "*st",
    "suspension",
    "major_litigation",
    "earnings_warning",
    "regulatory_probe",
    "pledge_risk",
    "delisting_risk",
}


def load_news(path: Path) -> List[NewsItem]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("news JSON must be a list")
    return [
        NewsItem(
            source=str(item.get("source", "")),
            title=str(item.get("title", "")),
            summary=str(item.get("summary", "")),
            published_at=str(item.get("published_at", "")),
        )
        for item in payload
    ]


def load_market_snapshot(path: Path) -> List[MarketStock]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [market_stock_from_row(row) for row in rows]


def market_stock_from_row(row: Dict[str, str]) -> MarketStock:
    return MarketStock(
        code=str(row.get("code", "")).zfill(6),
        name=str(row.get("name", "")),
        themes=split_list(row.get("themes", "")),
        pct_change=parse_float(row.get("pct_change")),
        close=parse_float(row.get("close")),
        volume=parse_float(row.get("volume")),
        volume_ma4=parse_float(row.get("volume_ma4")),
        volume_ma11=parse_float(row.get("volume_ma11")),
        volume_ma117=parse_float(row.get("volume_ma117")),
        large_order_ratio=parse_float(row.get("large_order_ratio")),
        main_force_net=parse_float(row.get("main_force_net")),
        turnover=parse_float(row.get("turnover")),
        close_ma5=parse_float(row.get("close_ma5")),
        close_ma10=parse_float(row.get("close_ma10")),
        close_ma20=parse_float(row.get("close_ma20")),
        consecutive_down_days=parse_int(row.get("consecutive_down_days")),
        risk_flags=[flag.lower() for flag in split_list(row.get("risk_flags", ""))],
        breakout_a=parse_bool(row.get("breakout_a")),
        breakout_b=parse_bool(row.get("breakout_b")),
        is_limit_up=parse_bool(row.get("is_limit_up")),
        is_fast_sealed=parse_bool(row.get("is_fast_sealed")),
        leader_rank=int(parse_float(row.get("leader_rank"))),
    )


def split_list(value: str | None) -> List[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[|,，;；]", str(value)) if part.strip()]


def parse_float(value: str | None) -> float:
    if value is None or str(value).strip() == "":
        return 0.0
    text = str(value).strip().replace("%", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}

def parse_int(value: str | None, default: int = 0) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(parse_float(value))
    except (ValueError, TypeError):
        return default


def analyze_news(news_items: Sequence[NewsItem], stocks: Sequence[MarketStock], thresholds: Dict[str, float]) -> List[HotCandidate]:
    hot_candidates: List[HotCandidate] = []
    for stock in stocks:
        matched_terms: List[str] = []
        news_reasons: List[str] = []
        score = 0.0
        terms = [stock.name, stock.code, *stock.themes]
        for item in news_items:
            text = f"{item.title} {item.summary}"
            source_weight = source_heat_weight(item.source)
            for term in terms:
                if term and term in text:
                    score += source_weight
                    matched_terms.append(term)
                    news_reasons.append(f"{item.source}: {item.title}")
                    break
        deduped_terms = sorted(set(matched_terms))
        deduped_reasons = dedupe_keep_order(news_reasons)
        if score >= thresholds["news_hot_score"]:
            hot_candidates.append(
                HotCandidate(
                    stock=stock,
                    hot_score=round(score, 3),
                    matched_terms=deduped_terms,
                    news_reasons=deduped_reasons[:5],
                )
            )
    return sorted(hot_candidates, key=lambda candidate: candidate.hot_score, reverse=True)


def source_heat_weight(source: str) -> float:
    normalized = source.lower()
    if normalized in {"wind", "official_media"}:
        return 1.5
    if normalized in {"jin10", "baidu_hot", "google_trends"}:
        return 1.0
    return 0.8


def dedupe_keep_order(values: Iterable[str]) -> List[str]:
    seen = set()
    output = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def layer2_technical_filter(candidate: HotCandidate, thresholds: Dict[str, float]) -> LayerDecision:
    stock = candidate.stock
    hard_risks = sorted(set(stock.risk_flags).intersection(RISK_FLAGS))
    if hard_risks:
        return LayerDecision(False, f"剔除风险标记: {', '.join(hard_risks)}", {"risk_count": len(hard_risks)})
    accumulation = stock.main_force_net > thresholds["main_force_net_min"] and stock.turnover >= 2.0
    if not accumulation:
        return LayerDecision(
            False,
            "主力埋伏特征不足",
            {"main_force_net": stock.main_force_net, "turnover": stock.turnover},
        )
    return LayerDecision(
        True,
        "通过：主力净流入为正且换手有效",
        {"main_force_net": stock.main_force_net, "turnover": stock.turnover},
    )


def layer3_volume_filter(candidate: HotCandidate, thresholds: Dict[str, float]) -> LayerDecision:
    stock = candidate.stock
    baseline = max(stock.volume_ma11, stock.volume_ma117, 1.0)
    burst_multiple = stock.volume / baseline
    vol_ma_bullish = stock.volume_ma4 > stock.volume_ma11 > stock.volume_ma117 > 0
    burst = burst_multiple >= thresholds["volume_burst_multiple"]
    large_order_ok = stock.large_order_ratio >= thresholds["large_order_ratio_min"]
    price_ma_bullish = stock.close_ma5 > stock.close_ma10 > stock.close_ma20 > 0
    ma_bullish = vol_ma_bullish
    rejections = []
    if stock.consecutive_down_days >= 4:
        rejections.append(f"连续下跌 {stock.consecutive_down_days} 天")
    if not price_ma_bullish:
        rejections.append("短期均线不呈多头排列 (MA5>MA10>MA20)")
    if vol_ma_bullish and not price_ma_bullish:
        rejections.append("成交量均线多头但股价均线未跟随")
    if rejections:
        return LayerDecision(
            False,
            "趋势否决：" + "；".join(rejections),
            {"consecutive_down_days": stock.consecutive_down_days, "price_ma_bullish": price_ma_bullish, "volume_ma_bullish": vol_ma_bullish},
        )
    passed = (burst or ma_bullish) and large_order_ok
    reason_parts = []
    if burst:
        reason_parts.append(f"成交量爆量 {burst_multiple:.2f}x")
    if ma_bullish:
        reason_parts.append("量能4/11/117多头排列")
    if price_ma_bullish:
        reason_parts.append("股价均线多头排列 (MA5>MA10>MA20)")
    if large_order_ok:
        reason_parts.append(f"大单占比 {stock.large_order_ratio:.1%}")
    reason = "通过：" + "，".join(reason_parts) if passed else "量能或大单占比不足"
    return LayerDecision(
        passed,
        reason,
        {
            "burst_multiple": round(burst_multiple, 3),
            "volume_ma_bullish_4_11_117": vol_ma_bullish,
            "price_ma_bullish": price_ma_bullish,
            "large_order_ratio": stock.large_order_ratio,
        },
    )


def build_limit_up_theme_map(stocks: Sequence[MarketStock]) -> Dict[str, List[str]]:
    theme_map: Dict[str, List[str]] = {}
    for stock in stocks:
        if not stock.is_limit_up:
            continue
        for theme in stock.themes:
            theme_map.setdefault(theme, []).append(f"{stock.code} {stock.name}")
    return theme_map


def matched_limit_up_peers(stock: MarketStock, limit_up_theme_map: Dict[str, List[str]]) -> List[str]:
    peers: List[str] = []
    for theme in stock.themes:
        for peer in limit_up_theme_map.get(theme, []):
            if not peer.startswith(stock.code):
                peers.append(f"{theme}: {peer}")
    return dedupe_keep_order(peers)


def candidate_buy_signal(stock: MarketStock, thresholds: Dict[str, float]) -> tuple[str, str, float] | None:
    if stock.breakout_a:
        return "A_BREAKOUT", "A类突破买点", limit_price(stock.close, 0.003)
    if stock.breakout_b:
        return "B_BREAKOUT", "B类突破买点", limit_price(stock.close, 0.005)
    board_min = thresholds["board_chase_min_pct"]
    board_max = thresholds["board_chase_max_pct"]
    if board_min <= stock.pct_change <= board_max:
        return "BOARD_CHASE_7_8", "打板儿7-8%挂单设置", limit_price(stock.close, 0.008)
    return None


def same_theme_candidates(stock: MarketStock, candidates: Sequence[HotCandidate]) -> List[HotCandidate]:
    themes = set(stock.themes)
    return [
        candidate
        for candidate in candidates
        if candidate.stock.code != stock.code and themes.intersection(candidate.stock.themes)
    ]


def find_buyable_rank3_fallback(stock: MarketStock, candidates: Sequence[HotCandidate], thresholds: Dict[str, float]) -> tuple[MarketStock, tuple[str, str, float]] | None:
    for candidate in same_theme_candidates(stock, candidates):
        peer = candidate.stock
        if peer.leader_rank != 3 or peer.is_fast_sealed:
            continue
        signal = candidate_buy_signal(peer, thresholds)
        if signal:
            return peer, signal
    return None


def layer4_buy_plan(
    candidate: HotCandidate,
    all_candidates: Sequence[HotCandidate],
    thresholds: Dict[str, float],
    limit_up_theme_map: Dict[str, List[str]],
) -> LayerDecision:
    stock = candidate.stock
    peers = matched_limit_up_peers(stock, limit_up_theme_map)
    if not peers:
        return LayerDecision(
            False,
            "同板块未出现涨停个股，不跟随买入",
            {"limit_up_peer_count": 0},
        )
    if stock.leader_rank == 2 and stock.is_fast_sealed:
        fallback = find_buyable_rank3_fallback(stock, all_candidates, thresholds)
        if fallback:
            fallback_stock, fallback_signal = fallback
            trigger, signal_reason, fallback_limit = fallback_signal
            return LayerDecision(
                True,
                f"龙二快速封板买不到，切换龙三：{signal_reason}",
                {
                    "trigger": trigger,
                    "limit_price": fallback_limit,
                    "limit_up_peers": "；".join(peers),
                    "leader_rank": 3,
                    "fallback_from": f"{stock.code} {stock.name}",
                    "target_code": fallback_stock.code,
                    "target_name": fallback_stock.name,
                    "target_pct_change": fallback_stock.pct_change,
                },
            )
        return LayerDecision(
            False,
            "龙二快速封板买不到，且未找到可买龙三",
            {"leader_rank": stock.leader_rank, "is_fast_sealed": stock.is_fast_sealed},
        )

    if stock.leader_rank != 2:
        return LayerDecision(
            False,
            "买入目标不是龙二，等待龙二或龙三替代机会",
            {"leader_rank": stock.leader_rank},
        )

    signal = candidate_buy_signal(stock, thresholds)
    if signal:
        trigger, signal_reason, target_limit = signal
        return LayerDecision(
            True,
            f"同板块已有涨停个股，龙二跟随：{signal_reason}",
            {
                "trigger": trigger,
                "limit_price": target_limit,
                "limit_up_peers": "；".join(peers),
                "leader_rank": 2,
                "fallback_from": "",
                "target_code": stock.code,
                "target_name": stock.name,
                "target_pct_change": stock.pct_change,
            },
        )
    return LayerDecision(
        False,
        "未出现A/B突破，且涨幅不在7-8%打板儿挂单区间",
        {"pct_change": stock.pct_change},
    )


def limit_price(close: float, premium: float) -> float:
    if not math.isfinite(close) or close <= 0:
        return 0.0
    return round(close * (1 + premium), 2)


def run_pipeline(news_items: Sequence[NewsItem], stocks: Sequence[MarketStock], thresholds: Dict[str, float] | None = None) -> Dict:
    active_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    hot_pool = analyze_news(news_items, stocks, active_thresholds)
    limit_up_theme_map = build_limit_up_theme_map(stocks)
    screened: List[ScreenedStock] = []
    buy_plans: List[BuyPlan] = []

    for candidate in hot_pool:
        layer1 = LayerDecision(
            True,
            "通过：新闻/热搜命中股名、代码或题材",
            {"hot_score": candidate.hot_score, "matched_terms": "|".join(candidate.matched_terms)},
        )
        layer2 = layer2_technical_filter(candidate, active_thresholds)
        layer3 = LayerDecision(False, "未进入第三层", {})
        layer4 = LayerDecision(False, "未进入第四层", {})
        if layer2.passed:
            layer3 = layer3_volume_filter(candidate, active_thresholds)
        if layer3.passed:
            layer4 = layer4_buy_plan(candidate, hot_pool, active_thresholds, limit_up_theme_map)
        screened_stock = ScreenedStock(
            stock=candidate.stock,
            hot_score=candidate.hot_score,
            matched_terms=candidate.matched_terms,
            news_reasons=candidate.news_reasons,
            layer1=layer1,
            layer2=layer2,
            layer3=layer3,
            layer4=layer4,
        )
        screened.append(screened_stock)
        if layer4.passed:
            buy_plans.append(build_buy_plan(screened_stock))

    return {
        "system": "Shenzhen intern trail",
        "isolation_note": "independent prototype; no legacy ledger read/write",
        "thresholds": active_thresholds,
        "limit_up_theme_map": limit_up_theme_map,
        "hot_pool": [hot_candidate_to_dict(candidate) for candidate in hot_pool],
        "layer_results": [screened_stock_to_dict(item) for item in screened],
        "buy_plans": [asdict(plan) for plan in buy_plans],
    }


def build_buy_plan(item: ScreenedStock) -> BuyPlan:
    stock = item.stock
    trigger = str(item.layer4.metrics.get("trigger", "UNKNOWN"))
    limit_value = item.layer4.metrics.get("limit_price", 0.0)
    target_code = str(item.layer4.metrics.get("target_code", stock.code))
    target_name = str(item.layer4.metrics.get("target_name", stock.name))
    target_pct_change = float(item.layer4.metrics.get("target_pct_change", stock.pct_change))
    leader_rank = int(item.layer4.metrics.get("leader_rank", stock.leader_rank))
    fallback_from = str(item.layer4.metrics.get("fallback_from", ""))
    return BuyPlan(
        code=target_code,
        name=target_name,
        trigger=trigger,
        limit_price=float(limit_value),
        pct_change_at_plan=target_pct_change,
        leader_rank=leader_rank,
        fallback_from=fallback_from,
        reason=f"{item.layer4.reason}; 新闻热度 {item.hot_score}; {item.layer3.reason}",
        risk_note="研究计划，不自动下单；需复核涨跌停、T+1、盘口撤单和当日公告风险。",
    )


def hot_candidate_to_dict(candidate: HotCandidate) -> Dict:
    return {
        "code": candidate.stock.code,
        "name": candidate.stock.name,
        "hot_score": candidate.hot_score,
        "matched_terms": candidate.matched_terms,
        "news_reasons": candidate.news_reasons,
    }


def screened_stock_to_dict(item: ScreenedStock) -> Dict:
    return {
        "code": item.stock.code,
        "name": item.stock.name,
        "hot_score": item.hot_score,
        "matched_terms": item.matched_terms,
        "news_reasons": item.news_reasons,
        "layer1": asdict(item.layer1),
        "layer2": asdict(item.layer2),
        "layer3": asdict(item.layer3),
        "layer4": asdict(item.layer4) if item.layer4 else None,
    }
