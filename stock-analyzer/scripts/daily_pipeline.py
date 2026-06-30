#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Intraday paper-trading pipeline orchestration."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import analyze
import ops_report
import paper_account
import paper_execute
import pipeline_review
import strategy_governance
import strategy_lab
import workflow_checkpoints


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
STRATEGY_RUNS_DIR = JOURNAL_DIR / "strategy-runs"
PIPELINE_RUNS_DIR = JOURNAL_DIR / "pipeline-runs"
STRATEGY_PATH = JOURNAL_DIR / "strategies.json"


def build_strategy_outputs(run_date: str) -> Dict[str, Path]:
    target_dir = STRATEGY_RUNS_DIR / run_date
    return {
        "dir": target_dir,
        "optimized": target_dir / "optimized.csv",
        "recommendation": target_dir / "recommendation.json",
    }


def stage_record_path(run_date: str, stage: str, root: Path = PIPELINE_RUNS_DIR) -> Path:
    return root / run_date / f"{stage}.json"


def write_stage_record(payload: Dict[str, object], root: Path = PIPELINE_RUNS_DIR) -> Path:
    run_date = str(payload.get("run_date") or datetime.now().strftime("%Y-%m-%d"))
    stage = str(payload.get("stage") or "unknown")
    path = stage_record_path(run_date, stage, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def sync_workbook_safe() -> Dict[str, object]:
    try:
        paper_account.sync_workbook()
        return {"ok": True, "workbook": str(paper_account.WORKBOOK_PATH)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def read_stage_record(run_date: str, stage: str, root: Path = PIPELINE_RUNS_DIR) -> Optional[Dict[str, object]]:
    path = stage_record_path(run_date, stage, root=root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def optimize_and_optionally_promote(
    *,
    stocks: List[str],
    days: int,
    source: str,
    run_date: str,
    promote: bool,
    require_cache_health: bool,
    optimization: Optional[str] = None,
) -> Dict[str, object]:
    outputs = build_strategy_outputs(run_date)
    if require_cache_health:
        strategy_lab.require_cache_health(stocks, days=days, min_rows=80, max_age_hours=36)
    frames = strategy_lab.backtest.load_market_frames(stocks, days, source)
    strategy_lab.require_market_frames(frames, stocks)
    opt_config = (
        strategy_governance.optimization_config_for_profile(optimization)
        if optimization
        else strategy_lab.OptimizationConfig(min_history=80)
    )
    rows = strategy_lab.optimize_strategies_from_frames(
        frames,
        strategy_lab.generate_parameter_grid(optimization=opt_config),
        opt_config,
    )
    strategy_lab.write_rows_dynamic(rows, outputs["optimized"])
    strategy_lab.write_recommendation(rows, outputs["recommendation"])
    promoted: Dict[str, object] = {}
    if promote:
        try:
            promoted = strategy_lab.promote_recommendation_to_registry(
                outputs["recommendation"],
                STRATEGY_PATH,
            )
        except ValueError as exc:
            promoted = {"status": "not_promoted", "reason": str(exc)}
    return {
        "optimized_path": str(outputs["optimized"]),
        "recommendation_path": str(outputs["recommendation"]),
        "best": rows[0] if rows else {},
        "promoted": promoted,
    }


def settle_from_decisions(package: Dict[str, object], run_date: str) -> Optional[Dict[str, object]]:
    prices = {
        str(item["symbol"]): float(item["price"])
        for item in package.get("decisions", [])
        if item.get("price")
    }
    names = {
        str(item["symbol"]): str(item.get("name", ""))
        for item in package.get("decisions", [])
    }
    active_positions = paper_account.active_positions()
    for symbol, row in active_positions.items():
        if symbol not in prices and row.get("last_price"):
            prices[symbol] = paper_account.as_float(row.get("last_price"))
            names.setdefault(symbol, str(row.get("name", "")))
    if not prices:
        return None
    return paper_account.settle_day(
        settle_date=run_date,
        prices=prices,
        names=names,
        notes="daily_pipeline 纸面收盘结算；非真实交易",
    )


def run_stage(
    *,
    stage: str,
    stocks: List[str],
    days: int,
    source: str,
    run_date: str,
    execute: bool = False,
    promote: bool = False,
    require_cache_health: bool = True,
) -> Dict[str, object]:
    result: Dict[str, object] = {
        "ok": True,
        "stage": stage,
        "run_date": run_date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "paper",
        "monitoring_note": "日常阶段用于纸面账户结算、风险暴露和流程漂移检查；研究回测仅在策略/参数/股票池规则变更或周/月度复盘时运行。",
        "risk_note": "仅用于训练/研究和纸面交易，不构成投资建议、稳定盈利承诺或真实交易指令。",
    }
    workflow_checkpoints.seed_day(run_date)
    try:
        if stage == "preopen":
            governance = strategy_governance.review_and_govern(run_date, apply_feedback=True)
            result["strategy_governance"] = governance
            previous_close = read_stage_record(run_date, "close")
            if previous_close:
                result["previous_close_summary"] = {
                    "ok": previous_close.get("ok"),
                    "generated_at": previous_close.get("generated_at"),
                    "has_settlement": bool(previous_close.get("settlement")),
                }
            health = analyze.inspect_market_cache(stocks, days=days, min_rows=80, max_age_hours=36)
            result["cache_health"] = health
            result["ok"] = bool(health.get("ok"))
            if not health.get("ok"):
                result["next_action"] = "先刷新缓存或修复行情源，再运行策略优化和纸面执行。"
            elif not governance.get("permissions", {}).get("allow_parameter_search"):
                result["ok"] = False
                result["next_action"] = governance.get("reason")
            else:
                result["strategy_optimization"] = optimize_and_optionally_promote(
                    stocks=stocks,
                    days=days,
                    source=source,
                    run_date=run_date,
                    promote=promote and bool(governance.get("permissions", {}).get("allow_promotion")),
                    require_cache_health=False,
                    optimization=str(governance.get("profile") or "standard"),
                )
        elif stage in {"open", "afternoon"}:
            package = paper_execute.build_decision_package(
                stocks,
                days=days,
                source=source,
                require_cache_health=require_cache_health,
            )
            package["executed_orders"] = paper_execute.execute_decisions(
                package,
                trade_date=run_date,
                trade_time="09:30" if stage == "open" else "13:00",
                dry_run=not execute,
            )
            result["execution"] = package
            result["ok"] = bool(package.get("ok"))
        elif stage == "midday":
            health = analyze.inspect_market_cache(stocks, days=days, min_rows=80, max_age_hours=36)
            package = paper_execute.build_decision_package(
                stocks,
                days=days,
                source=source,
                require_cache_health=require_cache_health,
            )
            result["cache_health"] = health
            result["afternoon_plan"] = package
            result["ok"] = bool(health.get("ok") and package.get("ok"))
        elif stage == "close":
            package = paper_execute.build_decision_package(
                stocks,
                days=days,
                source=source,
                require_cache_health=require_cache_health,
            )
            result["close_decisions"] = package
            if execute:
                result["settlement"] = settle_from_decisions(package, run_date)
                result["ops_report"] = str(
                    ops_report.write_report(
                        run_date,
                        ops_report.render_ops_report(run_date),
                    )
                )
            result["pipeline_review"] = pipeline_review.review_pipeline_day(run_date)
            result["ok"] = bool(package.get("ok"))
        else:
            raise ValueError(f"unknown stage: {stage}")
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
    result["workbook_sync"] = sync_workbook_safe()
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股日内纸面交易流水线")
    parser.add_argument("--stage", required=True, choices=["preopen", "open", "midday", "afternoon", "close"])
    parser.add_argument("--stocks", default="600519,300750")
    parser.add_argument("--days", type=int, default=260)
    parser.add_argument("--source", default="premium", choices=["premium", "push", "pull", "auto", "tencent", "eastmoney", "tushare", "stooq"])
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--execute", action="store_true", help="允许写入纸面成交/结算/日报；不会真实下单")
    parser.add_argument("--promote", action="store_true", help="preopen 阶段允许把合格候选晋级为 active paper strategy")
    parser.add_argument("--allow-unhealthy-cache", action="store_true", help="执行阶段不强制缓存健康，仅用于人工调试")
    parser.add_argument("--record", action="store_true", help="把阶段运行结果写入 trading-journal/pipeline-runs")
    args = parser.parse_args(argv)

    payload = run_stage(
        stage=args.stage,
        stocks=analyze.split_stock_list(args.stocks),
        days=max(80, min(args.days, 1200)),
        source=args.source,
        run_date=args.date,
        execute=args.execute,
        promote=args.promote,
        require_cache_health=not args.allow_unhealthy_cache,
    )
    if args.record:
        payload["record_path"] = str(write_stage_record(payload))
        try:
            payload["checkpoint_import"] = workflow_checkpoints.import_pipeline_records(args.date)
            payload["checkpoint_audit"] = workflow_checkpoints.audit_day(args.date)
            payload["workbook_sync"] = sync_workbook_safe()
            write_stage_record(payload)
        except Exception as exc:
            payload["checkpoint_error"] = str(exc)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
