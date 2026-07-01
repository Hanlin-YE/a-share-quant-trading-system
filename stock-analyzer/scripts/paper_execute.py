#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate paper-trading execution decisions from the active paper strategy."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import analyze
import paper_account
import strategy_lab


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
STRATEGY_PATH = JOURNAL_DIR / "strategies.json"
STATE_ORDER = {
    "WATCH": 0,
    "CANDIDATE": 1,
    "TRADE_PLAN": 2,
    "EXECUTED": 3,
}


def load_active_strategy(path: Path = STRATEGY_PATH) -> strategy_lab.Strategy:
    payload = json.loads(path.read_text(encoding="utf-8"))
    active_id = payload.get("active_paper_strategy_id") or "score-standard-v1"
    for item in payload.get("strategies", []):
        if item.get("id") == active_id:
            return strategy_lab.Strategy(
                id=item["id"],
                name=item.get("name", item["id"]),
                description=item.get("description", ""),
                config=strategy_lab.backtest.BacktestConfig(
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
            )
    raise ValueError(f"active paper strategy not found: {active_id}")


def load_strategy_payload(path: Path = STRATEGY_PATH) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def active_strategy_item(payload: Dict[str, object]) -> Dict[str, object]:
    active_id = payload.get("active_paper_strategy_id") or "score-standard-v1"
    for item in payload.get("strategies", []):
        if item.get("id") == active_id:
            return item
    raise ValueError(f"active paper strategy not found: {active_id}")


def state_rank(state: str) -> int:
    return STATE_ORDER.get(state.upper(), 0)


def floor_partial_exit(quantity: int, pct: float, lot_size: int = 100) -> int:
    if quantity <= 0 or pct <= 0:
        return 0
    if quantity < lot_size:
        return quantity
    raw = quantity * pct
    reduced = floor_to_lot(raw, lot_size)
    if reduced <= 0:
        reduced = lot_size
    remaining = quantity - reduced
    if 0 < remaining < lot_size:
        return quantity
    return min(reduced, quantity)


def account_equity_snapshot(config: paper_account.AccountConfig) -> Dict[str, float]:
    last = paper_account.latest_equity_row()
    if last:
        return {
            "equity": paper_account.as_float(last.get("end_equity"), config.initial_cash),
            "cash": paper_account.as_float(last.get("cash"), config.initial_cash),
            "stock_value": paper_account.as_float(last.get("stock_value"), 0.0),
            "exposure_pct": paper_account.as_float(last.get("total_exposure_pct"), 0.0),
        }
    return {
        "equity": config.initial_cash,
        "cash": config.initial_cash,
        "stock_value": 0.0,
        "exposure_pct": 0.0,
    }


def floor_to_lot(shares: float, lot_size: int = 100) -> int:
    if lot_size <= 1:
        return max(0, int(math.floor(shares)))
    return max(0, int(math.floor(shares / lot_size) * lot_size))


def score_data_result(data: analyze.DataResult) -> Dict[str, object]:
    """Score a symbol using T-1 history only; return T's open as exec price.

    与 backtest.py 对齐：信号只用 T-1 及之前数据（frame.iloc[:-1]），成交价用
    T 日开盘价（frame.iloc[-1]["open"]），避免当日收盘价同时做信号+成交的前视偏差。
    """
    full = data.frame
    # 信号帧：剔除最后一根 bar（T 日），只用 T-1 及之前的数据评分
    if len(full) > 1:
        signal_frame = full.iloc[:-1]
    else:
        signal_frame = full
    scored = analyze.add_indicators(signal_frame)
    ta_score, signals = analyze.technical_score(scored)
    max_drawdown = analyze.calc_max_drawdown(scored["close"].tail(120))
    risk = analyze.risk_score(scored, max_drawdown)
    final_score, suggestion = analyze.final_decision(ta_score, analyze.MLResult(False), risk)
    signal_last = scored.iloc[-1]
    latest = full.iloc[-1]
    exec_price = float(latest["open"]) if "open" in full.columns else float(latest["close"])
    return {
        "stock_code": data.stock_code,
        "stock_name": data.stock_name,
        "source": data.source,
        "source_note": data.source_note,
        "signal_date": str(signal_last["date"].date()),
        "latest_date": str(latest["date"].date()),
        "close": float(latest["close"]),
        "signal_close": float(signal_last["close"]),
        "exec_price": exec_price,
        "final_score": float(final_score),
        "ta_score": float(ta_score),
        "risk_score": float(risk),
        "max_drawdown_pct": float(max_drawdown),
        "suggestion": suggestion,
        "signals": signals[:5],
    }


def preflight_decision(
    *,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    trade_date: Optional[str],
    cash: float,
) -> Dict[str, object]:
    checks: Dict[str, object] = {
        "actionable": True,
        "blocking_reasons": [],
        "sellable_quantity": None,
        "cash_required": None,
    }
    reasons: List[str] = []
    if not side or quantity <= 0:
        checks["actionable"] = False
        checks["blocking_reasons"] = ["无可执行买卖数量"]
        return checks
    if side == "BUY":
        gross = quantity * price
        checks["cash_required"] = round(gross, 2)
        if quantity % paper_account.LOT_SIZE != 0:
            reasons.append(f"BUY 数量必须为 {paper_account.LOT_SIZE} 股整数倍")
        if gross > cash:
            reasons.append(f"现金不足: 需要 {gross:.2f}，可用 {cash:.2f}")
    elif side == "SELL":
        if trade_date:
            sellable = paper_account.available_to_sell(symbol, trade_date)
            checks["sellable_quantity"] = sellable
            if quantity > sellable:
                reasons.append(f"T+1 可卖不足: 计划 {quantity}，可卖 {sellable}")
        current_qty = paper_account.as_int((paper_account.active_positions().get(symbol) or {}).get("quantity"))
        remaining = current_qty - quantity if current_qty else 0
        if remaining > 0 and quantity % paper_account.LOT_SIZE != 0:
            reasons.append(f"SELL 未清仓时必须为 {paper_account.LOT_SIZE} 股整数倍")
        if 0 < remaining < paper_account.LOT_SIZE:
            reasons.append(f"SELL 会制造 {remaining} 股零股，需整笔清仓")
    if reasons:
        checks["actionable"] = False
        checks["blocking_reasons"] = reasons
    return checks


def decide_for_symbol(
    *,
    symbol: str,
    data: analyze.DataResult,
    strategy: strategy_lab.Strategy,
    config: paper_account.AccountConfig,
    account: Dict[str, float],
    positions: Dict[str, Dict[str, object]],
    symbol_state: str = "WATCH",
    allow_direct_trade_from_watch: bool = False,
    min_trade_state: str = "TRADE_PLAN",
    partial_exit_pct: float = 0.33,
    min_actionable_history: int = 180,
) -> Dict[str, object]:
    score = score_data_result(data)
    current_position = positions.get(data.stock_code)
    current_qty = paper_account.as_int(current_position.get("quantity") if current_position else 0)
    # 估值用 T 日收盘价（mark-to-market）；成交用 T 日开盘价（exec_price）
    current_value = current_qty * float(score["close"])
    exec_price = float(score.get("exec_price", score["close"]))
    equity = max(float(account["equity"]), 0.01)
    cash = max(float(account["cash"]), 0.0)
    target_weight = min(
        strategy.config.max_position_pct,
        max(0.0, strategy.config.max_total_exposure_pct - float(account.get("exposure_pct", 0.0))),
    )
    target_value = equity * target_weight / 100.0

    history_len = len(data.frame)
    action = "HOLD"
    side = ""
    quantity = 0
    reason = "未触发入场或退出条件"
    can_trade_from_state = (
        allow_direct_trade_from_watch
        or state_rank(symbol_state) >= state_rank(min_trade_state)
        or current_qty > 0
    )
    if history_len < min_actionable_history:
        action = "WATCH"
        reason = f"样本不足 {history_len} < {min_actionable_history}，只能观察，不能生成交易动作"
    elif not can_trade_from_state:
        action = "WATCH"
        reason = f"当前状态 {symbol_state} 未达到 {min_trade_state}，禁止从观察池直接交易"
    elif current_qty > 0 and float(score["final_score"]) < strategy.config.exit_score:
        action = "REDUCE"
        side = "SELL"
        quantity = floor_partial_exit(current_qty, partial_exit_pct)
        if quantity >= current_qty:
            action = "SELL"
        reason = (
            f"评分 {score['final_score']:.1f} 低于退出阈值 {strategy.config.exit_score:.1f}，"
            f"按分层减仓 {partial_exit_pct:.0%} 处理"
        )
    elif current_qty <= 0 and float(score["final_score"]) >= strategy.config.entry_score:
        affordable_value = min(target_value, cash)
        quantity = floor_to_lot(affordable_value / exec_price)
        if quantity > 0:
            action = "BUY"
            side = "BUY"
            reason = f"评分 {score['final_score']:.1f} 达到入场阈值 {strategy.config.entry_score:.1f}"
        else:
            reason = "达到入场阈值但现金或目标仓位不足一手"
    elif current_qty > 0:
        reason = "已有持仓且未跌破退出阈值，继续持有"

    preflight = preflight_decision(
        symbol=data.stock_code,
        side=side,
        quantity=quantity,
        price=exec_price,
        trade_date=datetime.now().strftime("%Y-%m-%d"),
        cash=cash,
    )

    return {
        "symbol": data.stock_code,
        "name": data.stock_name,
        "action": action,
        "side": side,
        "quantity": quantity,
        "price": round(exec_price, 4),
        "reason": reason,
        "current_quantity": current_qty,
        "current_value": round(current_value, 2),
        "target_weight_pct": round(target_weight, 4),
        "strategy_id": strategy.id,
        "state": symbol_state,
        "min_trade_state": min_trade_state,
        "history_len": history_len,
        "preflight": preflight,
        "score": score,
    }


def build_decision_package(
    stocks: List[str],
    days: int = 260,
    source: str = "premium",
    strategy_path: Path = STRATEGY_PATH,
    require_cache_health: bool = False,
    cache_min_rows: int = 80,
    cache_max_age_hours: int = 36,
    symbol_states: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    strategy_payload = load_strategy_payload(strategy_path)
    strategy_item = active_strategy_item(strategy_payload)
    strategy = load_active_strategy(strategy_path)
    state_machine = strategy_payload.get("state_machine") if isinstance(strategy_payload.get("state_machine"), dict) else {}
    allow_direct_trade_from_watch = bool(state_machine.get("allow_direct_trade_from_watch", False))
    min_trade_state = str(state_machine.get("min_trade_state") or "TRADE_PLAN")
    partial_exit_pct = float(strategy_item.get("partial_exit_pct", 0.33))
    min_actionable_history = int(strategy_item.get("min_actionable_history", 180))
    config = paper_account.load_account_config()
    account = account_equity_snapshot(config)
    positions = paper_account.active_positions()
    if require_cache_health:
        cache_health = analyze.inspect_market_cache(
            stocks,
            days=days,
            min_rows=cache_min_rows,
            max_age_hours=cache_max_age_hours,
        )
        if not cache_health.get("ok"):
            return {
                "ok": False,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "mode": "paper",
                "strategy": {
                    "id": strategy.id,
                    "name": strategy.name,
                    "entry_score": strategy.config.entry_score,
                    "exit_score": strategy.config.exit_score,
                    "max_position_pct": strategy.config.max_position_pct,
                    "max_total_exposure_pct": strategy.config.max_total_exposure_pct,
                    "min_trade_state": min_trade_state,
                    "min_actionable_history": min_actionable_history,
                },
                "account": account,
                "decisions": [],
                "failures": [{"symbol": "CACHE_HEALTH", "error": analyze.render_market_cache_health(cache_health)}],
                "risk_note": "缓存健康失败，禁止生成纸面交易动作；仅用于训练/研究。",
            }
    decisions: List[Dict[str, object]] = []
    failures: List[Dict[str, str]] = []

    for stock in stocks:
        stock_code = analyze.normalize_stock_code(stock)
        analyze.reset_fetch_errors()
        data = analyze.get_stock_data(stock_code, days, source)
        if not data or data.frame.empty:
            failures.append(
                {
                    "symbol": stock_code,
                    "error": analyze.fetch_error_summary_by_stage(),
                }
            )
            continue
        decisions.append(
            decide_for_symbol(
                symbol=stock_code,
                data=data,
                strategy=strategy,
                config=config,
                account=account,
                positions=positions,
                symbol_state=(symbol_states or {}).get(data.stock_code, "WATCH"),
                allow_direct_trade_from_watch=allow_direct_trade_from_watch,
                min_trade_state=min_trade_state,
                partial_exit_pct=partial_exit_pct,
                min_actionable_history=min_actionable_history,
            )
        )

    return {
        "ok": bool(decisions),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "paper",
        "strategy": {
            "id": strategy.id,
            "name": strategy.name,
            "entry_score": strategy.config.entry_score,
            "exit_score": strategy.config.exit_score,
            "max_position_pct": strategy.config.max_position_pct,
            "max_total_exposure_pct": strategy.config.max_total_exposure_pct,
            "min_trade_state": min_trade_state,
            "min_actionable_history": min_actionable_history,
        },
        "account": account,
        "decisions": decisions,
        "failures": failures,
        "risk_note": "仅用于训练/研究和纸面交易，不构成投资建议或真实交易指令。",
    }


def execute_decisions(package: Dict[str, object], trade_date: str, trade_time: str, dry_run: bool = True) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for decision in package.get("decisions", []):
        if decision.get("action") not in {"BUY", "SELL", "REDUCE"}:
            continue
        preflight = decision.get("preflight") if isinstance(decision.get("preflight"), dict) else {}
        if preflight and not preflight.get("actionable", True):
            rows.append(
                {
                    "dry_run": dry_run,
                    "blocked": True,
                    "blocking_reasons": preflight.get("blocking_reasons", []),
                    **decision,
                }
            )
            continue
        if dry_run:
            rows.append({"dry_run": True, **decision})
            continue
        rows.append(
            paper_account.record_trade(
                symbol=str(decision["symbol"]),
                name=str(decision.get("name", "")),
                side=str(decision["side"]),
                quantity=int(decision["quantity"]),
                price=float(decision["price"]),
                trade_date=trade_date,
                trade_time=trade_time,
                reason=str(decision["reason"]),
                strategy_tag=str(decision["strategy_id"]),
                notes="paper_execute 自动纸面执行；非真实交易",
            )
        )
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股纸面策略执行决策")
    parser.add_argument("--stocks", required=True, help="股票代码列表，逗号分隔")
    parser.add_argument("--days", type=int, default=260)
    parser.add_argument("--source", default="premium", choices=["premium", "push", "pull", "auto", "tencent", "eastmoney", "tushare", "stooq"])
    parser.add_argument("--strategy-path", default=str(STRATEGY_PATH))
    parser.add_argument("--require-cache-health", action="store_true", help="生成决策前要求本地行情缓存健康")
    parser.add_argument("--cache-max-age-hours", type=int, default=36)
    parser.add_argument("--cache-min-rows", type=int, default=80)
    parser.add_argument("--execute", action="store_true", help="写入纸面成交；默认只生成决策包")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--time", default=datetime.now().strftime("%H:%M"))
    args = parser.parse_args(argv)

    package = build_decision_package(
        analyze.split_stock_list(args.stocks),
        days=max(80, min(args.days, 1200)),
        source=args.source,
        strategy_path=Path(args.strategy_path),
        require_cache_health=args.require_cache_health,
        cache_min_rows=max(1, args.cache_min_rows),
        cache_max_age_hours=max(1, args.cache_max_age_hours),
    )
    package["executed_orders"] = execute_decisions(
        package,
        trade_date=args.date,
        trade_time=args.time,
        dry_run=not args.execute,
    )
    print(json.dumps(package, ensure_ascii=False, indent=2))
    return 0 if package.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
