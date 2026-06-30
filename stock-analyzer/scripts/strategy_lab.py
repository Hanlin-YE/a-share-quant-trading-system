#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Strategy registry, batch backtest comparison, and parameter search."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import backtest
import analyze


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
STRATEGY_PATH = JOURNAL_DIR / "strategies.json"


@dataclass
class Strategy:
    id: str
    name: str
    description: str
    config: backtest.BacktestConfig
    score_profile: str = "balanced"


@dataclass
class OptimizationConfig:
    score_profiles: Tuple[str, ...] = ("balanced", "trend", "mean_reversion")
    entry_scores: Tuple[float, ...] = (54.0, 58.0, 62.0, 66.0)
    exit_scores: Tuple[float, ...] = (38.0, 42.0, 46.0, 50.0)
    max_position_pcts: Tuple[float, ...] = (10.0, 15.0, 20.0)
    max_total_exposure_pcts: Tuple[float, ...] = (40.0, 60.0, 80.0)
    train_pct: float = 0.50
    validation_pct: float = 0.25
    min_trades: int = 2
    max_drawdown_pct: float = 20.0
    min_history: int = 80
    walk_forward_windows: int = 3
    walk_forward_min_traded_windows: int = 2
    walk_forward_top_n: int = 5


def load_strategies(path: Path = STRATEGY_PATH) -> List[Strategy]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    strategies = []
    for item in payload.get("strategies", []):
        strategies.append(
            Strategy(
                id=item["id"],
                name=item.get("name", item["id"]),
                description=item.get("description", ""),
                config=backtest.BacktestConfig(
                    initial_cash=float(item.get("initial_cash", 1_000_000.0)),
                    entry_score=float(item.get("entry_score", 58.0)),
                    exit_score=float(item.get("exit_score", 45.0)),
                    max_position_pct=float(item.get("max_position_pct", 20.0)),
                    max_total_exposure_pct=float(item.get("max_total_exposure_pct", 80.0)),
                    fee_bps=float(item.get("fee_bps", 3.0)),
                    min_commission=float(item.get("min_commission", 5.0)),
                    tax_bps=float(item.get("tax_bps", 5.0)),
                    transfer_bps=float(item.get("transfer_bps", 0.1)),
                    slippage_bps=float(item.get("slippage_bps", 5.0)),
                ),
                score_profile=item.get("score_profile", "balanced"),
            )
        )
    return strategies


def parse_float_list(raw: str) -> Tuple[float, ...]:
    values = tuple(float(item.strip()) for item in raw.split(",") if item.strip())
    if not values:
        raise ValueError("parameter list cannot be empty")
    return values


def generate_parameter_grid(
    base_config: Optional[backtest.BacktestConfig] = None,
    optimization: Optional[OptimizationConfig] = None,
) -> List[Strategy]:
    cfg = base_config or backtest.BacktestConfig()
    opt = optimization or OptimizationConfig()
    strategies: List[Strategy] = []
    for profile in opt.score_profiles:
        for entry_score in opt.entry_scores:
            for exit_score in opt.exit_scores:
                if exit_score >= entry_score:
                    continue
                for max_position_pct in opt.max_position_pcts:
                    for max_total_exposure_pct in opt.max_total_exposure_pcts:
                        strategy_config = backtest.BacktestConfig(
                            initial_cash=cfg.initial_cash,
                            entry_score=entry_score,
                            exit_score=exit_score,
                            max_position_pct=max_position_pct,
                            max_total_exposure_pct=max_total_exposure_pct,
                            fee_bps=cfg.fee_bps,
                            min_commission=cfg.min_commission,
                            tax_bps=cfg.tax_bps,
                            transfer_bps=cfg.transfer_bps,
                            slippage_bps=cfg.slippage_bps,
                            min_history=opt.min_history,
                            lot_size=cfg.lot_size,
                        )
                        strategy_id = (
                            f"grid-{profile}-e{entry_score:g}-x{exit_score:g}"
                            f"-p{max_position_pct:g}-t{max_total_exposure_pct:g}"
                        )
                        strategies.append(
                            Strategy(
                                id=strategy_id,
                                name=f"参数网格 {strategy_id}",
                                description="自动参数搜索候选，仅用于训练/研究。",
                                config=strategy_config,
                                score_profile=profile,
                            )
                        )
    return strategies


def split_frames_by_time(
    frames: Dict[str, object],
    train_pct: float,
    validation_pct: float,
) -> Dict[str, Dict[str, object]]:
    if train_pct <= 0 or validation_pct <= 0 or train_pct + validation_pct >= 1:
        raise ValueError("train_pct and validation_pct must be positive and leave room for test")
    splits: Dict[str, Dict[str, object]] = {"train": {}, "validation": {}, "test": {}}
    for symbol, frame in frames.items():
        normalized = backtest.normalize_frame(frame)
        train_end = max(1, int(len(normalized) * train_pct))
        validation_end = max(train_end + 1, int(len(normalized) * (train_pct + validation_pct)))
        splits["train"][symbol] = normalized.iloc[:train_end].copy()
        splits["validation"][symbol] = normalized.iloc[train_end:validation_end].copy()
        splits["test"][symbol] = normalized.iloc[validation_end:].copy()
    return splits


def optimization_objective(metrics: Dict[str, float], opt: OptimizationConfig) -> float:
    trade_penalty = max(0, opt.min_trades - int(metrics.get("trade_count", 0))) * 5.0
    drawdown_excess = max(0.0, float(metrics.get("max_drawdown_pct", 0.0)) - opt.max_drawdown_pct)
    return (
        float(metrics.get("total_return_pct", 0.0))
        + 0.25 * float(metrics.get("sharpe", 0.0))
        - 0.75 * float(metrics.get("max_drawdown_pct", 0.0))
        - 2.0 * drawdown_excess
        - trade_penalty
    )


def prefixed_metrics(prefix: str, metrics: Dict[str, float]) -> Dict[str, object]:
    fields = [
        "total_return_pct",
        "annualized_return_pct",
        "max_drawdown_pct",
        "daily_win_rate_pct",
        "sharpe",
        "trade_count",
        "avg_exposure_pct",
        "final_equity",
    ]
    return {f"{prefix}_{field}": metrics.get(field, "") for field in fields}


def memoized_score_func(score_func: backtest.ScoreFn) -> backtest.ScoreFn:
    cache: Dict[Tuple[str, str, str, int], Tuple[float, str]] = {}

    def cached(symbol: str, history: object) -> Tuple[float, str]:
        if history.empty:
            return score_func(symbol, history)
        first_date = str(history["date"].iloc[0])
        last_date = str(history["date"].iloc[-1])
        key = (symbol, first_date, last_date, len(history))
        if key not in cache:
            cache[key] = score_func(symbol, history)
        return cache[key]

    return cached


def score_symbol_history_with_profile(symbol: str, history: object, profile: str = "balanced") -> Tuple[float, str]:
    scored = analyze.add_indicators(history)
    latest = scored.iloc[-1]
    base_score, suggestion = backtest.score_symbol_history(symbol, history)
    if profile == "trend":
        bonus = 0.0
        if latest.get("ma_5", 0) > latest.get("ma_10", 0) > latest.get("ma_20", 0):
            bonus += 8.0
        if latest.get("close", 0) > latest.get("ma_20", 0):
            bonus += 4.0
        if latest.get("macd_hist", 0) > 0:
            bonus += 4.0
        if latest.get("rsi_14", 50) > 72:
            bonus -= 5.0
        return max(0.0, min(100.0, base_score + bonus)), f"{suggestion} / trend"
    if profile == "mean_reversion":
        bonus = 0.0
        if latest.get("rsi_14", 50) < 35:
            bonus += 8.0
        if latest.get("kdj_j", 50) < 20:
            bonus += 5.0
        if latest.get("drawdown_60", 0) < -0.12:
            bonus += 5.0
        if latest.get("close", 0) < latest.get("ma_60", 0):
            bonus -= 3.0
        return max(0.0, min(100.0, base_score + bonus)), f"{suggestion} / mean_reversion"
    return base_score, f"{suggestion} / balanced"


def profile_score_func(profile: str) -> backtest.ScoreFn:
    return lambda symbol, history: score_symbol_history_with_profile(symbol, history, profile)


def walk_forward_slices(frame: object, windows: int, min_history: int) -> List[object]:
    normalized = backtest.normalize_frame(frame)
    min_len = min_history + 2
    if len(normalized) < min_len or windows <= 0:
        return []
    slices = []
    step = max(1, (len(normalized) - min_len) // max(1, windows - 1)) if windows > 1 else 0
    for index in range(windows):
        start = min(index * step, max(0, len(normalized) - min_len))
        window = normalized.iloc[start:].copy()
        if len(window) >= min_len:
            slices.append(window)
    return slices


def walk_forward_frames(frames: Dict[str, object], windows: int, min_history: int) -> List[Dict[str, object]]:
    per_symbol = {
        symbol: walk_forward_slices(frame, windows=windows, min_history=min_history)
        for symbol, frame in frames.items()
    }
    if not per_symbol:
        return []
    available = min((len(items) for items in per_symbol.values()), default=0)
    output = []
    for idx in range(available):
        output.append({symbol: slices[idx] for symbol, slices in per_symbol.items()})
    return output


def evaluate_walk_forward_from_frames(
    frames: Dict[str, object],
    strategy: Strategy,
    optimization: Optional[OptimizationConfig] = None,
    score_func: backtest.ScoreFn = backtest.score_symbol_history,
) -> Dict[str, object]:
    opt = optimization or OptimizationConfig()
    windows = walk_forward_frames(frames, windows=opt.walk_forward_windows, min_history=opt.min_history)
    window_rows = []
    for index, window_frames in enumerate(windows, start=1):
        try:
            result = backtest.run_backtest_from_frames(window_frames, strategy.config, score_func=score_func)
            metrics = result.metrics
            window_rows.append(
                {
                    "window": index,
                    "status": "ok",
                    "total_return_pct": metrics["total_return_pct"],
                    "max_drawdown_pct": metrics["max_drawdown_pct"],
                    "trade_count": metrics["trade_count"],
                    "sharpe": metrics["sharpe"],
                }
            )
        except Exception as exc:
            window_rows.append({"window": index, "status": "failed", "error": str(exc)})
    ok_rows = [row for row in window_rows if row.get("status") == "ok"]
    traded_rows = [row for row in ok_rows if float(row.get("trade_count", 0) or 0) > 0]
    positive_rows = [row for row in ok_rows if float(row.get("total_return_pct", 0) or 0) > 0]
    avg_return = sum(float(row.get("total_return_pct", 0) or 0) for row in ok_rows) / len(ok_rows) if ok_rows else 0.0
    worst_drawdown = max((float(row.get("max_drawdown_pct", 0) or 0) for row in ok_rows), default=0.0)
    return {
        "walk_forward_window_count": len(window_rows),
        "walk_forward_ok_windows": len(ok_rows),
        "walk_forward_traded_windows": len(traded_rows),
        "walk_forward_positive_windows": len(positive_rows),
        "walk_forward_avg_return_pct": round(avg_return, 4),
        "walk_forward_worst_drawdown_pct": round(worst_drawdown, 4),
        "walk_forward_windows": window_rows,
    }


def evaluate_strategy_splits_from_frames(
    frames: Dict[str, object],
    strategy: Strategy,
    optimization: Optional[OptimizationConfig] = None,
    score_func: backtest.ScoreFn = backtest.score_symbol_history,
) -> Dict[str, object]:
    opt = optimization or OptimizationConfig()
    split_frames = split_frames_by_time(frames, opt.train_pct, opt.validation_pct)
    row: Dict[str, object] = {
        "strategy_id": strategy.id,
        "strategy_name": strategy.name,
        "entry_score": strategy.config.entry_score,
        "exit_score": strategy.config.exit_score,
        "score_profile": strategy.score_profile,
        "max_position_pct": strategy.config.max_position_pct,
        "max_total_exposure_pct": strategy.config.max_total_exposure_pct,
        "status": "ok",
        "notes": "",
    }
    objectives: Dict[str, float] = {}
    notes: List[str] = []
    for split_name in ("train", "validation", "test"):
        try:
            result = backtest.run_backtest_from_frames(
                split_frames[split_name],
                strategy.config,
                score_func=score_func,
            )
            row.update(prefixed_metrics(split_name, result.metrics))
            objectives[split_name] = optimization_objective(result.metrics, opt)
            notes.extend(f"{split_name}: {note}" for note in result.notes)
        except Exception as exc:
            row["status"] = "failed"
            row[f"{split_name}_error"] = str(exc)
            objectives[split_name] = -1_000_000.0
    row["train_objective"] = round(objectives["train"], 4)
    row["validation_objective"] = round(objectives["validation"], 4)
    row["test_objective"] = round(objectives["test"], 4)
    row["selection_basis"] = "validation_objective"
    row["notes"] = "; ".join(notes)
    return row


def optimize_strategies_from_frames(
    frames: Dict[str, object],
    strategies: List[Strategy],
    optimization: Optional[OptimizationConfig] = None,
    score_func: backtest.ScoreFn = backtest.score_symbol_history,
) -> List[Dict[str, object]]:
    score_funcs: Dict[str, backtest.ScoreFn] = {}
    def scorer_for(strategy: Strategy) -> backtest.ScoreFn:
        if score_func is not backtest.score_symbol_history:
            key = "__custom__"
            if key not in score_funcs:
                score_funcs[key] = memoized_score_func(score_func)
            return score_funcs[key]
        profile = strategy.score_profile or "balanced"
        if profile not in score_funcs:
            score_funcs[profile] = memoized_score_func(profile_score_func(profile))
        return score_funcs[profile]

    rows = [
        evaluate_strategy_splits_from_frames(frames, strategy, optimization, scorer_for(strategy))
        for strategy in strategies
    ]
    ranked = rank_optimization_rows(rows)
    strategy_by_id = {strategy.id: strategy for strategy in strategies}
    opt = optimization or OptimizationConfig()
    cutoff = None
    eligible_rows = [row for row in ranked if row.get("status") == "ok"]
    if opt.walk_forward_top_n > 0 and eligible_rows:
        cutoff_index = min(opt.walk_forward_top_n, len(eligible_rows)) - 1
        cutoff = float(eligible_rows[cutoff_index].get("validation_objective", -1_000_000.0))
    for index, row in enumerate(ranked):
        strategy = strategy_by_id.get(str(row.get("strategy_id")))
        should_walk = (
            cutoff is not None
            and row.get("status") == "ok"
            and float(row.get("validation_objective", -1_000_000.0)) >= cutoff
        )
        if should_walk and strategy is not None:
            row.update(evaluate_walk_forward_from_frames(frames, strategy, opt, score_func=scorer_for(strategy)))
        else:
            row.update(
                {
                    "walk_forward_window_count": 0,
                    "walk_forward_ok_windows": 0,
                    "walk_forward_traded_windows": 0,
                    "walk_forward_positive_windows": 0,
                    "walk_forward_avg_return_pct": 0.0,
                    "walk_forward_worst_drawdown_pct": 0.0,
                    "walk_forward_windows": [],
                }
            )
    return rank_optimization_rows(ranked)


def rank_optimization_rows(rows: Iterable[Dict[str, object]]) -> List[Dict[str, object]]:
    return sorted(
        rows,
        key=lambda item: (
            item.get("status") == "ok",
            float(item.get("validation_objective", -1_000_000.0)),
            float(item.get("validation_total_return_pct", -1_000_000.0) or -1_000_000.0),
            -float(item.get("validation_max_drawdown_pct", 1_000_000.0) or 1_000_000.0),
            float(item.get("train_objective", -1_000_000.0)),
        ),
        reverse=True,
    )


def compare_strategies_from_frames(
    frames: Dict[str, object],
    strategies: List[Strategy],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for strategy in strategies:
        result = backtest.run_backtest_from_frames(frames, strategy.config)
        metrics = result.metrics
        rows.append(
            {
                "strategy_id": strategy.id,
                "strategy_name": strategy.name,
                "total_return_pct": metrics["total_return_pct"],
                "annualized_return_pct": metrics["annualized_return_pct"],
                "max_drawdown_pct": metrics["max_drawdown_pct"],
                "daily_win_rate_pct": metrics["daily_win_rate_pct"],
                "sharpe": metrics["sharpe"],
                "trade_count": int(metrics["trade_count"]),
                "avg_exposure_pct": metrics["avg_exposure_pct"],
                "final_equity": metrics["final_equity"],
                "notes": "; ".join(result.notes),
            }
        )
    return rows


def sort_strategy_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return sorted(
        rows,
        key=lambda item: (
            float(item["total_return_pct"]),
            -float(item["max_drawdown_pct"]),
            float(item["sharpe"]),
        ),
        reverse=True,
    )


def write_comparison(rows: List[Dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "strategy_id",
        "strategy_name",
        "total_return_pct",
        "annualized_return_pct",
        "max_drawdown_pct",
        "daily_win_rate_pct",
        "sharpe",
        "trade_count",
        "avg_exposure_pct",
        "final_equity",
        "notes",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_rows_dynamic(rows: List[Dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields: List[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_recommendation_payload(rows: List[Dict[str, object]]) -> Dict[str, object]:
    if not rows or rows[0].get("status") != "ok":
        return {
            "status": "no_candidate",
            "reason": "no optimization candidate completed train/validation/test evaluation",
            "risk_note": "仅用于训练/研究，不构成投资建议、稳定盈利承诺或自动交易信号。",
        }
    best = rows[0]
    candidate = {
        "strategy_id": best["strategy_id"],
        "score_profile": best.get("score_profile", "balanced"),
        "entry_score": best["entry_score"],
        "exit_score": best["exit_score"],
        "max_position_pct": best["max_position_pct"],
        "max_total_exposure_pct": best["max_total_exposure_pct"],
        "selection_basis": best["selection_basis"],
        "validation": {
            "objective": best.get("validation_objective"),
            "total_return_pct": best.get("validation_total_return_pct"),
            "max_drawdown_pct": best.get("validation_max_drawdown_pct"),
            "sharpe": best.get("validation_sharpe"),
            "trade_count": best.get("validation_trade_count"),
        },
        "test": {
            "objective": best.get("test_objective"),
            "total_return_pct": best.get("test_total_return_pct"),
            "max_drawdown_pct": best.get("test_max_drawdown_pct"),
            "sharpe": best.get("test_sharpe"),
            "trade_count": best.get("test_trade_count"),
        },
        "walk_forward": {
            "window_count": best.get("walk_forward_window_count"),
            "ok_windows": best.get("walk_forward_ok_windows"),
            "traded_windows": best.get("walk_forward_traded_windows"),
            "positive_windows": best.get("walk_forward_positive_windows"),
            "avg_return_pct": best.get("walk_forward_avg_return_pct"),
            "worst_drawdown_pct": best.get("walk_forward_worst_drawdown_pct"),
        },
    }
    promotion_gate = build_promotion_gate(best)
    return {
        "status": "candidate_found",
        "recommended_candidate": candidate,
        "promotion_gate": promotion_gate,
        "next_search": next_search_suggestion(best, promotion_gate),
        "risk_note": "仅用于训练/研究，不构成投资建议、稳定盈利承诺或自动交易信号。",
    }


def build_promotion_gate(row: Dict[str, object]) -> Dict[str, object]:
    checks = [
        ("validation_objective > 0", float(row.get("validation_objective", -1_000_000.0)) > 0),
        ("test_total_return_pct > 0", float(row.get("test_total_return_pct", -1_000_000.0) or -1_000_000.0) > 0),
        ("test_max_drawdown_pct <= 20", float(row.get("test_max_drawdown_pct", 1_000_000.0) or 1_000_000.0) <= 20.0),
        ("test_trade_count >= 2", int(float(row.get("test_trade_count", 0) or 0)) >= 2),
        ("walk_forward_traded_windows >= 2", int(float(row.get("walk_forward_traded_windows", 0) or 0)) >= 2),
        ("walk_forward_avg_return_pct > 0", float(row.get("walk_forward_avg_return_pct", -1_000_000.0) or -1_000_000.0) > 0),
    ]
    failed = [name for name, passed in checks if not passed]
    return {
        "eligible_for_paper_trading": not failed,
        "rules": [name for name, _ in checks],
        "failed_rules": failed,
        "note": "通过晋级门槛也只允许进入纸面交易观察，不允许自动真实下单。",
    }


def next_search_suggestion(row: Dict[str, object], gate: Dict[str, object]) -> Dict[str, object]:
    failed = set(gate.get("failed_rules", []))
    actions = []
    if "test_trade_count >= 2" in failed:
        actions.append("测试集无足够交易，优先扩大可回测股票池或延长测试窗口，不建议直接晋级。")
    if "test_total_return_pct > 0" in failed:
        actions.append("测试集收益未转正，下一轮保留样本外门槛并比较更多策略族。")
    if "walk_forward_avg_return_pct > 0" in failed:
        actions.append("滚动样本外平均收益为负，下一轮降低过拟合风险，优先扩充股票池。")
    if "walk_forward_traded_windows >= 2" in failed:
        actions.append("滚动窗口交易覆盖不足，检查阈值是否过严或样本窗口是否过窄。")
    if not actions:
        actions.append("候选满足晋级门槛，可进入纸面交易观察，仍禁止真实自动下单。")
    return {
        "profile": row.get("score_profile", "balanced"),
        "actions": actions,
        "recommended_next": "expand_cache_pool" if failed else "paper_trade_observation",
    }


def write_recommendation(rows: List[Dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_recommendation_payload(rows)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def strategy_item_from_recommendation(
    payload: Dict[str, object],
    strategy_id: str = "paper-auto-optimized-v1",
) -> Dict[str, object]:
    if payload.get("status") != "candidate_found":
        raise ValueError("recommendation has no candidate")
    gate = payload.get("promotion_gate", {})
    if not isinstance(gate, dict) or not gate.get("eligible_for_paper_trading"):
        raise ValueError("candidate did not pass paper-trading promotion gate")
    candidate = payload.get("recommended_candidate", {})
    if not isinstance(candidate, dict):
        raise ValueError("recommendation candidate is malformed")
    source_id = str(candidate["strategy_id"])
    return {
        "id": strategy_id,
        "name": "自动优化纸面策略 v1",
        "description": (
            f"由策略参数优化候选 {source_id} 晋级，仅用于纸面交易观察；"
            "不构成投资建议或真实交易信号。"
        ),
        "source_strategy_id": source_id,
        "promotion_status": "paper_trading_only",
        "score_profile": candidate.get("score_profile", "balanced"),
        "entry_score": float(candidate["entry_score"]),
        "exit_score": float(candidate["exit_score"]),
        "max_position_pct": float(candidate["max_position_pct"]),
        "max_total_exposure_pct": float(candidate["max_total_exposure_pct"]),
        "fee_bps": 3.0,
        "min_commission": 5.0,
        "tax_bps": 5.0,
        "transfer_bps": 0.1,
        "slippage_bps": 5.0,
        "validation_total_return_pct": candidate.get("validation", {}).get("total_return_pct"),
        "validation_max_drawdown_pct": candidate.get("validation", {}).get("max_drawdown_pct"),
        "test_total_return_pct": candidate.get("test", {}).get("total_return_pct"),
        "test_max_drawdown_pct": candidate.get("test", {}).get("max_drawdown_pct"),
    }


def promote_recommendation_to_registry(
    recommendation_path: Path,
    registry_path: Path = STRATEGY_PATH,
    strategy_id: str = "paper-auto-optimized-v1",
) -> Dict[str, object]:
    payload = json.loads(recommendation_path.read_text(encoding="utf-8"))
    item = strategy_item_from_recommendation(payload, strategy_id=strategy_id)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    strategies = registry.setdefault("strategies", [])
    replaced = False
    for index, existing in enumerate(strategies):
        if existing.get("id") == strategy_id:
            strategies[index] = item
            replaced = True
            break
    if not replaced:
        strategies.append(item)
    registry["active_paper_strategy_id"] = strategy_id
    registry["active_paper_strategy_note"] = "仅用于纸面交易观察，不允许自动真实下单。"
    registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return item


def render_comparison(rows: List[Dict[str, object]]) -> str:
    lines = ["策略对比", "=" * 40]
    for row in sort_strategy_rows(rows):
        lines.append(
            f"- {row['strategy_id']}: 收益{row['total_return_pct']}%，"
            f"回撤{row['max_drawdown_pct']}%，Sharpe {row['sharpe']}，交易{row['trade_count']}次"
        )
    lines.append("风险提示: 仅用于训练/研究，不构成投资建议或自动交易信号。")
    return "\n".join(lines)


def render_optimization(rows: List[Dict[str, object]]) -> str:
    lines = ["策略参数优化", "=" * 40]
    if not rows:
        lines.append("没有可评估的策略候选。")
        return "\n".join(lines)
    best = rows[0]
    if best.get("status") != "ok":
        lines.append("所有候选均未通过训练/验证/测试评估。")
    else:
        lines.append(
            "推荐候选: "
            f"{best['strategy_id']}，入场{best['entry_score']}，退出{best['exit_score']}，"
            f"单票{best['max_position_pct']}%，总暴露{best['max_total_exposure_pct']}%"
        )
        lines.append(
            "验证集: "
            f"收益{best.get('validation_total_return_pct')}%，"
            f"回撤{best.get('validation_max_drawdown_pct')}%，"
            f"Sharpe {best.get('validation_sharpe')}，"
            f"交易{best.get('validation_trade_count')}次"
        )
        lines.append(
            "测试集仅复核不参与选择: "
            f"收益{best.get('test_total_return_pct')}%，"
            f"回撤{best.get('test_max_drawdown_pct')}%，"
            f"Sharpe {best.get('test_sharpe')}"
        )
    lines.append("")
    lines.append("候选排行")
    for row in rows[:5]:
        lines.append(
            f"- {row['strategy_id']}: 状态{row.get('status')}，"
            f"验证目标{row.get('validation_objective')}，"
            f"验证收益{row.get('validation_total_return_pct', 'N/A')}%，"
            f"测试收益{row.get('test_total_return_pct', 'N/A')}%"
        )
    lines.append("")
    lines.append("规则说明: 参数只按验证集排序，测试集只用于样本外复核，避免用测试集挑策略。")
    lines.append("风险提示: 仅用于训练/研究，不构成投资建议、稳定盈利承诺或自动交易信号。")
    return "\n".join(lines)


def require_market_frames(frames: Dict[str, object], stocks: List[str]) -> None:
    if frames:
        return
    requested = ",".join(stocks)
    raise RuntimeError(
        f"没有可用行情数据，无法运行策略实验。请求标的: {requested}。"
        "请检查 DNS/网络、腾讯/东方财富/Stooq 可用性，或先生成可验证行情缓存。"
    )


def require_cache_health(stocks: List[str], days: int, min_rows: int, max_age_hours: int) -> Dict[str, object]:
    health = analyze.inspect_market_cache(
        stocks,
        days=days,
        min_rows=min_rows,
        max_age_hours=max_age_hours,
    )
    if not health.get("ok"):
        raise RuntimeError(analyze.render_market_cache_health(health))
    return health


def healthy_stocks_from_cache_health(health: Dict[str, object]) -> List[str]:
    healthy = []
    for item in health.get("results", []):
        if item.get("usable") and item.get("stock_code"):
            healthy.append(str(item["stock_code"]))
    return healthy


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股策略版本与参数扫描")
    parser.add_argument("--stocks", default="")
    parser.add_argument("--days", type=int, default=360)
    parser.add_argument("--source", default="auto", choices=["premium", "push", "pull", "tushare", "auto", "tencent", "eastmoney", "stooq"])
    parser.add_argument("--strategies", default=str(STRATEGY_PATH))
    parser.add_argument("--output", default=str(JOURNAL_DIR / "strategy-runs" / "latest.csv"))
    parser.add_argument("--recommendation-output", default="", help="优化模式下可选：写出推荐候选 JSON")
    parser.add_argument("--promote-if-eligible", action="store_true", help="优化候选通过门槛时写入纸面策略注册表")
    parser.add_argument("--promoted-strategy-id", default="paper-auto-optimized-v1")
    parser.add_argument("--optimize", action="store_true", help="运行参数网格优化，使用训练/验证/测试切分")
    parser.add_argument("--score-profiles", default="balanced,trend,mean_reversion")
    parser.add_argument("--entry-scores", default="54,58,62,66")
    parser.add_argument("--exit-scores", default="38,42,46,50")
    parser.add_argument("--max-position-pcts", default="10,15,20")
    parser.add_argument("--max-total-exposure-pcts", default="40,60,80")
    parser.add_argument("--train-pct", type=float, default=0.50)
    parser.add_argument("--validation-pct", type=float, default=0.25)
    parser.add_argument("--min-trades", type=int, default=2)
    parser.add_argument("--max-drawdown-pct", type=float, default=20.0)
    parser.add_argument("--min-history", type=int, default=80)
    parser.add_argument("--walk-forward-top-n", type=int, default=5)
    parser.add_argument("--require-cache-health", action="store_true", help="优化前要求本地行情缓存健康")
    parser.add_argument("--allow-partial-cache-health", action="store_true", help="缓存门禁失败时允许只使用健康标的继续研究回测")
    parser.add_argument("--use-cache-pool", action="store_true", help="从本地健康缓存自动发现股票池")
    parser.add_argument("--cache-pool-limit", type=int, default=20)
    parser.add_argument("--cache-max-age-hours", type=int, default=36)
    parser.add_argument("--cache-min-rows", type=int, default=80)
    args = parser.parse_args(argv)

    stocks = analyze.split_stock_list(args.stocks)
    if args.use_cache_pool:
        pool = analyze.discover_cached_stock_pool(
            days=args.days,
            min_rows=max(1, args.cache_min_rows),
            max_age_hours=max(1, args.cache_max_age_hours),
            limit=max(1, args.cache_pool_limit),
        )
        stocks = list(pool.get("stocks") or [])
        print("使用本地缓存发现股票池:")
        print(",".join(stocks) if stocks else "无")
        if not stocks:
            print(json.dumps(pool, ensure_ascii=False, indent=2))
            return 2
    if not stocks:
        print("未提供股票列表；请使用 --stocks 或 --use-cache-pool。")
        return 2
    if args.require_cache_health:
        cache_health = None
        try:
            cache_health = require_cache_health(
                stocks,
                days=args.days,
                min_rows=max(1, args.cache_min_rows),
                max_age_hours=max(1, args.cache_max_age_hours),
            )
        except RuntimeError as exc:
            if not args.allow_partial_cache_health:
                print(str(exc))
                return 2
            cache_health = analyze.inspect_market_cache(
                stocks,
                days=args.days,
                min_rows=max(1, args.cache_min_rows),
                max_age_hours=max(1, args.cache_max_age_hours),
            )
            partial_stocks = healthy_stocks_from_cache_health(cache_health)
            if not partial_stocks:
                print(str(exc))
                return 2
            print("缓存门禁部分通过，仅使用健康标的继续研究回测:")
            print(",".join(partial_stocks))
            stocks = partial_stocks
        if cache_health:
            import os
            os.environ["A_SHARE_CACHE_MAX_AGE_HOURS"] = str(max(1, args.cache_max_age_hours))
    frames = backtest.load_market_frames(stocks, args.days, args.source)
    try:
        require_market_frames(frames, stocks)
    except RuntimeError as exc:
        print(str(exc))
        return 2
    if args.optimize:
        optimization = OptimizationConfig(
            score_profiles=tuple(item.strip() for item in args.score_profiles.split(",") if item.strip()),
            entry_scores=parse_float_list(args.entry_scores),
            exit_scores=parse_float_list(args.exit_scores),
            max_position_pcts=parse_float_list(args.max_position_pcts),
            max_total_exposure_pcts=parse_float_list(args.max_total_exposure_pcts),
            train_pct=args.train_pct,
            validation_pct=args.validation_pct,
            min_trades=args.min_trades,
            max_drawdown_pct=args.max_drawdown_pct,
            min_history=args.min_history,
            walk_forward_top_n=max(0, args.walk_forward_top_n),
        )
        strategies = generate_parameter_grid(optimization=optimization)
        rows = optimize_strategies_from_frames(frames, strategies, optimization)
        write_rows_dynamic(rows, Path(args.output))
        if args.recommendation_output:
            recommendation_path = Path(args.recommendation_output)
            write_recommendation(rows, recommendation_path)
            if args.promote_if_eligible:
                try:
                    item = promote_recommendation_to_registry(
                        recommendation_path,
                        Path(args.strategies),
                        strategy_id=args.promoted_strategy_id,
                    )
                    print(f"纸面策略已晋级: {item['id']}")
                except ValueError as exc:
                    print(f"纸面策略未晋级: {exc}")
        print(render_optimization(rows))
    else:
        strategies = load_strategies(Path(args.strategies))
        rows = compare_strategies_from_frames(frames, strategies)
        sorted_rows = sort_strategy_rows(rows)
        write_comparison(sorted_rows, Path(args.output))
        print(render_comparison(sorted_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
