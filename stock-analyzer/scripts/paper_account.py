#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper account ledger for daily A-share trading practice."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from backtest import trade_cost_breakdown


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
LEDGER_DIR = JOURNAL_DIR / "ledger"
ACCOUNT_PATH = JOURNAL_DIR / "account.json"
PORTFOLIO_LEDGER_PATH = JOURNAL_DIR / "portfolio_ledger.csv"
WORKBOOK_PATH = JOURNAL_DIR / "量化交易AI实盘_纸面交易记录.xlsx"
SYNC_WORKBOOK_SCRIPT = ROOT / "tools" / "sync_portfolio_workbook.py"
ORDERS_PATH = LEDGER_DIR / "orders.csv"
POSITIONS_PATH = LEDGER_DIR / "positions.csv"
EQUITY_PATH = LEDGER_DIR / "equity_curve.csv"

PORTFOLIO_LEDGER_FIELDS = [
    "date",
    "section",
    "row_type",
    "time",
    "symbol",
    "name",
    "side",
    "action",
    "quantity",
    "price",
    "avg_cost",
    "gross_amount",
    "commission",
    "stamp_tax",
    "transfer_fee",
    "total_cost",
    "net_amount",
    "cash",
    "stock_value",
    "market_value",
    "start_equity",
    "end_equity",
    "daily_pnl",
    "daily_return_pct",
    "realized_pnl",
    "unrealized_pnl",
    "unrealized_pnl_pct",
    "total_exposure_pct",
    "weight_pct",
    "max_drawdown_pct",
    "risk_state",
    "strategy_tag",
    "strategy_id",
    "score_profile",
    "factor_weights",
    "strategy_status",
    "reason",
    "thesis",
    "review_date",
    "status",
    "notes",
]

ORDER_FIELDS = [
    "date",
    "time",
    "symbol",
    "name",
    "action",
    "side",
    "quantity",
    "price",
    "gross_amount",
    "commission",
    "stamp_tax",
    "transfer_fee",
    "total_cost",
    "net_amount",
    "reason",
    "strategy_tag",
    "status",
    "notes",
]
POSITION_FIELDS = [
    "date",
    "symbol",
    "name",
    "side",
    "quantity",
    "avg_cost",
    "last_price",
    "market_value",
    "unrealized_pnl",
    "unrealized_pnl_pct",
    "weight_pct",
    "thesis",
    "status",
    "review_date",
    "notes",
]
EQUITY_FIELDS = [
    "date",
    "start_equity",
    "end_equity",
    "daily_pnl",
    "daily_return_pct",
    "cash",
    "stock_value",
    "total_exposure_pct",
    "max_drawdown_pct",
    "risk_state",
    "notes",
]

LOT_SIZE = 100


@dataclass
class AccountConfig:
    initial_cash: float
    fee_bps: float
    min_commission: float
    tax_bps: float
    transfer_bps: float
    slippage_bps: float
    max_position_pct: float
    max_total_exposure_pct: float
    daily_loss_stop_pct: float
    max_drawdown_alert_pct: float
    max_drawdown_stop_pct: float


def ensure_ledger_files() -> None:
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    ensure_csv_header(PORTFOLIO_LEDGER_PATH, PORTFOLIO_LEDGER_FIELDS)
    ensure_csv_header(ORDERS_PATH, ORDER_FIELDS)
    ensure_csv_header(POSITIONS_PATH, POSITION_FIELDS)
    ensure_csv_header(EQUITY_PATH, EQUITY_FIELDS)


def ensure_csv_header(path: Path, fields: List[str]) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fields).writeheader()


def load_account_config(path: Path = ACCOUNT_PATH) -> AccountConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    limits = payload.get("risk_limits", {})
    return AccountConfig(
        initial_cash=float(payload.get("initial_cash", 1_000_000.0)),
        fee_bps=float(payload.get("fee_bps", 3.0)),
        min_commission=float(payload.get("min_commission", 5.0)),
        tax_bps=float(payload.get("tax_bps", 5.0)),
        transfer_bps=float(payload.get("transfer_bps", 0.1)),
        slippage_bps=float(payload.get("slippage_bps", 5.0)),
        max_position_pct=float(limits.get("max_position_pct", 20.0)),
        max_total_exposure_pct=float(limits.get("max_total_exposure_pct", 80.0)),
        daily_loss_stop_pct=float(limits.get("daily_loss_stop_pct", 1.0)),
        max_drawdown_alert_pct=float(limits.get("max_drawdown_alert_pct", 5.0)),
        max_drawdown_stop_pct=float(limits.get("max_drawdown_stop_pct", 10.0)),
    )


def read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, fields: List[str], rows: List[Dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def append_row(path: Path, fields: List[str], row: Dict[str, object]) -> None:
    ensure_csv_header(path, fields)
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=fields).writerow({field: row.get(field, "") for field in fields})


def portfolio_rows() -> List[Dict[str, str]]:
    rows = read_rows(PORTFOLIO_LEDGER_PATH)
    has_account_rows = any(row.get("row_type") in {"TRADE", "POSITION", "DAY_SUMMARY"} for row in rows)
    if has_account_rows:
        return rows
    legacy_orders = read_rows(ORDERS_PATH)
    legacy_equity = read_rows(EQUITY_PATH)
    legacy_positions = read_rows(POSITIONS_PATH)
    if not (legacy_orders or legacy_equity or legacy_positions):
        return []
    migrated = migrate_legacy_rows(legacy_orders, legacy_positions, legacy_equity)
    feedback_rows = [row for row in rows if row.get("row_type") == "STRATEGY_FEEDBACK"]
    if feedback_rows:
        write_portfolio_rows(list(migrated) + feedback_rows)
        return read_rows(PORTFOLIO_LEDGER_PATH)
    return migrated


def migrate_legacy_rows(
    orders: List[Dict[str, str]],
    positions: List[Dict[str, str]],
    equity_rows: List[Dict[str, str]],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for order in orders:
        rows.append(
            {
                "date": order.get("date", ""),
                "section": f"{order.get('date', '')} 交易",
                "row_type": "TRADE",
                "time": order.get("time", ""),
                "symbol": order.get("symbol", ""),
                "name": order.get("name", ""),
                "side": order.get("side", ""),
                "action": order.get("action", ""),
                "quantity": order.get("quantity", ""),
                "price": order.get("price", ""),
                "gross_amount": order.get("gross_amount", ""),
                "commission": order.get("commission", ""),
                "stamp_tax": order.get("stamp_tax", ""),
                "transfer_fee": order.get("transfer_fee", ""),
                "total_cost": order.get("total_cost", ""),
                "net_amount": order.get("net_amount", ""),
                "strategy_tag": order.get("strategy_tag", ""),
                "strategy_id": order.get("strategy_tag", ""),
                "reason": order.get("reason", ""),
                "status": order.get("status", ""),
                "notes": order.get("notes", ""),
            }
        )
    for position in positions:
        rows.append(
            {
                "date": position.get("date", ""),
                "section": f"{position.get('date', '')} 持仓",
                "row_type": "POSITION",
                "symbol": position.get("symbol", ""),
                "name": position.get("name", ""),
                "side": position.get("side", ""),
                "quantity": position.get("quantity", ""),
                "avg_cost": position.get("avg_cost", ""),
                "price": position.get("last_price", ""),
                "market_value": position.get("market_value", ""),
                "unrealized_pnl": position.get("unrealized_pnl", ""),
                "unrealized_pnl_pct": position.get("unrealized_pnl_pct", ""),
                "weight_pct": position.get("weight_pct", ""),
                "thesis": position.get("thesis", ""),
                "status": position.get("status", ""),
                "review_date": position.get("review_date", ""),
                "notes": position.get("notes", ""),
            }
        )
    for equity in equity_rows:
        rows.append(
            {
                "date": equity.get("date", ""),
                "section": f"{equity.get('date', '')} 组合汇总",
                "row_type": "DAY_SUMMARY",
                "start_equity": equity.get("start_equity", ""),
                "end_equity": equity.get("end_equity", ""),
                "daily_pnl": equity.get("daily_pnl", ""),
                "daily_return_pct": equity.get("daily_return_pct", ""),
                "cash": equity.get("cash", ""),
                "stock_value": equity.get("stock_value", ""),
                "total_exposure_pct": equity.get("total_exposure_pct", ""),
                "max_drawdown_pct": equity.get("max_drawdown_pct", ""),
                "risk_state": equity.get("risk_state", ""),
                "notes": equity.get("notes", ""),
            }
        )
    write_portfolio_rows(rows)
    return read_rows(PORTFOLIO_LEDGER_PATH)


def write_portfolio_rows(rows: List[Dict[str, object]]) -> None:
    PORTFOLIO_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_rows(PORTFOLIO_LEDGER_PATH, PORTFOLIO_LEDGER_FIELDS, sort_portfolio_rows(rows))


def sort_portfolio_rows(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    order = {
        "TRADE": 0,
        "OPENING_POSITION": 1,
        "TARGET_PORTFOLIO": 2,
        "TRADE_PLAN": 3,
        "DAY_SUMMARY": 4,
        "BACKTEST": 5,
        "POSITION": 6,
        "INTRADAY_CHECK": 7,
        "STRATEGY_FEEDBACK": 8,
    }

    def key(row: Dict[str, object]) -> tuple:
        return (
            str(row.get("date", "")),
            order.get(str(row.get("row_type", "")), 99),
            str(row.get("symbol", "")),
            str(row.get("time", "")),
        )

    return sorted(rows, key=key)


def append_portfolio_row(row: Dict[str, object]) -> None:
    append_row(PORTFOLIO_LEDGER_PATH, PORTFOLIO_LEDGER_FIELDS, row)


def sync_workbook() -> None:
    if not PORTFOLIO_LEDGER_PATH.exists() or PORTFOLIO_LEDGER_PATH.stat().st_size == 0:
        return
    spec = importlib.util.spec_from_file_location("sync_portfolio_workbook", SYNC_WORKBOOK_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load workbook sync script: {SYNC_WORKBOOK_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.sync(PORTFOLIO_LEDGER_PATH, WORKBOOK_PATH)


def trades_from_portfolio() -> List[Dict[str, str]]:
    return [row for row in portfolio_rows() if row.get("row_type") == "TRADE"]


def positions_from_portfolio() -> List[Dict[str, str]]:
    summaries = [row for row in portfolio_rows() if row.get("row_type") == "DAY_SUMMARY"]
    latest_date = summaries[-1].get("date") if summaries else ""
    return [
        row
        for row in portfolio_rows()
        if row.get("row_type") == "POSITION" and (not latest_date or row.get("date") == latest_date)
    ]


def equity_from_portfolio() -> List[Dict[str, str]]:
    return [row for row in portfolio_rows() if row.get("row_type") == "DAY_SUMMARY"]


def latest_equity_row() -> Dict[str, str]:
    rows = equity_from_portfolio()
    return rows[-1] if rows else {}


def as_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: object, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def current_cash(config: AccountConfig) -> float:
    row = latest_equity_row()
    if row:
        return as_float(row.get("cash"), config.initial_cash)
    return config.initial_cash


def active_positions() -> Dict[str, Dict[str, object]]:
    positions = {}
    for row in positions_from_portfolio():
        qty = as_int(row.get("quantity"))
        if qty > 0:
            positions[str(row["symbol"])] = row
    return positions


def available_to_sell(symbol: str, trade_date: str) -> int:
    """A-share T+1 sellable shares: today's buys are not sellable."""
    available = 0
    for row in portfolio_rows():
        row_type = row.get("row_type")
        if row_type not in {"OPENING_POSITION", "TRADE"}:
            continue
        if str(row.get("symbol", "")) != symbol:
            continue
        row_date = str(row.get("date", ""))
        side = str(row.get("side", "")).upper()
        qty = as_int(row.get("quantity"))
        if row_type == "OPENING_POSITION":
            if row_date <= trade_date:
                available += qty
            continue
        if row_date < trade_date:
            available += qty if side == "BUY" else -qty
        elif row_date == trade_date and side == "SELL":
            available -= qty
    return max(0, available)


def current_position_quantity(symbol: str) -> int:
    position = active_positions().get(symbol)
    if not position:
        return 0
    return as_int(position.get("quantity"))


def validate_a_share_lot(symbol: str, side: str, quantity: int, trade_date: str) -> None:
    """Enforce A-share board-lot buys and avoid creating artificial odd lots."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if side == "BUY":
        if quantity % LOT_SIZE != 0:
            raise ValueError(f"A-share BUY quantity must be a multiple of {LOT_SIZE}")
        return

    sellable = available_to_sell(symbol, trade_date)
    if quantity > sellable:
        raise ValueError(
            f"T+1 sell violation: requested {quantity} shares of {symbol}, "
            f"but only {sellable} shares are sellable from prior holdings"
        )

    current_qty = current_position_quantity(symbol)
    if current_qty <= 0:
        current_qty = sellable
    remaining = current_qty - quantity
    if remaining < 0:
        raise ValueError(f"SELL quantity exceeds current position: {quantity} > {current_qty}")
    if remaining == 0:
        return
    if quantity % LOT_SIZE != 0:
        raise ValueError(
            f"A-share SELL quantity must be a multiple of {LOT_SIZE} unless closing the full position"
        )
    if remaining < LOT_SIZE:
        raise ValueError(
            f"A-share SELL would create an odd-lot remainder: {remaining} shares; close full position instead"
        )


def sync_compatibility_ledgers() -> None:
    orders = []
    for row in trades_from_portfolio():
        orders.append(
            {
                "date": row.get("date", ""),
                "time": row.get("time", ""),
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "action": row.get("action", ""),
                "side": row.get("side", ""),
                "quantity": row.get("quantity", ""),
                "price": row.get("price", ""),
                "gross_amount": row.get("gross_amount", ""),
                "commission": row.get("commission", ""),
                "stamp_tax": row.get("stamp_tax", ""),
                "transfer_fee": row.get("transfer_fee", ""),
                "total_cost": row.get("total_cost", ""),
                "net_amount": row.get("net_amount", ""),
                "reason": row.get("reason", ""),
                "strategy_tag": row.get("strategy_tag") or row.get("strategy_id", ""),
                "status": row.get("status", ""),
                "notes": row.get("notes", ""),
            }
        )
    write_rows(ORDERS_PATH, ORDER_FIELDS, orders)

    positions = []
    for row in positions_from_portfolio():
        positions.append(
            {
                "date": row.get("date", ""),
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "side": row.get("side", "LONG"),
                "quantity": row.get("quantity", ""),
                "avg_cost": row.get("avg_cost", ""),
                "last_price": row.get("price", ""),
                "market_value": row.get("market_value", ""),
                "unrealized_pnl": row.get("unrealized_pnl", ""),
                "unrealized_pnl_pct": row.get("unrealized_pnl_pct", ""),
                "weight_pct": row.get("weight_pct", ""),
                "thesis": row.get("thesis", ""),
                "status": row.get("status", ""),
                "review_date": row.get("review_date", ""),
                "notes": row.get("notes", ""),
            }
        )
    write_rows(POSITIONS_PATH, POSITION_FIELDS, positions)

    equity = []
    for row in equity_from_portfolio():
        equity.append(
            {
                "date": row.get("date", ""),
                "start_equity": row.get("start_equity", ""),
                "end_equity": row.get("end_equity", ""),
                "daily_pnl": row.get("daily_pnl", ""),
                "daily_return_pct": row.get("daily_return_pct", ""),
                "cash": row.get("cash", ""),
                "stock_value": row.get("stock_value", ""),
                "total_exposure_pct": row.get("total_exposure_pct", ""),
                "max_drawdown_pct": row.get("max_drawdown_pct", ""),
                "risk_state": row.get("risk_state", ""),
                "notes": row.get("notes", ""),
            }
        )
    write_rows(EQUITY_PATH, EQUITY_FIELDS, equity)


def record_trade(
    *,
    symbol: str,
    name: str,
    side: str,
    quantity: int,
    price: float,
    trade_date: str,
    trade_time: str,
    reason: str,
    strategy_tag: str,
    notes: str,
    config: Optional[AccountConfig] = None,
) -> Dict[str, object]:
    ensure_ledger_files()
    cfg = config or load_account_config()
    side = side.upper()
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    if quantity <= 0 or price <= 0:
        raise ValueError("quantity and price must be positive")
    validate_a_share_lot(symbol, side, quantity, trade_date)

    trade_price = price * (1 + cfg.slippage_bps / 10_000.0) if side == "BUY" else price * (1 - cfg.slippage_bps / 10_000.0)
    gross = quantity * trade_price
    costs = trade_cost_breakdown(
        gross,
        side,
        cfg.fee_bps,
        cfg.min_commission,
        cfg.tax_bps,
        cfg.transfer_bps,
    )
    net_amount = -(gross + costs["total_cost"]) if side == "BUY" else gross - costs["total_cost"]
    cash_after = current_cash(cfg) + net_amount
    if cash_after < -0.01:
        raise ValueError("cash would become negative")

    row = {
        "date": trade_date,
        "section": f"{trade_date} 交易",
        "row_type": "TRADE",
        "time": trade_time,
        "symbol": symbol,
        "name": name,
        "action": "买入" if side == "BUY" else "卖出",
        "side": side,
        "quantity": quantity,
        "price": round(trade_price, 4),
        "gross_amount": round(gross, 2),
        "commission": round(costs["commission"], 2),
        "stamp_tax": round(costs["stamp_tax"], 2),
        "transfer_fee": round(costs["transfer_fee"], 2),
        "total_cost": round(costs["total_cost"], 2),
        "net_amount": round(net_amount, 2),
        "reason": reason,
        "strategy_tag": strategy_tag,
        "strategy_id": strategy_tag,
        "status": "filled",
        "notes": notes,
    }
    append_portfolio_row(row)
    sync_compatibility_ledgers()
    sync_workbook()
    return row


def settle_day(
    *,
    settle_date: str,
    prices: Dict[str, float],
    names: Optional[Dict[str, str]] = None,
    config: Optional[AccountConfig] = None,
    notes: str = "",
) -> Dict[str, object]:
    ensure_ledger_files()
    cfg = config or load_account_config()
    names = names or {}
    lots: Dict[str, int] = {}
    cost_basis: Dict[str, float] = {}
    stock_names: Dict[str, str] = {}
    cash = cfg.initial_cash

    inventory_rows = [
        row for row in portfolio_rows() if row.get("row_type") in {"OPENING_POSITION", "TRADE"}
    ]
    for order in inventory_rows:
        side = str(order.get("side", "")).upper()
        symbol = str(order.get("symbol", ""))
        qty = as_int(order.get("quantity"))
        gross = as_float(order.get("gross_amount"))
        total_cost = as_float(order.get("total_cost"))
        net_amount = as_float(order.get("net_amount"))
        stock_names[symbol] = order.get("name") or names.get(symbol, "")
        cash += net_amount
        if side == "BUY":
            lots[symbol] = lots.get(symbol, 0) + qty
            cost_basis[symbol] = cost_basis.get(symbol, 0.0) + gross + total_cost
        elif side == "SELL":
            previous_qty = lots.get(symbol, 0)
            avg_cost = cost_basis.get(symbol, 0.0) / previous_qty if previous_qty else 0.0
            lots[symbol] = max(0, previous_qty - qty)
            cost_basis[symbol] = max(0.0, cost_basis.get(symbol, 0.0) - avg_cost * qty)

    position_rows: List[Dict[str, object]] = []
    stock_value = 0.0
    for symbol, qty in sorted(lots.items()):
        if qty <= 0:
            continue
        last_price = as_float(prices.get(symbol))
        avg_cost = cost_basis.get(symbol, 0.0) / qty if qty else 0.0
        market_value = qty * last_price
        unrealized = market_value - cost_basis.get(symbol, 0.0)
        stock_value += market_value
        position_rows.append(
            {
                "date": settle_date,
                "section": f"{settle_date} 持仓",
                "row_type": "POSITION",
                "symbol": symbol,
                "name": stock_names.get(symbol) or names.get(symbol, ""),
                "side": "LONG",
                "quantity": qty,
                "avg_cost": round(avg_cost, 4),
                "price": round(last_price, 4),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized, 2),
                "unrealized_pnl_pct": round(unrealized / cost_basis.get(symbol, 1.0) * 100, 4) if cost_basis.get(symbol, 0.0) else 0.0,
                "weight_pct": 0.0,
                "thesis": "",
                "status": "open",
                "review_date": "",
                "notes": "",
            }
        )

    end_equity = cash + stock_value
    for row in position_rows:
        row["weight_pct"] = round(as_float(row["market_value"]) / end_equity * 100, 4) if end_equity else 0.0

    previous_rows = equity_from_portfolio()
    start_equity = as_float(previous_rows[-1].get("end_equity"), cfg.initial_cash) if previous_rows else cfg.initial_cash
    previous_peak = max([cfg.initial_cash] + [as_float(row.get("end_equity"), cfg.initial_cash) for row in previous_rows])
    peak = max(previous_peak, end_equity)
    drawdown_pct = (end_equity / peak - 1) * 100 if peak else 0.0
    daily_pnl = end_equity - start_equity
    daily_return_pct = daily_pnl / start_equity * 100 if start_equity else 0.0
    exposure_pct = stock_value / end_equity * 100 if end_equity else 0.0
    risk_state = risk_state_for(daily_return_pct, drawdown_pct, cfg)
    equity_row = {
        "date": settle_date,
        "section": f"{settle_date} 组合汇总",
        "row_type": "DAY_SUMMARY",
        "start_equity": round(start_equity, 2),
        "end_equity": round(end_equity, 2),
        "daily_pnl": round(daily_pnl, 2),
        "daily_return_pct": round(daily_return_pct, 4),
        "cash": round(cash, 2),
        "stock_value": round(stock_value, 2),
        "total_exposure_pct": round(exposure_pct, 4),
        "max_drawdown_pct": round(drawdown_pct, 4),
        "risk_state": risk_state,
        "notes": notes,
    }
    existing_rows = [
        row
        for row in portfolio_rows()
        if not (row.get("date") == settle_date and row.get("row_type") in {"DAY_SUMMARY", "POSITION"})
    ]
    write_portfolio_rows(existing_rows + [equity_row] + position_rows)
    sync_compatibility_ledgers()
    sync_workbook()
    return equity_row


def risk_state_for(daily_return_pct: float, drawdown_pct: float, cfg: AccountConfig) -> str:
    if daily_return_pct <= -cfg.daily_loss_stop_pct or abs(drawdown_pct) >= cfg.max_drawdown_stop_pct:
        return "STOP"
    if abs(drawdown_pct) >= cfg.max_drawdown_alert_pct:
        return "ALERT"
    return "OK"


def latest_status(config: Optional[AccountConfig] = None) -> str:
    ensure_ledger_files()
    cfg = config or load_account_config()
    equity_rows = equity_from_portfolio()
    positions = active_positions()
    if equity_rows:
        last = equity_rows[-1]
        return (
            f"账户状态 {last.get('date')}: 权益={last.get('end_equity')}，现金={last.get('cash')}，"
            f"股票市值={last.get('stock_value')}，当日盈亏={last.get('daily_pnl')}，"
            f"回撤={last.get('max_drawdown_pct')}%，风险={last.get('risk_state')}，持仓数={len(positions)}"
        )
    return f"账户状态: 尚未结算，初始资金={cfg.initial_cash:.2f}，持仓数={len(positions)}"


def parse_price_list(items: List[str]) -> Dict[str, float]:
    prices = {}
    for item in items:
        symbol, price = item.split("=", 1)
        prices[symbol.strip()] = float(price)
    return prices


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股纸面账户状态管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化账本文件")

    trade = sub.add_parser("trade", help="记录一笔纸面成交")
    trade.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    trade.add_argument("--time", default=datetime.now().strftime("%H:%M"))
    trade.add_argument("--symbol", required=True)
    trade.add_argument("--name", default="")
    trade.add_argument("--side", choices=["BUY", "SELL"], required=True)
    trade.add_argument("--quantity", type=int, required=True)
    trade.add_argument("--price", type=float, required=True)
    trade.add_argument("--reason", default="")
    trade.add_argument("--strategy-tag", default="")
    trade.add_argument("--notes", default="")

    settle = sub.add_parser("settle", help="按收盘价结算当天账户")
    settle.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    settle.add_argument("--price", action="append", default=[], help="格式: 600519=1272.86，可重复")
    settle.add_argument("--notes", default="")

    sub.add_parser("status", help="查看最新账户状态")
    args = parser.parse_args(argv)

    if args.command == "init":
        ensure_ledger_files()
        print(latest_status())
        return 0
    if args.command == "trade":
        row = record_trade(
            symbol=args.symbol,
            name=args.name,
            side=args.side,
            quantity=args.quantity,
            price=args.price,
            trade_date=args.date,
            trade_time=args.time,
            reason=args.reason,
            strategy_tag=args.strategy_tag,
            notes=args.notes,
        )
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0
    if args.command == "settle":
        row = settle_day(settle_date=args.date, prices=parse_price_list(args.price), notes=args.notes)
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        print(latest_status())
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
