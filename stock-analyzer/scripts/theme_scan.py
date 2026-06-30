#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A-share theme rotation scanner.

This script internalizes the table-driven watchlist workflow:
1. rank hot themes from limit-up attribution data,
2. restrict picks to stocks already present in the user's table,
3. enforce non-limit-up, positive capital flow, liquidity, and risk filters,
4. emit machine-readable JSON for downstream tools.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


FIELD_ALIASES = {
    "code": ["股票代码", "代码", "证券代码", "stock_code", "code"],
    "name": ["股票名称", "名称", "证券简称", "简称", "stock_name", "name"],
    "theme": ["概念名称", "题材名称", "板块名称", "热门板块", "概念", "题材", "theme", "sector"],
    "limit_reason": ["涨停分析", "涨停原因", "涨停解析", "异动原因", "原因", "limit_reason"],
    "pct_change": ["今日涨幅", "涨幅", "涨跌幅", "change_pct", "pct_change"],
    "price": ["当前价格", "最新价", "收盘价", "价格", "price", "close"],
    "capital_net": ["资金净额", "净流入", "主力净额", "概念净额", "capital_net", "net_inflow"],
    "turnover": ["换手率", "turnover"],
    "volume_ratio": ["量比", "volume_ratio"],
    "theme_strength": ["概念强度值", "概念强度", "题材强度", "strength", "theme_strength"],
    "float_market_cap": ["流通市值", "实际流通", "流通市值亿", "float_market_cap"],
    "seal_strength": ["封单强度", "封单比", "seal_strength"],
}


@dataclass
class ThemeStats:
    name: str
    core_theme: str
    limit_up_count: int
    strength: float
    capital_net: float
    heat_score: float
    risk_level: str
    capital_ecology: str
    liquidity_clash: str
    commander_instruction: str


@dataclass
class Pick:
    theme: str
    code: str
    name: str
    price: Optional[float]
    pct_change: float
    strategy: str
    tier: str
    profit_logic: str
    risk_note: str
    score: float


@dataclass(frozen=True)
class SizingProfile:
    key: str
    label: str
    source: str
    default_max_total_pct: Optional[float]
    default_max_single_pct: float
    default_risk_budget_pct: Optional[float]
    position_floor_pct: float
    position_ceiling_pct: float
    main_stop_loss_pct: Optional[float]
    growth_stop_loss_pct: Optional[float]
    source_rules: Sequence[str]
    note: str


@dataclass
class PositionPlan:
    code: str
    name: str
    action: str
    target_weight_pct: float
    target_weight_band_pct: Optional[str]
    target_amount: Optional[float]
    stop_loss_pct: Optional[float]
    max_loss_pct: Optional[float]
    max_loss_amount: Optional[float]
    source_profile: str
    sizing_reason: str


SIZING_PROFILES: Dict[str, SizingProfile] = {
    "llmquant-long-biased": SizingProfile(
        key="llmquant-long-biased",
        label="LLMQuant long-biased equity book",
        source="LLMQuant/skills llmquant-strategies/workflows/long-biased.md",
        default_max_total_pct=None,
        default_max_single_pct=10.0,
        default_risk_budget_pct=None,
        position_floor_pct=3.0,
        position_ceiling_pct=8.0,
        main_stop_loss_pct=None,
        growth_stop_loss_pct=None,
        source_rules=(
            "target net 70-95% long; target gross 100-130%",
            "15-30 concentrated longs",
            "position sizing 3-8% per position; top 5 positions 30-50% of book",
            "10% single-name limit; 30% single-sector limit; 50% top-5 limit",
            "drawdown triggers: -10% reduce gross/reassess; -15% increase tail hedge; -20% full review",
            "liquidity: every position exitable in <=20 trading days at <20% ADV",
        ),
        note=(
            "GitHub-derived long-biased portfolio constraints. This script only maps table signals "
            "into that 3-8% band; it still requires fundamental, sector, ADV, and thesis checks."
        ),
    ),
    "quant-paper": SizingProfile(
        key="quant-paper",
        label="LLMQuant quant research / paper-trading gate",
        source="LLMQuant/skills llmquant-strategies/workflows/quant.md",
        default_max_total_pct=0.0,
        default_max_single_pct=0.0,
        default_risk_budget_pct=None,
        position_floor_pct=0.0,
        position_ceiling_pct=0.0,
        main_stop_loss_pct=None,
        growth_stop_loss_pct=None,
        source_rules=(
            "train/validation/test split with strict isolation",
            "paper trading for 3-6 months before capital deployment",
            "strategy weights by out-of-sample Sharpe and correlation matrix",
            "gross leverage capped by ex-ante VaR and stress scenarios",
            "kill switch: strategy drawdown > 3x historical worst = pause and review",
        ),
        note="No capital allocation until the rule set has a clean backtest and 3-6 months of paper trading.",
    ),
    "serenity-chokepoint": SizingProfile(
        key="serenity-chokepoint",
        label="Serenity-style chokepoint research gate",
        source="SevenBlues/serenity-chokepoint public framework, adapted as research gates only",
        default_max_total_pct=0.0,
        default_max_single_pct=0.0,
        default_risk_budget_pct=None,
        position_floor_pct=0.0,
        position_ceiling_pct=0.0,
        main_stop_loss_pct=None,
        growth_stop_loss_pct=None,
        source_rules=(
            "map the supply chain and score true bottleneck nodes before treating price action as a signal",
            "require supply concentration, irreplaceability, demand/supply gap, qualification barrier, and under-discovery evidence",
            "separate structural moat score from timing/growth-ramp score",
            "red-team every candidate for substitution risk, customer concentration, dilution, policy/export controls, and cycle timing",
            "use momentum/radar only to surface names; pool inclusion requires deep research validation",
            "A-share deployment remains observation-only until local data, costs, liquidity, and out-of-sample replay are complete",
        ),
        note=(
            "Serenity is best used as a deep-research gate, not as an execution signal. "
            "This profile fuses chokepoint thesis discipline with local A-share theme scanning, but allocates 0% until validated."
        ),
    ),
    "local-a-share-theme": SizingProfile(
        key="local-a-share-theme",
        label="Local A-share intraday theme research template",
        source="local heuristic, not copied from LLMQuant",
        default_max_total_pct=20.0,
        default_max_single_pct=8.0,
        default_risk_budget_pct=0.5,
        position_floor_pct=0.0,
        position_ceiling_pct=8.0,
        main_stop_loss_pct=4.5,
        growth_stop_loss_pct=7.0,
        source_rules=(
            "20% total research exposure cap",
            "8% single-name cap before strategy-specific haircuts",
            "0.5% portfolio risk budget per stopped trade",
            "4.5% main-board and 7.0% ChiNext/STAR stop-distance placeholders",
        ),
        note=(
            "This is a local conservative research template for A-share theme scans. "
            "It is not a sourced LLMQuant rule and should be replaced after backtesting."
        ),
    ),
}


def get_sizing_profile(strategy_profile: str) -> SizingProfile:
    try:
        return SIZING_PROFILES[strategy_profile]
    except KeyError as exc:
        choices = ", ".join(sorted(SIZING_PROFILES))
        raise ValueError(f"未知仓位profile: {strategy_profile}; 可选: {choices}") from exc


def resolve_columns(columns: Iterable[str]) -> Dict[str, str]:
    normalized = {str(column).strip().lower(): str(column) for column in columns}
    resolved: Dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            key = alias.strip().lower()
            if key in normalized:
                resolved[canonical] = normalized[key]
                break
    required = ["code", "name", "theme", "pct_change", "capital_net", "turnover"]
    missing = [field for field in required if field not in resolved]
    if missing:
        raise ValueError(f"CSV缺少必要字段: {', '.join(missing)}")
    return resolved


def parse_number(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "N/A", "nan", "None"}:
        return None
    multiplier = 1.0
    if "亿" in text:
        multiplier = 100_000_000.0
    elif "万" in text:
        multiplier = 10_000.0
    text = text.replace(",", "").replace("%", "").replace("+", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def clean_code(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    match = re.search(r"(\d{6})", text)
    if match:
        return match.group(1)
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def is_chinext_or_star(code: str) -> bool:
    return code.startswith(("300", "301", "688"))


def is_limit_up(code: str, pct_change: Optional[float]) -> bool:
    if pct_change is None:
        return False
    threshold = 19.5 if is_chinext_or_star(code) else 9.5
    return pct_change >= threshold


def pct_range_ok(code: str, pct_change: Optional[float]) -> bool:
    if pct_change is None:
        return False
    if is_chinext_or_star(code):
        return 6.0 <= pct_change <= 13.0
    return 5.0 <= pct_change <= 8.5


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = resolve_columns(frame.columns)
    df = pd.DataFrame()
    for field, column in columns.items():
        df[field] = frame[column]
    for optional in FIELD_ALIASES:
        if optional not in df:
            df[optional] = None

    df["code"] = df["code"].map(clean_code)
    for text_col in ["name", "theme", "limit_reason"]:
        df[text_col] = df[text_col].fillna("").map(lambda x: str(x).strip())
    for numeric_col in [
        "pct_change",
        "price",
        "capital_net",
        "turnover",
        "volume_ratio",
        "theme_strength",
        "float_market_cap",
        "seal_strength",
    ]:
        df[numeric_col] = df[numeric_col].map(parse_number)
    df = df[(df["code"] != "") & (df["name"] != "") & (df["theme"] != "")]
    return df.reset_index(drop=True)


def summarize_reason(reasons: Sequence[str]) -> str:
    words: Dict[str, int] = {}
    for reason in reasons:
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", reason):
            if token in {"涨停", "原因", "公司", "今日", "相关", "概念"}:
                continue
            words[token] = words.get(token, 0) + 1
    if not words:
        return "资金共振"
    ranked = sorted(words.items(), key=lambda item: (-item[1], item[0]))
    text = "".join(word for word, _ in ranked[:2])
    return text[:20] or "资金共振"


def rank_themes(df: pd.DataFrame, limit: int = 3) -> List[ThemeStats]:
    stats: List[ThemeStats] = []
    for theme, group in df.groupby("theme"):
        limit_group = group[
            group.apply(lambda row: is_limit_up(str(row["code"]), row["pct_change"]), axis=1)
            & (group["limit_reason"].str.len() > 0)
        ]
        if limit_group.empty:
            continue
        limit_count = int(len(limit_group))
        strength = float(group["theme_strength"].dropna().mean()) if group["theme_strength"].notna().any() else 0.0
        capital_net = float(group["capital_net"].dropna().sum()) if group["capital_net"].notna().any() else 0.0
        heat_score = limit_count * 100.0 + strength * 0.25 + capital_net / 100_000_000.0 * 10.0
        seal_values = limit_group["seal_strength"].dropna()
        seal_low = bool(not seal_values.empty and seal_values.median() < 0.5)
        risk_level = "高" if limit_count > 10 or seal_low else ("中" if capital_net < 0 else "低")
        capital_ecology = "合力推土" if capital_net > 0 and not seal_low else "挂单测压"
        liquidity_clash = "板块高潮，警惕分化" if limit_count > 10 else ("龙头封单偏弱，跟风降级" if seal_low else "虹吸风险可控")
        commander_instruction = "只做分歧低吸" if risk_level == "高" else ("等龙头确认" if risk_level == "中" else "关注补涨中军")
        stats.append(
            ThemeStats(
                name=str(theme),
                core_theme=summarize_reason(limit_group["limit_reason"].tolist()),
                limit_up_count=limit_count,
                strength=strength,
                capital_net=capital_net,
                heat_score=heat_score,
                risk_level=risk_level,
                capital_ecology=capital_ecology,
                liquidity_clash=liquidity_clash,
                commander_instruction=commander_instruction,
            )
        )
    return sorted(stats, key=lambda item: item.heat_score, reverse=True)[:limit]


def institution_quality(row: pd.Series) -> Tuple[bool, str]:
    name = str(row.get("name", ""))
    code = str(row.get("code", ""))
    float_cap = row.get("float_market_cap")
    blue_chip_hint = any(key in name for key in ["中国", "中信", "石油", "石化", "银行", "保险", "证券", "军工"])
    active_hint = any(key in name for key in ["通源", "准油", "天银", "中科", "华工", "万丰"])
    cap_hint = float_cap is not None and pd.notna(float_cap) and float_cap >= 10_000_000_000
    index_hint = code.startswith(("000", "001", "600", "601", "603"))
    if blue_chip_hint:
        return True, "央企/行业龙头特征"
    if cap_hint:
        return True, "流通市值较大，机构覆盖概率高"
    if active_hint:
        return True, "历史情绪活跃股"
    if index_hint:
        return True, "主板代表性标的"
    return False, "基本面/机构认可度证据不足"


def strategy_type(row: pd.Series) -> str:
    code = str(row.get("code", ""))
    float_cap = row.get("float_market_cap")
    if is_chinext_or_star(code):
        return "策略C（20CM弹性套利）"
    if float_cap is not None and pd.notna(float_cap):
        if float_cap < 5_000_000_000:
            return "策略A（龙头伴侣/低位补涨）"
        if float_cap > 10_000_000_000:
            return "策略B（中军趋势容量）"
    return "策略A/B（补涨或中军，需结合流通盘确认）"


def pick_candidates(df: pd.DataFrame, themes: Sequence[ThemeStats], max_picks: int = 3) -> List[Pick]:
    theme_names = {theme.name for theme in themes}
    if not theme_names:
        return []
    theme_rank = {theme.name: index for index, theme in enumerate(themes)}
    candidates = df[df["theme"].isin(theme_names)].copy()
    picks: List[Pick] = []
    for _, row in candidates.iterrows():
        code = str(row["code"])
        pct_change = row["pct_change"]
        capital_net = row["capital_net"]
        turnover = row["turnover"]
        volume_ratio = row["volume_ratio"]
        if is_limit_up(code, pct_change):
            continue
        if capital_net is None or pd.isna(capital_net) or capital_net <= 0:
            continue
        if not pct_range_ok(code, pct_change):
            continue
        if capital_net <= 30_000_000:
            continue
        if turnover is None or pd.isna(turnover) or not (5.0 <= turnover <= 20.0):
            continue
        if volume_ratio is not None and pd.notna(volume_ratio) and volume_ratio <= 1.8:
            continue

        quality_ok, quality_reason = institution_quality(row)
        tier = "第一梯队" if quality_ok else "第三梯队"
        theme_bonus = (len(themes) - theme_rank.get(str(row["theme"]), len(themes))) * 10
        score = theme_bonus + float(capital_net) / 100_000_000.0 * 8 + float(pct_change) * 2
        if quality_ok:
            score += 15
        if volume_ratio is not None and pd.notna(volume_ratio):
            score += min(float(volume_ratio), 5.0)

        risk_note = "无硬性风险"
        if turnover > 18:
            risk_note = "换手接近上限，警惕加速分化"
        if is_chinext_or_star(code) and pct_change > 12:
            risk_note = "20CM标的接近筛选上沿，勿追高"

        picks.append(
            Pick(
                theme=str(row["theme"]),
                code=code,
                name=str(row["name"]),
                price=row["price"] if row["price"] is not None and pd.notna(row["price"]) else None,
                pct_change=float(pct_change),
                strategy=strategy_type(row),
                tier=tier,
                profit_logic=(
                    f"{quality_reason}；涨幅、资金净额、换手率"
                    f"{'、量比' if volume_ratio is not None and pd.notna(volume_ratio) else ''}均通过筛选，"
                    f"位于核心题材「{row['theme']}」内，适合作为未涨停补涨候选。"
                ),
                risk_note=risk_note,
                score=score,
            )
        )
    return sorted(picks, key=lambda item: item.score, reverse=True)[:max_picks]


def theme_risk_multiplier(theme: str, themes: Sequence[ThemeStats]) -> float:
    risk = next((item.risk_level for item in themes if item.name == theme), "中")
    return {"低": 1.0, "中": 0.6, "高": 0.25}.get(risk, 0.5)


def stop_loss_pct_for_pick(pick: Pick, profile: SizingProfile) -> Optional[float]:
    if profile.main_stop_loss_pct is None or profile.growth_stop_loss_pct is None:
        return None
    if pick.code.startswith(("300", "301", "688")):
        return profile.growth_stop_loss_pct
    if "换手接近上限" in pick.risk_note:
        return 3.5
    return profile.main_stop_loss_pct


def single_position_cap_pct(pick: Pick, max_single_pct: float, profile: SizingProfile) -> float:
    if profile.key != "local-a-share-theme":
        return min(profile.position_ceiling_pct, max_single_pct)

    if "策略B" in pick.strategy:
        cap = 8.0
    elif "策略C" in pick.strategy:
        cap = 4.0
    else:
        cap = 5.0
    if pick.tier != "第一梯队":
        cap *= 0.5
    if pick.risk_note != "无硬性风险":
        cap *= 0.7
    return min(cap, max_single_pct)


def long_biased_target_pct(pick: Pick, themes: Sequence[ThemeStats], profile: SizingProfile, max_single_pct: float) -> float:
    theme_mult = theme_risk_multiplier(pick.theme, themes)
    if theme_mult <= 0.25:
        return 0.0
    cap_pct = single_position_cap_pct(pick, max_single_pct, profile)
    normalized_score = max(0.0, min((pick.score - 20.0) / 80.0, 1.0))
    target = profile.position_floor_pct + normalized_score * (profile.position_ceiling_pct - profile.position_floor_pct)
    if pick.tier != "第一梯队":
        target *= 0.5
    if pick.risk_note != "无硬性风险":
        target *= 0.7
    target *= theme_mult
    target = min(max(target, 0.0), cap_pct)
    return target if target >= profile.position_floor_pct else 0.0


def build_position_plan(
    picks: Sequence[Pick],
    themes: Sequence[ThemeStats],
    capital: Optional[float] = None,
    max_total_pct: Optional[float] = None,
    max_single_pct: Optional[float] = None,
    risk_budget_pct: Optional[float] = None,
    strategy_profile: str = "llmquant-long-biased",
) -> List[PositionPlan]:
    if not picks:
        return []

    profile = get_sizing_profile(strategy_profile)
    effective_max_total_pct = profile.default_max_total_pct if max_total_pct is None else max_total_pct
    effective_max_single_pct = profile.default_max_single_pct if max_single_pct is None else max_single_pct
    effective_risk_budget_pct = profile.default_risk_budget_pct if risk_budget_pct is None else risk_budget_pct

    raw_plans: List[Tuple[Pick, Optional[float], float]] = []
    for pick in picks:
        stop_pct = stop_loss_pct_for_pick(pick, profile)
        if profile.key in {"quant-paper", "serenity-chokepoint"}:
            target_pct = 0.0
        elif profile.key == "llmquant-long-biased":
            target_pct = long_biased_target_pct(pick, themes, profile, effective_max_single_pct)
        else:
            theme_mult = theme_risk_multiplier(pick.theme, themes)
            cap_pct = single_position_cap_pct(pick, effective_max_single_pct, profile)
            signal_pct = min(max((pick.score - 20.0) / 80.0 * effective_max_single_pct, 0.0), cap_pct)
            risk_pct_cap = (
                effective_risk_budget_pct / stop_pct * 100.0
                if effective_risk_budget_pct is not None and stop_pct not in (None, 0)
                else cap_pct
            )
            target_pct = min(signal_pct * theme_mult, cap_pct, risk_pct_cap)
            if theme_mult <= 0.25:
                target_pct = 0.0
        raw_plans.append((pick, stop_pct, max(0.0, target_pct)))

    total_pct = sum(item[2] for item in raw_plans)
    scale = 1.0
    if effective_max_total_pct is not None and total_pct > effective_max_total_pct and total_pct > 0:
        scale = effective_max_total_pct / total_pct

    plans: List[PositionPlan] = []
    for pick, stop_pct, target_pct in raw_plans:
        target_pct *= scale
        amount = capital * target_pct / 100.0 if capital is not None else None
        max_loss_pct = target_pct * stop_pct / 100.0 if stop_pct is not None else None
        max_loss_amount = capital * max_loss_pct / 100.0 if capital is not None and max_loss_pct is not None else None
        action = "可小仓试错" if target_pct > 0 else "仅观察"
        if profile.key == "llmquant-long-biased":
            reason = (
                "按 LLMQuant long-biased 规则映射：单票3-8%目标区间、10%单名上限、"
                "风险折减后低于3%的候选降为观察；30%单行业和50%前五大集中度需另用组合持仓校验；"
                "本表缺ADV/行业持仓，不能替代实盘下单。"
            )
        elif profile.key == "quant-paper":
            reason = "按 LLMQuant quant 规则，未完成回测和3-6个月paper trading前，目标仓位为0，仅观察记录。"
        elif profile.key == "serenity-chokepoint":
            reason = (
                "按 Serenity chokepoint 研究门槛：先验证产业链瓶颈、不可替代性、需求缺口、认证壁垒、"
                "低发现度和反证清单；题材表只能提供A股热度和资金承接，不能证明结构性胜率，"
                "未完成本地A股回测和纸面交易前目标仓位为0。"
            )
        else:
            stop_text = "未知" if stop_pct is None else f"{stop_pct:.1f}%"
            risk_text = "未设置" if effective_risk_budget_pct is None else f"{effective_risk_budget_pct:.2f}%"
            reason = (
                f"本地A股题材研究模板：按候选分数、题材风险、单票上限、每笔风险预算{risk_text}共同约束；"
                f"止损距离按{'20CM' if pick.code.startswith(('300', '301', '688')) else '主板'}占位{stop_text}估计，非LLMQuant来源。"
            )
        plans.append(
            PositionPlan(
                code=pick.code,
                name=pick.name,
                action=action,
                target_weight_pct=round(target_pct, 3),
                target_weight_band_pct=(
                    f"{profile.position_floor_pct:.1f}-{profile.position_ceiling_pct:.1f}"
                    if profile.key == "llmquant-long-biased" and target_pct > 0
                    else None
                ),
                target_amount=None if amount is None else round(amount, 2),
                stop_loss_pct=None if stop_pct is None else round(stop_pct, 3),
                max_loss_pct=None if max_loss_pct is None else round(max_loss_pct, 3),
                max_loss_amount=None if max_loss_amount is None else round(max_loss_amount, 2),
                source_profile=profile.key,
                sizing_reason=reason,
            )
        )
    return plans


def scan_theme_table(
    frame: pd.DataFrame,
    analysis_date: Optional[str] = None,
    max_picks: int = 3,
    capital: Optional[float] = None,
    max_total_pct: Optional[float] = None,
    max_single_pct: Optional[float] = None,
    risk_budget_pct: Optional[float] = None,
    strategy_profile: str = "llmquant-long-biased",
) -> Dict[str, object]:
    df = normalize_frame(frame)
    themes = rank_themes(df, limit=3)
    picks = pick_candidates(df, themes, max_picks=max_picks)
    profile = get_sizing_profile(strategy_profile)
    effective_max_total_pct = profile.default_max_total_pct if max_total_pct is None else max_total_pct
    effective_max_single_pct = profile.default_max_single_pct if max_single_pct is None else max_single_pct
    effective_risk_budget_pct = profile.default_risk_budget_pct if risk_budget_pct is None else risk_budget_pct
    plans = build_position_plan(
        picks,
        themes,
        capital=capital,
        max_total_pct=max_total_pct,
        max_single_pct=max_single_pct,
        risk_budget_pct=risk_budget_pct,
        strategy_profile=profile.key,
    )
    best_theme = themes[0].name if themes else ""
    return {
        "analysis_date": analysis_date or date.today().isoformat(),
        "most_promising_theme": best_theme,
        "theme_analyses": [
            {
                "sector_name": item.name,
                "core_theme": item.core_theme,
                "limit_up_count": item.limit_up_count,
                "theme_strength": round(item.strength, 4),
                "capital_net": round(item.capital_net, 2),
                "heat_score": round(item.heat_score, 4),
                "capital_ecology": item.capital_ecology,
                "liquidity_clash": item.liquidity_clash,
                "risk_level": item.risk_level,
                "commander_instruction": item.commander_instruction,
            }
            for item in themes
        ],
        "alpha_picks": [
            {
                "题材名称": item.theme,
                "股票代码": item.code,
                "股票名称": item.name,
                "当前价格": None if item.price is None else round(item.price, 3),
                "今日涨幅": round(item.pct_change, 3),
                "策略类型": item.strategy,
                "梯队": item.tier,
                "profit_logic": item.profit_logic,
                "risk_note": item.risk_note,
            }
            for item in picks
        ],
        "position_plan": [
            {
                "股票代码": item.code,
                "股票名称": item.name,
                "动作": item.action,
                "目标仓位%": item.target_weight_pct,
                "目标仓位区间%": item.target_weight_band_pct,
                "目标金额": item.target_amount,
                "止损距离%": item.stop_loss_pct,
                "组合最大亏损%": item.max_loss_pct,
                "最大亏损金额": item.max_loss_amount,
                "仓位profile": item.source_profile,
                "仓位理由": item.sizing_reason,
            }
            for item in plans
        ],
        "portfolio_controls": {
            "strategy_profile": profile.key,
            "profile_label": profile.label,
            "profile_source": profile.source,
            "profile_note": profile.note,
            "source_rules": list(profile.source_rules),
            "max_total_weight_pct": effective_max_total_pct,
            "max_single_weight_pct": effective_max_single_pct,
            "per_trade_risk_budget_pct": effective_risk_budget_pct,
            "capital": capital,
            "entry_rule": "开盘前只生成计划；9:30-9:45不追价，10:00前后确认题材延续、个股承接和资金未转弱后才允许执行研究仓位。",
        },
        "risk_controls": [
            "所有推荐股票必须来自输入表格",
            "已排除涨停股、资金净额非正、量化条件不达标标的",
            "仓位数字必须标明来源profile；LLMQuant profile只提供组合约束，不替代A股实盘回测",
            "结果仅供研究复盘，不构成投资建议或自动交易信号",
        ],
    }


def read_csv(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="gbk")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股题材轮动与潜力股筛选")
    parser.add_argument("--csv", required=True, help="包含涨停分析/题材/资金/涨幅等字段的CSV")
    parser.add_argument("--date", default=None, help="分析日期，默认使用今天")
    parser.add_argument("--max-picks", type=int, default=3, help="最多输出几只候选股，默认3")
    parser.add_argument("--capital", type=float, default=None, help="研究账户资金规模；提供后输出目标金额")
    parser.add_argument(
        "--strategy-profile",
        choices=sorted(SIZING_PROFILES),
        default="llmquant-long-biased",
        help="仓位profile；默认使用LLMQuant long-biased来源规则",
    )
    parser.add_argument("--max-total-pct", type=float, default=None, help="覆盖profile的组合总暴露上限")
    parser.add_argument("--max-single-pct", type=float, default=None, help="覆盖profile的单票目标仓位上限")
    parser.add_argument("--risk-budget-pct", type=float, default=None, help="覆盖profile的每笔止损风险预算；LLMQuant long-biased默认不使用")
    args = parser.parse_args(argv)

    try:
        result = scan_theme_table(
            read_csv(args.csv),
            analysis_date=args.date,
            max_picks=max(1, min(args.max_picks, 3)),
            capital=args.capital,
            max_total_pct=None if args.max_total_pct is None else max(0.0, min(args.max_total_pct, 100.0)),
            max_single_pct=None if args.max_single_pct is None else max(0.0, min(args.max_single_pct, 100.0)),
            risk_budget_pct=None if args.risk_budget_pct is None else max(0.0, min(args.risk_budget_pct, 10.0)),
            strategy_profile=args.strategy_profile,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
