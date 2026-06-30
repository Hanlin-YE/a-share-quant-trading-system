#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio backtesting for the local A-share analyzer.

The engine trades at the next session's open using signals computed from the
previous session only. That keeps the first version intentionally boring and
auditable: no same-day close leakage, explicit costs, and a reproducible equity
curve that can later be compared with paper-trading logs.

For A-share common stocks this is a T+1-compatible daily rebalancing model:
shares bought at a session open can only be reduced from the next session
onward because the engine runs at most one rebalance per symbol per session.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

import analyze


ScoreFn = Callable[[str, pd.DataFrame], Tuple[float, str]]


@dataclass
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    entry_score: float = 58.0
    exit_score: float = 45.0
    max_position_pct: float = 20.0
    max_total_exposure_pct: float = 80.0
    fee_bps: float = 3.0
    min_commission: float = 5.0
    tax_bps: float = 5.0
    transfer_bps: float = 0.1
    slippage_bps: float = 5.0
    min_history: int = 80
    lot_size: int = 100


@dataclass
class BacktestResult:
    metrics: Dict[str, float]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    notes: List[str]


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    clean, _ = analyze.validate_ohlcv_frame(frame)
    return clean.sort_values("date").reset_index(drop=True)


def score_symbol_history(symbol: str, history: pd.DataFrame) -> Tuple[float, str]:
    scored = analyze.add_indicators(history)
    ta_score, _ = analyze.technical_score(scored)
    max_drawdown = analyze.calc_max_drawdown(scored["close"].tail(120))
    risk = analyze.risk_score(scored, max_drawdown)
    final_score, suggestion = analyze.final_decision(ta_score, analyze.MLResult(False), risk)
    return float(final_score), suggestion


def floor_to_lot(shares: float, lot_size: int) -> int:
    if lot_size <= 1:
        return max(0, int(math.floor(shares)))
    return max(0, int(math.floor(shares / lot_size) * lot_size))


def trade_cost_breakdown(
    amount: float,
    side: str,
    fee_bps: float,
    min_commission: float,
    tax_bps: float = 0.0,
    transfer_bps: float = 0.0,
) -> Dict[str, float]:
    gross = abs(amount)
    commission = max(gross * fee_bps / 10_000.0, min_commission) if gross > 0 else 0.0
    stamp_tax = gross * tax_bps / 10_000.0 if side.upper() == "SELL" else 0.0
    transfer_fee = gross * transfer_bps / 10_000.0
    total = commission + stamp_tax + transfer_fee
    return {
        "commission": commission,
        "stamp_tax": stamp_tax,
        "transfer_fee": transfer_fee,
        "total_cost": total,
    }


def common_trade_dates(frames: Dict[str, pd.DataFrame]) -> List[pd.Timestamp]:
    date_sets = [set(pd.to_datetime(frame["date"])) for frame in frames.values()]
    if not date_sets:
        return []
    return sorted(set.intersection(*date_sets))


def run_backtest_from_frames(
    frames: Dict[str, pd.DataFrame],
    config: Optional[BacktestConfig] = None,
    score_func: ScoreFn = score_symbol_history,
) -> BacktestResult:
    cfg = config or BacktestConfig()
    normalized = {symbol: normalize_frame(frame) for symbol, frame in frames.items()}
    normalized = {symbol: frame for symbol, frame in normalized.items() if len(frame) >= cfg.min_history + 2}
    notes: List[str] = []
    if len(normalized) != len(frames):
        skipped = sorted(set(frames) - set(normalized))
        notes.append(f"样本不足剔除: {', '.join(skipped)}")
    if not normalized:
        raise ValueError("没有足够样本可回测。")

    dates = common_trade_dates(normalized)
    if len(dates) < cfg.min_history + 2:
        raise ValueError("共同交易日不足，无法构建组合回测。")

    indexes = {
        symbol: {pd.Timestamp(value): idx for idx, value in enumerate(frame["date"])}
        for symbol, frame in normalized.items()
    }
    holdings: Dict[str, int] = {symbol: 0 for symbol in normalized}
    cash = float(cfg.initial_cash)
    equity_high = float(cfg.initial_cash)
    equity_rows: List[Dict[str, object]] = []
    trade_rows: List[Dict[str, object]] = []

    for current_date in dates[1:]:
        previous_date = dates[dates.index(current_date) - 1]
        if any(indexes[symbol][previous_date] + 1 < cfg.min_history for symbol in normalized):
            continue

        signals: Dict[str, Tuple[float, str]] = {}
        for symbol, frame in normalized.items():
            previous_pos = indexes[symbol][previous_date]
            history = frame.iloc[: previous_pos + 1].copy()
            signals[symbol] = score_func(symbol, history)

        open_prices = {
            symbol: float(normalized[symbol].iloc[indexes[symbol][current_date]]["open"])
            for symbol in normalized
        }
        close_prices = {
            symbol: float(normalized[symbol].iloc[indexes[symbol][current_date]]["close"])
            for symbol in normalized
        }
        open_equity = cash + sum(holdings[symbol] * open_prices[symbol] for symbol in normalized)

        keep = {symbol for symbol, shares in holdings.items() if shares > 0 and signals[symbol][0] >= cfg.exit_score}
        enter = {symbol for symbol, (score, _) in signals.items() if score >= cfg.entry_score}
        target_symbols = sorted(keep | enter, key=lambda item: signals[item][0], reverse=True)
        if target_symbols:
            target_weight = min(
                cfg.max_position_pct / 100.0,
                cfg.max_total_exposure_pct / 100.0 / len(target_symbols),
            )
        else:
            target_weight = 0.0

        target_shares: Dict[str, int] = {}
        for symbol in normalized:
            if symbol not in target_symbols:
                target_shares[symbol] = 0
                continue
            buy_price = open_prices[symbol] * (1 + cfg.slippage_bps / 10_000.0)
            desired_value = open_equity * target_weight
            target_shares[symbol] = floor_to_lot(desired_value / buy_price, cfg.lot_size)

        for symbol in normalized:
            delta = target_shares[symbol] - holdings[symbol]
            if delta >= 0:
                continue
            shares_to_sell = abs(delta)
            price = open_prices[symbol] * (1 - cfg.slippage_bps / 10_000.0)
            gross = shares_to_sell * price
            costs = trade_cost_breakdown(
                gross,
                "SELL",
                cfg.fee_bps,
                cfg.min_commission,
                cfg.tax_bps,
                cfg.transfer_bps,
            )
            cost = costs["total_cost"]
            cash += gross - cost
            holdings[symbol] -= shares_to_sell
            trade_rows.append(
                {
                    "date": current_date.date().isoformat(),
                    "symbol": symbol,
                    "action": "SELL",
                    "shares": shares_to_sell,
                    "price": round(price, 4),
                    "gross": round(gross, 2),
                    "commission": round(costs["commission"], 2),
                    "stamp_tax": round(costs["stamp_tax"], 2),
                    "transfer_fee": round(costs["transfer_fee"], 2),
                    "cost": round(cost, 2),
                    "score": round(signals[symbol][0], 2),
                    "reason": signals[symbol][1],
                }
            )

        for symbol in target_symbols:
            delta = target_shares[symbol] - holdings[symbol]
            if delta <= 0:
                continue
            price = open_prices[symbol] * (1 + cfg.slippage_bps / 10_000.0)
            affordable = floor_to_lot(cash / (price * (1 + (cfg.fee_bps + cfg.transfer_bps) / 10_000.0)), cfg.lot_size)
            shares_to_buy = min(delta, affordable)
            if shares_to_buy <= 0:
                continue
            gross = shares_to_buy * price
            costs = trade_cost_breakdown(
                gross,
                "BUY",
                cfg.fee_bps,
                cfg.min_commission,
                cfg.tax_bps,
                cfg.transfer_bps,
            )
            cost = costs["total_cost"]
            cash -= gross + cost
            holdings[symbol] += shares_to_buy
            trade_rows.append(
                {
                    "date": current_date.date().isoformat(),
                    "symbol": symbol,
                    "action": "BUY",
                    "shares": shares_to_buy,
                    "price": round(price, 4),
                    "gross": round(gross, 2),
                    "commission": round(costs["commission"], 2),
                    "stamp_tax": round(costs["stamp_tax"], 2),
                    "transfer_fee": round(costs["transfer_fee"], 2),
                    "cost": round(cost, 2),
                    "score": round(signals[symbol][0], 2),
                    "reason": signals[symbol][1],
                }
            )

        stock_value = sum(holdings[symbol] * close_prices[symbol] for symbol in normalized)
        end_equity = cash + stock_value
        equity_high = max(equity_high, end_equity)
        drawdown = end_equity / equity_high - 1 if equity_high else 0.0
        previous_equity = equity_rows[-1]["end_equity"] if equity_rows else cfg.initial_cash
        daily_return = end_equity / float(previous_equity) - 1 if previous_equity else 0.0
        exposure = stock_value / end_equity if end_equity else 0.0

        equity_rows.append(
            {
                "date": current_date.date().isoformat(),
                "cash": round(cash, 2),
                "stock_value": round(stock_value, 2),
                "end_equity": round(end_equity, 2),
                "daily_return_pct": round(daily_return * 100, 4),
                "exposure_pct": round(exposure * 100, 2),
                "drawdown_pct": round(drawdown * 100, 4),
                "held_symbols": ",".join(symbol for symbol, shares in holdings.items() if shares > 0),
            }
        )

    if not equity_rows:
        raise ValueError("回测期内没有可执行交易日。")

    equity_curve = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    final_equity = float(equity_curve.iloc[-1]["end_equity"])
    total_return = final_equity / cfg.initial_cash - 1
    max_drawdown = abs(float(equity_curve["drawdown_pct"].min()))
    daily_returns = equity_curve["daily_return_pct"].astype(float) / 100.0
    win_rate = float((daily_returns > 0).mean() * 100)
    years = max(len(equity_curve) / 252.0, 1 / 252.0)
    annualized = (final_equity / cfg.initial_cash) ** (1 / years) - 1 if final_equity > 0 else -1.0
    volatility = float(daily_returns.std(ddof=0) * math.sqrt(252)) if len(daily_returns) > 1 else 0.0
    sharpe = float((daily_returns.mean() * 252) / volatility) if volatility > 0 else 0.0

    latest_positions = []
    latest_close = {
        symbol: float(normalized[symbol].iloc[indexes[symbol][dates[-1]]]["close"])
        for symbol in normalized
    }
    for symbol, shares in holdings.items():
        if shares <= 0:
            continue
        value = shares * latest_close[symbol]
        latest_positions.append(
            {
                "symbol": symbol,
                "shares": shares,
                "last_close": round(latest_close[symbol], 4),
                "market_value": round(value, 2),
                "weight_pct": round(value / final_equity * 100, 2) if final_equity else 0.0,
            }
        )

    metrics = {
        "initial_cash": round(cfg.initial_cash, 2),
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return * 100, 4),
        "annualized_return_pct": round(annualized * 100, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "daily_win_rate_pct": round(win_rate, 2),
        "volatility_pct": round(volatility * 100, 4),
        "sharpe": round(sharpe, 4),
        "trade_count": float(len(trades)),
        "avg_exposure_pct": round(float(equity_curve["exposure_pct"].mean()), 2),
    }
    return BacktestResult(metrics, equity_curve, trades, pd.DataFrame(latest_positions), notes)


def load_market_frames(stocks: List[str], days: int, source: str) -> Dict[str, pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}
    failures: List[str] = []
    for stock in stocks:
        analyze.reset_fetch_errors()
        result = analyze.get_stock_data(stock, days, source)
        if result is None:
            failures.append(f"{stock}: {analyze.fetch_error_summary_by_stage()}")
            continue
        frames[result.stock_code] = result.frame
    if failures:
        print("取数失败剔除:")
        for item in failures:
            print(f"- {item}")
    return frames


def render_result(result: BacktestResult) -> str:
    lines = [
        "A股组合回测报告",
        "=" * 40,
        f"期末权益: {result.metrics['final_equity']:.2f}",
        f"总收益率: {result.metrics['total_return_pct']:.4f}%",
        f"年化收益率: {result.metrics['annualized_return_pct']:.4f}%",
        f"最大回撤: {result.metrics['max_drawdown_pct']:.4f}%",
        f"日胜率: {result.metrics['daily_win_rate_pct']:.2f}%",
        f"年化波动率: {result.metrics['volatility_pct']:.4f}%",
        f"Sharpe: {result.metrics['sharpe']:.4f}",
        f"交易次数: {int(result.metrics['trade_count'])}",
        f"平均仓位: {result.metrics['avg_exposure_pct']:.2f}%",
        "",
        "当前持仓",
    ]
    if result.positions.empty:
        lines.append("- 空仓")
    else:
        for row in result.positions.itertuples(index=False):
            lines.append(
                f"- {row.symbol}: {row.shares}股，市值{row.market_value:.2f}，权重{row.weight_pct:.2f}%"
            )
    if result.notes:
        lines.extend(["", "备注"])
        lines.extend(f"- {note}" for note in result.notes)
    lines.extend(
        [
            "",
            "规则说明: 信号使用前一交易日收盘后可见数据，下一交易日开盘成交；按A股T+1日频调仓口径处理，不做日内高频或当日买入当日卖出；已计入佣金、印花税和滑点。",
            "风险提示: 本报告只用于训练/研究，不构成投资建议或自动交易信号。",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股组合回测")
    parser.add_argument("--stocks", required=True, help="股票代码列表，逗号分隔")
    parser.add_argument("--days", type=int, default=360, help="回测历史天数")
    parser.add_argument("--source", default="auto", choices=["premium", "push", "pull", "tushare", "auto", "tencent", "eastmoney", "stooq"])
    parser.add_argument("--initial-cash", type=float, default=1_000_000)
    parser.add_argument("--entry-score", type=float, default=58.0)
    parser.add_argument("--exit-score", type=float, default=45.0)
    parser.add_argument("--max-position-pct", type=float, default=20.0)
    parser.add_argument("--max-total-exposure-pct", type=float, default=80.0)
    parser.add_argument("--fee-bps", type=float, default=3.0)
    parser.add_argument("--min-commission", type=float, default=5.0)
    parser.add_argument("--tax-bps", type=float, default=5.0)
    parser.add_argument("--transfer-bps", type=float, default=0.1)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--output-dir", type=str, default="", help="可选：输出 equity_curve.csv、trades.csv、positions.csv")
    args = parser.parse_args(argv)

    stocks = analyze.split_stock_list(args.stocks)
    frames = load_market_frames(stocks, args.days, args.source)
    config = BacktestConfig(
        initial_cash=args.initial_cash,
        entry_score=args.entry_score,
        exit_score=args.exit_score,
        max_position_pct=args.max_position_pct,
        max_total_exposure_pct=args.max_total_exposure_pct,
        fee_bps=args.fee_bps,
        min_commission=args.min_commission,
        tax_bps=args.tax_bps,
        transfer_bps=args.transfer_bps,
        slippage_bps=args.slippage_bps,
    )
    result = run_backtest_from_frames(frames, config)
    if args.output_dir:
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        result.equity_curve.to_csv(output / "equity_curve.csv", index=False)
        result.trades.to_csv(output / "trades.csv", index=False)
        result.positions.to_csv(output / "positions.csv", index=False)
    print(render_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
