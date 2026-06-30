#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Govern strategy optimization permissions from pipeline feedback."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import paper_account
import pipeline_review
import strategy_lab


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
STRATEGY_PATH = JOURNAL_DIR / "strategies.json"


def governance_from_review(review: Dict[str, object]) -> Dict[str, object]:
    bucket = str(review.get("failure_bucket") or "missing_pipeline_records")
    equity = review.get("equity") if isinstance(review.get("equity"), dict) else {}
    risk_state = str(equity.get("risk_state") or "")
    order_count = int(review.get("order_count") or 0)

    allow_backtest = bucket in {"pipeline_ok"}
    allow_parameter_search = bucket == "pipeline_ok"
    allow_promotion = bucket == "pipeline_ok" and risk_state not in {"ALERT", "STOP"}
    allow_new_entries = risk_state not in {"ALERT", "STOP"} and bucket == "pipeline_ok"
    profile = "standard"
    reason = "流水线正常，允许标准参数搜索。"

    if bucket in {"missing_pipeline_records", "data_cache_unhealthy"}:
        profile = "blocked_data"
        reason = "流水线记录或行情缓存不可用，禁止调参和晋级。"
    elif bucket.endswith("_failed"):
        profile = "blocked_pipeline"
        reason = "日内阶段失败，先修复失败链路。"
    elif risk_state in {"ALERT", "STOP"}:
        profile = "defensive"
        reason = "账户风险状态触线，仅允许防守型复核。"
        allow_parameter_search = True
        allow_promotion = False
        allow_new_entries = False
    elif bucket == "pipeline_ok" and order_count == 0:
        profile = "exploration"
        reason = "流水线正常但无成交，允许小幅放宽观察参数。"

    return {
        "ok": allow_backtest or profile in {"defensive", "exploration", "standard"},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_date": review.get("run_date"),
        "profile": profile,
        "reason": reason,
        "permissions": {
            "allow_backtest": allow_backtest or profile in {"defensive", "exploration"},
            "allow_parameter_search": allow_parameter_search,
            "allow_promotion": allow_promotion,
            "allow_new_entries": allow_new_entries,
        },
        "optimization": optimization_config_for_profile(profile).__dict__,
        "review": {
            "failure_bucket": bucket,
            "risk_state": risk_state,
            "order_count": order_count,
            "stage_status": review.get("stage_status", {}),
        },
        "risk_note": "仅用于训练/研究和纸面交易治理，不构成投资建议、稳定盈利承诺或真实交易指令。",
    }


def as_float(value: object, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def append_feedback_to_ledger(row: Dict[str, object], ledger_path: Path) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    exists = ledger_path.exists() and ledger_path.stat().st_size > 0
    with ledger_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=paper_account.PORTFOLIO_LEDGER_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in paper_account.PORTFOLIO_LEDGER_FIELDS})


def strategy_feedback_decision(review: Dict[str, object], strategy: Dict[str, object]) -> Dict[str, object]:
    equity = review.get("equity") if isinstance(review.get("equity"), dict) else {}
    daily_return_pct = as_float(equity.get("daily_return_pct"))
    daily_pnl = as_float(equity.get("daily_pnl"))
    risk_state = str(equity.get("risk_state") or "")
    bucket = str(review.get("failure_bucket") or "")
    order_count = int(review.get("order_count") or 0)
    previous_weight = as_float(strategy.get("paper_weight"), 1.0)
    failure_count = int(strategy.get("failure_count") or 0)
    success_count = int(strategy.get("success_count") or 0)

    failed = bucket != "pipeline_ok" or risk_state == "STOP" or daily_return_pct < 0
    if failed:
        failure_count += 1
        success_count = 0
    elif order_count > 0:
        success_count += 1
        failure_count = 0

    status = str(strategy.get("strategy_status") or "active")
    adjustment = 0.0
    reason = "策略表现中性，维持权重。"
    if bucket != "pipeline_ok":
        adjustment = -0.2
        status = "paused"
        reason = f"流水线反馈为 {bucket}，暂停策略扩张并降低权重。"
    elif risk_state == "STOP" or daily_return_pct <= -1.0:
        adjustment = -0.35
        status = "probation"
        reason = "账户触发 STOP 或单日亏损超过 1%，先进入观察并降低权重；连续失败才淘汰。"
    elif daily_return_pct < 0:
        adjustment = -0.25
        status = "probation"
        reason = "当日收益为负，策略进入观察并降低权重。"
    elif order_count > 0 and daily_return_pct > 0:
        adjustment = 0.1
        status = "active"
        reason = "有成交且收益为正，小幅提高策略权重。"

    if failure_count >= 3:
        status = "retired"
        adjustment = min(adjustment, -0.6)
        reason = "连续失败次数达到 3 次，淘汰该纸面策略。"

    new_weight = max(0.0, min(1.5, previous_weight + adjustment))
    if status == "retired":
        new_weight = 0.0

    return {
        "paper_weight": round(new_weight, 4),
        "strategy_status": status,
        "failure_count": failure_count,
        "success_count": success_count,
        "daily_return_pct": daily_return_pct,
        "daily_pnl": daily_pnl,
        "reason": reason,
    }


def apply_strategy_feedback(
    review: Dict[str, object],
    registry_path: Path = STRATEGY_PATH,
    ledger_path: Path = paper_account.PORTFOLIO_LEDGER_PATH,
) -> Dict[str, object]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    active_id = registry.get("active_paper_strategy_id") or "score-standard-v1"
    strategies = registry.setdefault("strategies", [])
    target: Optional[Dict[str, object]] = None
    for item in strategies:
        if item.get("id") == active_id:
            target = item
            break
    if target is None:
        return {
            "ok": False,
            "strategy_id": active_id,
            "strategy_status": "missing",
            "reason": "active paper strategy not found",
        }

    decision = strategy_feedback_decision(review, target)
    target.update(
        {
            "paper_weight": decision["paper_weight"],
            "strategy_status": decision["strategy_status"],
            "failure_count": decision["failure_count"],
            "success_count": decision["success_count"],
            "last_feedback_date": review.get("run_date"),
            "last_feedback_reason": decision["reason"],
        }
    )
    if decision["strategy_status"] == "retired" and registry.get("active_paper_strategy_id") == active_id:
        registry["active_paper_strategy_id"] = ""
        registry["active_paper_strategy_note"] = "上一活跃策略已因纸面反馈淘汰，需重新通过治理门槛选择。"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    weights = {
        str(item.get("id")): item.get("paper_weight", "")
        for item in strategies
        if item.get("id")
    }
    feedback_row = {
        "date": review.get("run_date", ""),
        "section": f"{review.get('run_date', '')} 策略反馈",
        "row_type": "STRATEGY_FEEDBACK",
        "strategy_id": active_id,
        "score_profile": target.get("score_profile", ""),
        "factor_weights": json.dumps(weights, ensure_ascii=False, sort_keys=True),
        "strategy_status": decision["strategy_status"],
        "daily_pnl": decision["daily_pnl"],
        "daily_return_pct": decision["daily_return_pct"],
        "risk_state": (review.get("equity") or {}).get("risk_state", "") if isinstance(review.get("equity"), dict) else "",
        "reason": decision["reason"],
        "notes": f"failure_bucket={review.get('failure_bucket', '')}; order_count={review.get('order_count', 0)}",
    }
    append_feedback_to_ledger(feedback_row, ledger_path)
    return {"ok": True, "strategy_id": active_id, **decision}


def optimization_config_for_profile(profile: str) -> strategy_lab.OptimizationConfig:
    if profile == "defensive":
        return strategy_lab.OptimizationConfig(
            entry_scores=(62.0, 66.0, 70.0),
            exit_scores=(48.0, 52.0),
            max_position_pcts=(5.0, 8.0, 10.0),
            max_total_exposure_pcts=(20.0, 30.0, 40.0),
            min_trades=1,
            max_drawdown_pct=12.0,
        )
    if profile == "exploration":
        return strategy_lab.OptimizationConfig(
            entry_scores=(52.0, 56.0, 60.0),
            exit_scores=(40.0, 44.0, 48.0),
            max_position_pcts=(8.0, 12.0, 15.0),
            max_total_exposure_pcts=(30.0, 45.0, 60.0),
            min_trades=1,
            max_drawdown_pct=18.0,
        )
    if profile == "standard":
        return strategy_lab.OptimizationConfig()
    return strategy_lab.OptimizationConfig(
        entry_scores=(70.0,),
        exit_scores=(55.0,),
        max_position_pcts=(0.0,),
        max_total_exposure_pcts=(0.0,),
        min_trades=999,
        max_drawdown_pct=0.0,
    )


def review_and_govern(run_date: str, root: Optional[Path] = None, apply_feedback: bool = False) -> Dict[str, object]:
    review_root = root or pipeline_review.PIPELINE_RUNS_DIR
    source_date = pipeline_review.latest_run_date_before_or_on(run_date, root=review_root) or run_date
    review = pipeline_review.review_pipeline_day(source_date, root=review_root)
    payload = governance_from_review(review)
    payload["requested_run_date"] = run_date
    payload["source_run_date"] = source_date
    if apply_feedback:
        try:
            payload["strategy_feedback"] = apply_strategy_feedback(review)
        except Exception as exc:
            payload["strategy_feedback"] = {"ok": False, "error": str(exc)}
    return payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="根据流水线反馈生成策略治理约束")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args(argv)

    payload = review_and_govern(args.date)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("permissions", {}).get("allow_parameter_search") else 2


if __name__ == "__main__":
    raise SystemExit(main())
