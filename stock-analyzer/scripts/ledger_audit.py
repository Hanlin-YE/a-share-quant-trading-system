#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit formal paper-account ledger invariants."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional


ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = ROOT / "trading-journal" / "portfolio_ledger.csv"
LOT_SIZE = 100
MORNING_START = "09:30"
MORNING_END = "11:30"
AFTERNOON_START = "13:00"
AFTERNOON_END = "15:00"


def as_float(value: object) -> Optional[float]:
    try:
        if value in ("", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: object, default: int = 0) -> int:
    try:
        if value in ("", None):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def read_rows(path: Path = LEDGER_PATH) -> List[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def day_summaries(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [row for row in rows if row.get("row_type") == "DAY_SUMMARY"]


def audit_equity_continuity(rows: List[Dict[str, str]], tolerance: float = 0.01) -> List[Dict[str, object]]:
    issues: List[Dict[str, object]] = []
    summaries = day_summaries(rows)
    summaries.sort(key=lambda row: (row.get("date", ""), row.get("time", "")))
    previous = None
    for row in summaries:
        start = as_float(row.get("start_equity"))
        end = as_float(row.get("end_equity"))
        if end is None:
            issues.append(
                {
                    "type": "missing_end_equity",
                    "date": row.get("date", ""),
                    "section": row.get("section", ""),
                }
            )
        if previous is not None and start is not None:
            previous_end = as_float(previous.get("end_equity"))
            if previous_end is not None and abs(start - previous_end) > tolerance:
                issues.append(
                    {
                        "type": "equity_continuity_break",
                        "date": row.get("date", ""),
                        "section": row.get("section", ""),
                        "start_equity": start,
                        "previous_date": previous.get("date", ""),
                        "previous_end_equity": previous_end,
                        "difference": round(start - previous_end, 4),
                    }
                )
        previous = row if end is not None else previous
    return issues


def audit_non_summary_equity(rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    equity_fields = ["start_equity", "end_equity", "daily_pnl", "daily_return_pct"]
    issues = []
    for index, row in enumerate(rows, start=2):
        if row.get("row_type") == "DAY_SUMMARY":
            continue
        filled = {field: row.get(field, "") for field in equity_fields if row.get(field, "") not in ("", None)}
        if filled:
            issues.append(
                {
                    "type": "non_summary_equity_values",
                    "csv_line": index,
                    "date": row.get("date", ""),
                    "row_type": row.get("row_type", ""),
                    "section": row.get("section", ""),
                    "filled": filled,
                }
            )
    return issues


def valid_trade_time(value: str) -> bool:
    text = str(value or "").strip()
    return (MORNING_START <= text <= MORNING_END) or (AFTERNOON_START <= text <= AFTERNOON_END)


def audit_trade_rules(rows: List[Dict[str, str]]) -> List[Dict[str, object]]:
    issues: List[Dict[str, object]] = []
    positions: Dict[str, int] = {}
    sellable: Dict[str, int] = {}
    current_date = ""
    trade_rows = [
        (index, row)
        for index, row in enumerate(rows, start=2)
        if row.get("row_type") in {"OPENING_POSITION", "TRADE"}
    ]
    trade_rows.sort(key=lambda item: (item[1].get("date", ""), item[1].get("time", ""), item[0]))

    def roll_date(row_date: str) -> None:
        nonlocal current_date, sellable
        if row_date and row_date != current_date:
            current_date = row_date
            sellable = dict(positions)

    for csv_line, row in trade_rows:
        row_date = str(row.get("date", ""))
        roll_date(row_date)
        symbol = str(row.get("symbol", ""))
        side = str(row.get("side", "")).upper()
        qty = as_int(row.get("quantity"))
        row_type = row.get("row_type")
        if not symbol or qty <= 0:
            continue

        if row_type == "OPENING_POSITION":
            positions[symbol] = positions.get(symbol, 0) + qty
            sellable[symbol] = sellable.get(symbol, 0) + qty
            continue

        if not valid_trade_time(str(row.get("time", ""))):
            issues.append(
                {
                    "type": "invalid_trade_time",
                    "csv_line": csv_line,
                    "date": row_date,
                    "symbol": symbol,
                    "time": row.get("time", ""),
                }
            )
        if side == "BUY":
            if qty % LOT_SIZE != 0:
                issues.append(
                    {
                        "type": "invalid_buy_lot",
                        "csv_line": csv_line,
                        "date": row_date,
                        "symbol": symbol,
                        "quantity": qty,
                    }
                )
            positions[symbol] = positions.get(symbol, 0) + qty
            continue
        if side == "SELL":
            available = sellable.get(symbol, 0)
            current_qty = positions.get(symbol, 0)
            if qty > available:
                issues.append(
                    {
                        "type": "t_plus_one_violation",
                        "csv_line": csv_line,
                        "date": row_date,
                        "symbol": symbol,
                        "quantity": qty,
                        "sellable": available,
                    }
                )
            remaining = current_qty - qty
            if remaining > 0 and qty % LOT_SIZE != 0:
                issues.append(
                    {
                        "type": "invalid_sell_lot",
                        "csv_line": csv_line,
                        "date": row_date,
                        "symbol": symbol,
                        "quantity": qty,
                        "remaining": remaining,
                    }
                )
            if 0 < remaining < LOT_SIZE:
                issues.append(
                    {
                        "type": "odd_lot_remainder",
                        "csv_line": csv_line,
                        "date": row_date,
                        "symbol": symbol,
                        "quantity": qty,
                        "remaining": remaining,
                    }
                )
            positions[symbol] = max(0, remaining)
            sellable[symbol] = max(0, available - qty)
    return issues


def audit_ledger(path: Path = LEDGER_PATH) -> Dict[str, object]:
    rows = read_rows(path)
    issues = audit_equity_continuity(rows) + audit_non_summary_equity(rows) + audit_trade_rules(rows)
    return {
        "ok": not issues,
        "path": str(path),
        "issue_count": len(issues),
        "issues": issues,
    }


def render(result: Dict[str, object]) -> str:
    lines = [
        "纸面账户账本审计",
        "==============",
        f"文件: {result['path']}",
        f"问题数: {result['issue_count']}",
    ]
    for issue in result["issues"]:
        if issue["type"] == "equity_continuity_break":
            lines.append(
                f"- 权益不连续: {issue['previous_date']} 期末 {issue['previous_end_equity']} -> "
                f"{issue['date']} 期初 {issue['start_equity']}，差额 {issue['difference']}"
            )
        elif issue["type"] == "non_summary_equity_values":
            lines.append(
                f"- 非组合汇总行占用权益列: line {issue['csv_line']} {issue['row_type']} {issue['filled']}"
            )
        elif issue["type"] == "invalid_trade_time":
            lines.append(f"- 成交时间无效: line {issue['csv_line']} {issue['symbol']} {issue['time']}")
        elif issue["type"] == "invalid_buy_lot":
            lines.append(f"- 买入非整手: line {issue['csv_line']} {issue['symbol']} {issue['quantity']}股")
        elif issue["type"] == "invalid_sell_lot":
            lines.append(
                f"- 卖出非整手且未清仓: line {issue['csv_line']} {issue['symbol']} "
                f"卖出{issue['quantity']}股，剩余{issue['remaining']}股"
            )
        elif issue["type"] == "odd_lot_remainder":
            lines.append(
                f"- 卖出制造零股: line {issue['csv_line']} {issue['symbol']} "
                f"卖出{issue['quantity']}股，剩余{issue['remaining']}股"
            )
        elif issue["type"] == "t_plus_one_violation":
            lines.append(
                f"- T+1违规: line {issue['csv_line']} {issue['symbol']} "
                f"请求卖出{issue['quantity']}股，可卖{issue['sellable']}股"
            )
        else:
            lines.append(f"- {issue}")
    return "\n".join(lines)


def audit_finding_rows(result: Dict[str, object], finding_date: str) -> List[Dict[str, object]]:
    rows = []
    for issue in result.get("issues", []):
        rows.append(
            {
                "date": finding_date,
                "section": f"{finding_date} 账本审计",
                "row_type": "AUDIT_FINDING",
                "symbol": issue.get("symbol", "PORTFOLIO"),
                "name": "",
                "side": "RESEARCH",
                "action": "审计发现",
                "quantity": issue.get("quantity", ""),
                "strategy_tag": "ledger-audit",
                "strategy_id": "ledger-audit",
                "strategy_status": "needs_fix",
                "reason": issue.get("type", ""),
                "status": "failed",
                "notes": json.dumps(issue, ensure_ascii=False),
            }
        )
    return rows


def append_audit_findings(path: Path, result: Dict[str, object], finding_date: str) -> int:
    rows = read_rows(path)
    existing = {
        row.get("notes", "")
        for row in rows
        if row.get("row_type") == "AUDIT_FINDING" and row.get("date") == finding_date
    }
    findings = [row for row in audit_finding_rows(result, finding_date) if row.get("notes", "") not in existing]
    if not findings:
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        fields = list(csv.DictReader(handle).fieldnames or [])
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        for row in findings:
            writer.writerow({field: row.get(field, "") for field in fields})
    return len(findings)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="审计纸面账户账本连续性")
    parser.add_argument("--ledger", default=str(LEDGER_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--append-findings", action="store_true", help="把审计发现追加到同一 portfolio_ledger.csv")
    parser.add_argument("--date", default="")
    args = parser.parse_args(argv)
    ledger_path = Path(args.ledger)
    result = audit_ledger(ledger_path)
    if args.append_findings and result.get("issues"):
        finding_date = args.date or max((row.get("date", "") for row in read_rows(ledger_path)), default="")
        result["appended_findings"] = append_audit_findings(ledger_path, result, finding_date)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
