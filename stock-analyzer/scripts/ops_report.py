#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily operations report for the paper-trading workflow."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import paper_account


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
REVIEWS_DIR = JOURNAL_DIR / "reviews"
STRATEGY_RUNS_DIR = JOURNAL_DIR / "strategy-runs"


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def latest_row(rows: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    return rows[-1] if rows else None


def latest_strategy_run(path: Optional[Path] = None) -> List[Dict[str, str]]:
    if path is not None:
        return read_csv(path)
    candidates = sorted(STRATEGY_RUNS_DIR.glob("*.csv"), key=lambda item: item.stat().st_mtime, reverse=True)
    return read_csv(candidates[0]) if candidates else []


def render_ops_report(report_date: str, strategy_path: Optional[Path] = None) -> str:
    equity = latest_row(paper_account.equity_from_portfolio())
    positions = paper_account.positions_from_portfolio()
    orders = paper_account.trades_from_portfolio()
    strategies = latest_strategy_run(strategy_path)

    lines = [
        f"# {report_date} 运营日报",
        "",
        "## 账户状态",
    ]
    if equity:
        lines.extend(
            [
                f"- 期末权益: {equity.get('end_equity', '')}",
                f"- 当日盈亏: {equity.get('daily_pnl', '')}",
                f"- 现金: {equity.get('cash', '')}",
                f"- 股票市值: {equity.get('stock_value', '')}",
                f"- 总暴露: {equity.get('total_exposure_pct', '')}%",
                f"- 回撤: {equity.get('max_drawdown_pct', '')}%",
                f"- 风险状态: {equity.get('risk_state', '')}",
            ]
        )
    else:
        lines.append("- 尚未生成账户结算。")

    lines.extend(["", "## 当前持仓"])
    open_positions = [row for row in positions if int(float(row.get("quantity") or 0)) > 0]
    if open_positions:
        for row in open_positions:
            lines.append(
                f"- {row.get('symbol')} {row.get('name')}: {row.get('quantity')}股，"
                f"市值{row.get('market_value')}，权重{row.get('weight_pct')}%，"
                f"浮盈亏{row.get('unrealized_pnl')}"
            )
    else:
        lines.append("- 空仓")

    lines.extend(["", "## 交易活动"])
    if orders:
        recent_orders = orders[-5:]
        for row in recent_orders:
            lines.append(
                f"- {row.get('date')} {row.get('time')} {row.get('symbol')} {row.get('side')} "
                f"{row.get('quantity')}股，净额{row.get('net_amount')}，成本{row.get('total_cost')}"
            )
    else:
        lines.append("- 今日无交易记录。")

    lines.extend(["", "## 策略对比"])
    if strategies:
        for row in strategies[:5]:
            lines.append(
                f"- {row.get('strategy_id')}: 收益{row.get('total_return_pct')}%，"
                f"回撤{row.get('max_drawdown_pct')}%，Sharpe {row.get('sharpe')}，"
                f"交易{row.get('trade_count')}次"
            )
    else:
        lines.append("- 尚未生成策略对比。")

    actions = []
    if equity and equity.get("risk_state") in {"ALERT", "STOP"}:
        actions.append("风险状态触线，下一交易日先降频复核，不新增策略。")
    if not strategies:
        actions.append("补跑策略对比，至少比较 standard / conservative / active。")
    if not orders:
        actions.append("若有纸面交易计划，先写入订单账本再复盘。")
    if not actions:
        actions.append("保持账户账本、策略对比和盘后复盘同步更新。")

    lines.extend(["", "## 下一步动作"])
    lines.extend(f"- {item}" for item in actions)
    lines.extend(["", "风险提示: 本报告只用于训练/研究，不构成投资建议或自动交易信号。"])
    return "\n".join(lines)


def write_report(report_date: str, content: str, output: Optional[Path] = None) -> Path:
    target = output or REVIEWS_DIR / f"{report_date}-ops-report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="生成纸面交易运营日报")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--strategy-run", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args(argv)

    strategy_path = Path(args.strategy_run) if args.strategy_run else None
    output_path = Path(args.output) if args.output else None
    content = render_ops_report(args.date, strategy_path=strategy_path)
    path = write_report(args.date, content, output_path)
    print(f"运营日报已生成: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
