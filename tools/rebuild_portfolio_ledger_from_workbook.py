#!/usr/bin/env python3
"""Rebuild the single CSV ledger from the restored workbook plus legacy CSV rows."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Dict, Iterable, List

from extract_existing_workbook_history import extract


FIELDS = [
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


def value(item: Dict[str, object], key: str) -> object:
    current = item.get(key, "")
    text = str(current)
    return "" if text.startswith("=") else current


def append(rows: List[Dict[str, object]], row: Dict[str, object]) -> None:
    rows.append({field: row.get(field, "") for field in FIELDS})


def plan_rows(payload: Dict[str, object]) -> Iterable[Dict[str, object]]:
    for item in payload.get("plan_rows", []):
        symbol = str(item.get("股票代码", "")).strip()
        if not symbol:
            continue
        actual_qty = value(item, "实际买入股数")
        actual_price = value(item, "实际买入价")
        if actual_qty and actual_price:
            yield {
                "date": "2026-06-05",
                "section": "2026-06-05 原Excel交易计划",
                "row_type": "TRADE_PLAN",
                "time": item.get("买入时间", ""),
                "symbol": symbol,
                "name": item.get("名称", ""),
                "side": "BUY" if float(actual_qty) > 0 else "",
                "action": item.get("13:00买/卖动作", ""),
                "quantity": actual_qty,
                "price": actual_price,
                "gross_amount": value(item, "实际投入金额"),
                "market_value": value(item, "卖出金额"),
                "realized_pnl": value(item, "实现盈亏"),
                "unrealized_pnl": value(item, "实现盈亏") if symbol == "600519" else "",
                "unrealized_pnl_pct": value(item, "收益率%"),
                "weight_pct": value(item, "实际占总资金%"),
                "strategy_tag": item.get("交易策略", ""),
                "strategy_id": item.get("交易策略", ""),
                "reason": item.get("买入/观察条件", ""),
                "thesis": item.get("后验验证口径", ""),
                "status": item.get("最终判断", ""),
                "notes": item.get("备注", ""),
            }


def execution_rows(payload: Dict[str, object]) -> Iterable[Dict[str, object]]:
    for item in payload.get("execution_rows", []):
        stage = str(item.get("复查阶段", ""))
        symbol = str(item.get("股票代码", "") or "").strip()
        action = str(item.get("动作", "") or "")
        if not symbol and stage != "组合汇总":
            continue
        row_type = "DAY_SUMMARY" if stage == "组合汇总" else "INTRADAY_CHECK"
        raw_time = str(item.get("时间", "") or "")
        date = raw_time if raw_time.startswith("2026-") else "2026-06-05"
        yield {
            "date": date,
            "section": f"{date} {stage}",
            "row_type": row_type,
            "time": "" if raw_time.startswith("2026-") else raw_time,
            "symbol": symbol,
            "name": item.get("名称", ""),
            "side": item.get("方向", ""),
            "action": action,
            "quantity": item.get("股数", ""),
            "price": item.get("价格", ""),
            "gross_amount": item.get("金额", ""),
            "cash": item.get("组合现金", ""),
            "stock_value": item.get("组合市值", ""),
            "market_value": item.get("金额", ""),
            "daily_return_pct": item.get("组合收益率%", ""),
            "weight_pct": item.get("仓位%", ""),
            "reason": item.get("买卖理由", "") or item.get("触发条件", ""),
            "review_date": item.get("后续验证", ""),
            "status": item.get("是否正确", ""),
            "notes": item.get("备注", ""),
        }


def legacy_rows(csv_path: Path) -> Iterable[Dict[str, object]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            if row.get("row_type") in {"TRADE_PLAN", "INTRADAY_CHECK"}:
                continue
            if row.get("row_type") in {"OPENING_POSITION", "TARGET_PORTFOLIO", "DAY_SUMMARY", "POSITION", "STRATEGY_FEEDBACK"}:
                rows.append(row)
                continue
            if row.get("row_type") == "TRADE" and row.get("strategy_tag") == "manual-sync":
                row = dict(row)
                row["date"] = "2026-06-05"
                row["section"] = "2026-06-05 期初持仓同步"
                row["row_type"] = "OPENING_POSITION"
                row["time"] = ""
                row["action"] = "期初持仓同步"
                row["reason"] = "不是2026年2月真实交易；仅用于承接量化系统开始时已存在的600519纸面持仓"
                row["notes"] = (
                    "原始来源为本地回测未确认卖出后的持仓同步；"
                    "总表按2026-06-05期初持仓处理，不作为量化交易启动前成交。"
                )
                rows.append(row)
        if not any(row.get("row_type") == "OPENING_POSITION" for row in rows):
            orders_path = csv_path.parent / "ledger" / "orders.csv"
            if orders_path.exists():
                with orders_path.open("r", encoding="utf-8-sig", newline="") as orders_handle:
                    for order in csv.DictReader(orders_handle):
                        if order.get("strategy_tag") != "manual-sync":
                            continue
                        rows.append(
                            {
                                "date": "2026-06-05",
                                "section": "2026-06-05 期初持仓同步",
                                "row_type": "OPENING_POSITION",
                                "time": "",
                                "symbol": order.get("symbol", ""),
                                "name": order.get("name", ""),
                                "side": order.get("side", ""),
                                "action": "期初持仓同步",
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
                                "reason": "不是2026年2月真实交易；仅用于承接量化系统开始时已存在的600519纸面持仓",
                                "status": order.get("status", ""),
                                "notes": "原始来源为本地回测未确认卖出后的持仓同步；总表按2026-06-05期初持仓处理，不作为量化交易启动前成交。",
                            }
                        )
        existing_equity_dates = {row.get("date") for row in rows if row.get("row_type") == "DAY_SUMMARY"}
        equity_path = csv_path.parent / "ledger" / "equity_curve.csv"
        if equity_path.exists():
            with equity_path.open("r", encoding="utf-8-sig", newline="") as equity_handle:
                for equity in csv.DictReader(equity_handle):
                    if equity.get("date") in existing_equity_dates:
                        continue
                    rows.append(
                        {
                            "date": equity.get("date", ""),
                            "section": f"{equity.get('date', '')} 组合汇总",
                            "row_type": "DAY_SUMMARY",
                            "cash": equity.get("cash", ""),
                            "stock_value": equity.get("stock_value", ""),
                            "start_equity": equity.get("start_equity", ""),
                            "end_equity": equity.get("end_equity", ""),
                            "daily_pnl": equity.get("daily_pnl", ""),
                            "daily_return_pct": equity.get("daily_return_pct", ""),
                            "total_exposure_pct": equity.get("total_exposure_pct", ""),
                            "max_drawdown_pct": equity.get("max_drawdown_pct", ""),
                            "risk_state": equity.get("risk_state", ""),
                            "notes": equity.get("notes", ""),
                        }
                    )
        existing_position_keys = {
            (row.get("date"), row.get("symbol"))
            for row in rows
            if row.get("row_type") == "POSITION"
        }
        positions_path = csv_path.parent / "ledger" / "positions.csv"
        if positions_path.exists():
            with positions_path.open("r", encoding="utf-8-sig", newline="") as positions_handle:
                for position in csv.DictReader(positions_handle):
                    key = (position.get("date"), position.get("symbol"))
                    if key in existing_position_keys:
                        continue
                    rows.append(
                        {
                            "date": position.get("date", ""),
                            "section": f"{position.get('date', '')} 持仓",
                            "row_type": "POSITION",
                            "symbol": position.get("symbol", ""),
                            "name": position.get("name", ""),
                            "side": position.get("side", ""),
                            "quantity": position.get("quantity", ""),
                            "price": position.get("last_price", ""),
                            "avg_cost": position.get("avg_cost", ""),
                            "market_value": position.get("market_value", ""),
                            "unrealized_pnl": position.get("unrealized_pnl", ""),
                            "unrealized_pnl_pct": position.get("unrealized_pnl_pct", ""),
                            "weight_pct": position.get("weight_pct", ""),
                            "thesis": position.get("thesis", ""),
                            "review_date": position.get("review_date", ""),
                            "status": position.get("status", ""),
                            "notes": position.get("notes", ""),
                        }
                    )
        return rows


def rebuild(workbook_path: Path, existing_ledger_path: Path, output_path: Path) -> None:
    payload = extract(workbook_path)
    rows: List[Dict[str, object]] = []
    for row in legacy_rows(existing_ledger_path):
        append(rows, row)
    for row in plan_rows(payload):
        append(rows, row)
    for row in execution_rows(payload):
        append(rows, row)

    unique_rows: List[Dict[str, object]] = []
    seen = set()
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in FIELDS)
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    rows = unique_rows

    order = {
        "OPENING_POSITION": 0,
        "TARGET_PORTFOLIO": 1,
        "TRADE": 2,
        "TRADE_PLAN": 3,
        "DAY_SUMMARY": 4,
        "POSITION": 5,
        "INTRADAY_CHECK": 6,
        "STRATEGY_FEEDBACK": 7,
    }
    rows.sort(key=lambda row: (str(row.get("date", "")), order.get(str(row.get("row_type", "")), 99), str(row.get("time", "")), str(row.get("symbol", ""))))
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: rebuild_portfolio_ledger_from_workbook.py <workbook.xlsx> <existing-ledger.csv> <output-ledger.csv>", file=sys.stderr)
        return 2
    rebuild(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
