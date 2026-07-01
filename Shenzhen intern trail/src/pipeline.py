from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .models import BuyPlan, HotCandidate, LayerDecision, MarketStock, NewsItem, ScreenedStock


DEFAULT_THRESHOLDS = {
    "news_hot_score": 1.0,
    # 第二层：主力埋伏 + 业务占比
    "main_force_net_min": 0.0,
    "main_force_5d_min": 0.0,  # 近5日主力净流入累计为正
    "turnover_min": 2.0,
    "business_ratio_min": 0.15,  # 业务占比>15%
    # 第三层：量能 + 大单
    "large_order_ratio_min": 0.17,  # 大单主动买盘占比>17%
    "large_order_ratio_max": 0.50,  # 且<50%
    "volume_to_market_ratio": 1 / 7500,  # 个股成交额>两市1/7500
    "volume_burst_multiple": 1.8,
    # 第四层：买点
    "board_chase_min_pct": 7.5,  # 涨幅超过7.5%买入
    "board_chase_max_pct": 9.9,
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
        amount=parse_float(row.get("amount")),
        active_buy_ratio=parse_float(row.get("active_buy_ratio")) or parse_float(row.get("large_order_ratio")),
        main_force_net_5d=parse_float(row.get("main_force_net_5d")),
        main_force_net_10d=parse_float(row.get("main_force_net_10d")),
        main_force_net_20d=parse_float(row.get("main_force_net_20d")),
        dif_value=parse_float(row.get("dif_value")),
        is_consolidating=parse_bool(row.get("is_consolidating")),
        business_ratio=parse_float(row.get("business_ratio")),
        is_bottom_divergence=parse_bool(row.get("is_bottom_divergence")),
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
    if normalized in {"jin10", "baidu_hot", "google_trends", "toutiao_hot"}:
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
    """第二层：剔除风险 + 多日主力资金埋伏 + 业务占比>15%。"""
    stock = candidate.stock
    hard_risks = sorted(set(stock.risk_flags).intersection(RISK_FLAGS))
    if hard_risks:
        return LayerDecision(False, f"剔除风险标记: {', '.join(hard_risks)}", {"risk_count": len(hard_risks)})

    # 多日主力资金埋伏：近5日主力净流入累计为正，且近20日为正（持续埋伏）
    mf_5d = stock.main_force_net_5d
    mf_20d = stock.main_force_net_20d
    accumulation = mf_5d > thresholds["main_force_5d_min"] and stock.turnover >= thresholds["turnover_min"]
    if not accumulation:
        return LayerDecision(
            False,
            "主力埋伏特征不足（近5日主力净流入非正或换手无效）",
            {"main_force_net_5d": mf_5d, "main_force_net_20d": mf_20d, "turnover": stock.turnover},
        )

    # 业务占比>15%
    if stock.business_ratio < thresholds["business_ratio_min"]:
        return LayerDecision(
            False,
            f"业务占比 {stock.business_ratio:.0%} 未达 15%",
            {"business_ratio": stock.business_ratio},
        )

    return LayerDecision(
        True,
        f"通过：近5日主力净流入 {mf_5d:.0f}，业务占比达标，换手 {stock.turnover:.1f}%",
        {"main_force_net_5d": mf_5d, "main_force_net_20d": mf_20d, "business_ratio": stock.business_ratio, "turnover": stock.turnover},
    )


def layer3_volume_filter(candidate: HotCandidate, thresholds: Dict[str, float], market_total_amount: float, popularity_refs: list[str] | None = None, same_theme_passed_count: int = 0) -> LayerDecision:
    """第三层：大单主动买盘占比 17-50%（必要）+ 成交额>两市1/7500（必要）+ 盘整否决；4/11/117多头为参考；≥2只时参考人气榜。"""
    stock = candidate.stock

    # 盘整否决：不在盘整时买入
    if stock.is_consolidating:
        return LayerDecision(False, "处于盘整，不买入", {"is_consolidating": True})

    # 连续下跌4天否决
    if stock.consecutive_down_days >= 4:
        return LayerDecision(False, f"连续下跌 {stock.consecutive_down_days} 天", {"consecutive_down_days": stock.consecutive_down_days})

    # 必要条件1：大单主动买盘占比 17%-50%
    ratio = stock.active_buy_ratio
    ratio_min = thresholds["large_order_ratio_min"]
    ratio_max = thresholds["large_order_ratio_max"]
    if not (ratio_min <= ratio <= ratio_max):
        return LayerDecision(
            False,
            f"大单主动买盘占比 {ratio:.1%} 不在 [{ratio_min:.0%}, {ratio_max:.0%}]",
            {"active_buy_ratio": ratio},
        )

    # 必要条件2：个股成交额 > 两市成交额 1/7500
    if market_total_amount > 0:
        threshold_amount = market_total_amount * thresholds["volume_to_market_ratio"]
        if stock.amount < threshold_amount:
            return LayerDecision(
                False,
                f"成交额 {stock.amount:.0f} 不足两市1/7500 ({threshold_amount:.0f})",
                {"amount": stock.amount, "market_threshold": threshold_amount},
            )

    # 参考条件：4/11/117 量能多头排列（非必要）
    vol_ma_bullish = stock.volume_ma4 > stock.volume_ma11 > stock.volume_ma117 > 0
    baseline = max(stock.volume_ma11, stock.volume_ma117, 1.0)
    burst_multiple = stock.volume / baseline
    price_ma_bullish = stock.close_ma5 > stock.close_ma10 > stock.close_ma20 > 0

    reason_parts = [f"大单占比 {ratio:.1%} 达标", f"成交额 {stock.amount/1e8:.2f}亿 达两市1/7500"]
    if vol_ma_bullish:
        reason_parts.append("量能4/11/117多头排列（参考）")
    if burst_multiple >= thresholds["volume_burst_multiple"]:
        reason_parts.append(f"爆量 {burst_multiple:.2f}x（参考）")
    if price_ma_bullish:
        reason_parts.append("股价均线多头")
    if same_theme_passed_count >= 2 and popularity_refs:
        reason_parts.append(f"同板块通过≥2只，参考人气榜：{', '.join(popularity_refs[:3])}")
    metrics = {
        "active_buy_ratio": ratio,
        "amount": stock.amount,
        "volume_ma_bullish_4_11_117": vol_ma_bullish,
        "burst_multiple": round(burst_multiple, 3),
        "price_ma_bullish": price_ma_bullish,
        "same_theme_passed_count": same_theme_passed_count,
        "popularity_refs": popularity_refs or [],
    }
    return LayerDecision(True, "通过：" + "，".join(reason_parts), metrics)


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
    """买点：DIF底背离 > A/B突破 > 7.5%打板。文档：涨幅超过7.5%时买入；技术买点为背离和突破。"""
    if stock.is_bottom_divergence:
        return "DIVERGENCE_BUY", "DIF底背离买点", limit_price(stock.close, 0.003)
    if stock.breakout_a:
        return "A_BREAKOUT", "A类突破买点", limit_price(stock.close, 0.003)
    if stock.breakout_b:
        return "B_BREAKOUT", "B类突破买点", limit_price(stock.close, 0.005)
    board_min = thresholds["board_chase_min_pct"]
    board_max = thresholds["board_chase_max_pct"]
    if board_min <= stock.pct_change <= board_max:
        return "BOARD_CHASE_7_5", "涨幅>7.5%打板挂单", limit_price(stock.close, 0.008)
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
    """第四层：同板块龙一封板后，选龙二（或龙三）跟随；涨幅>7.5%或背离/突破买入。"""
    stock = candidate.stock
    peers = matched_limit_up_peers(stock, limit_up_theme_map)
    if not peers:
        return LayerDecision(
            False,
            "同板块未出现涨停锚点（龙一未封板），不跟随买入",
            {"limit_up_peer_count": 0},
        )
    # 龙二快速封板买不到 → 切龙三
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

    # 龙一本身不买（已封板买不到）
    if stock.leader_rank == 1 and stock.is_fast_sealed:
        return LayerDecision(
            False,
            "龙一已封死涨停，买不到，等待龙二/龙三机会",
            {"leader_rank": 1, "is_fast_sealed": True},
        )
    if stock.leader_rank not in (2, 3):
        return LayerDecision(
            False,
            f"梯队 rank={stock.leader_rank} 非龙二/龙三，等待机会",
            {"leader_rank": stock.leader_rank},
        )

    signal = candidate_buy_signal(stock, thresholds)
    if signal:
        trigger, signal_reason, target_limit = signal
        return LayerDecision(
            True,
            f"同板块龙一封板，龙{('二' if stock.leader_rank == 2 else '三')}跟随：{signal_reason}",
            {
                "trigger": trigger,
                "limit_price": target_limit,
                "limit_up_peers": "；".join(peers),
                "leader_rank": stock.leader_rank,
                "fallback_from": "",
                "target_code": stock.code,
                "target_name": stock.name,
                "target_pct_change": stock.pct_change,
            },
        )
    return LayerDecision(
        False,
        f"未出现买点信号（涨幅未达7.5%且无背离/突破），当前涨幅 {stock.pct_change:.2f}%",
        {"pct_change": stock.pct_change},
    )


def limit_price(close: float, premium: float) -> float:
    if not math.isfinite(close) or close <= 0:
        return 0.0
    return round(close * (1 + premium), 2)


def run_pipeline(
    news_items: Sequence[NewsItem],
    stocks: Sequence[MarketStock],
    thresholds: Dict[str, float] | None = None,
    market_total_amount: float = 0.0,
) -> Dict:
    active_thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    hot_pool = analyze_news(news_items, stocks, active_thresholds)
    limit_up_theme_map = build_limit_up_theme_map(stocks)
    screened: List[ScreenedStock] = []
    buy_plans: List[BuyPlan] = []
    slot = 0

    # 阶段1：全跑 layer2，统计同板块通过数 + 人气参考（涨幅前3）
    theme_passed: dict[str, list[HotCandidate]] = defaultdict(list)
    l2_results: dict[str, LayerDecision] = {}
    for candidate in hot_pool:
        layer2 = layer2_technical_filter(candidate, active_thresholds)
        l2_results[candidate.stock.code] = layer2
        if layer2.passed:
            for theme in candidate.stock.themes:
                theme_passed[theme].append(candidate)

    def popularity_refs_for(stock: MarketStock) -> tuple[list[str], int]:
        refs: list[str] = []
        passed_count = 0
        for theme in stock.themes:
            peers = theme_passed.get(theme, [])
            passed_count = max(passed_count, len(peers))
            for p in sorted(peers, key=lambda c: c.stock.pct_change, reverse=True)[:3]:
                label = f"{p.stock.code}:{p.stock.name}({p.stock.pct_change:.1f}%)"
                if label not in refs:
                    refs.append(label)
        return refs[:5], passed_count

    # 阶段2：layer3（带人气参考）+ layer4
    for candidate in hot_pool:
        layer1 = LayerDecision(
            True,
            "通过：新闻/热搜命中股名、代码或题材",
            {"hot_score": candidate.hot_score, "matched_terms": "|".join(candidate.matched_terms)},
        )
        layer2 = l2_results[candidate.stock.code]
        layer3 = LayerDecision(False, "未进入第三层", {})
        layer4 = LayerDecision(False, "未进入第四层", {})
        if layer2.passed:
            pop_refs, passed_count = popularity_refs_for(candidate.stock)
            layer3 = layer3_volume_filter(candidate, active_thresholds, market_total_amount, pop_refs, passed_count)
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
            slot = (slot % 4) + 1  # 分4仓滚动
            buy_plans.append(build_buy_plan(screened_stock, slot))

    return {
        "system": "Shenzhen intern trail",
        "isolation_note": "independent prototype; no legacy ledger read/write",
        "thresholds": active_thresholds,
        "market_total_amount": market_total_amount,
        "limit_up_theme_map": limit_up_theme_map,
        "hot_pool": [hot_candidate_to_dict(candidate) for candidate in hot_pool],
        "layer_results": [screened_stock_to_dict(item) for item in screened],
        "buy_plans": [asdict(plan) for plan in buy_plans],
    }


def build_buy_plan(item: ScreenedStock, slot: int = 0) -> BuyPlan:
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
        risk_note="研究计划，不自动下单；需复核涨跌停、T+1、盘口撤单和当日公告风险；分4仓滚动，严格止盈止损。",
        slot=slot,
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
