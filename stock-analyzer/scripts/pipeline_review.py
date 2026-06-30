#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Review recorded intraday pipeline runs and classify feedback for tuning."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import paper_account


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
PIPELINE_RUNS_DIR = JOURNAL_DIR / "pipeline-runs"
LEDGER_DIR = JOURNAL_DIR / "ledger"
EQUITY_PATH = LEDGER_DIR / "equity_curve.csv"
ORDER_PATH = LEDGER_DIR / "orders.csv"
STAGES = ["preopen", "open", "midday", "afternoon", "close"]


def read_json(path: Path) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def stage_path(run_date: str, stage: str, root: Path = PIPELINE_RUNS_DIR) -> Path:
    return root / run_date / f"{stage}.json"


def load_stage_records(run_date: str, root: Path = PIPELINE_RUNS_DIR) -> Dict[str, Optional[Dict[str, object]]]:
    return {stage: read_json(stage_path(run_date, stage, root=root)) for stage in STAGES}


def available_run_dates(root: Path = PIPELINE_RUNS_DIR) -> List[str]:
    if not root.exists():
        return []
    dates = []
    for item in root.iterdir():
        if not item.is_dir():
            continue
        try:
            datetime.strptime(item.name, "%Y-%m-%d")
        except ValueError:
            continue
        if any(stage_path(item.name, stage, root=root).exists() for stage in STAGES):
            dates.append(item.name)
    return sorted(dates)


def latest_run_date_before_or_on(run_date: str, root: Path = PIPELINE_RUNS_DIR) -> Optional[str]:
    candidates = [item for item in available_run_dates(root=root) if item <= run_date]
    return candidates[-1] if candidates else None


def latest_equity_for_date(run_date: str, path: Path = EQUITY_PATH) -> Optional[Dict[str, str]]:
    if path == EQUITY_PATH:
        rows = [row for row in paper_account.equity_from_portfolio() if row.get("date") == run_date]
    else:
        rows = [row for row in read_csv(path) if row.get("date") == run_date]
    return rows[-1] if rows else None


def orders_for_date(run_date: str, path: Path = ORDER_PATH) -> List[Dict[str, str]]:
    if path == ORDER_PATH:
        return [row for row in paper_account.trades_from_portfolio() if row.get("date") == run_date]
    return [row for row in read_csv(path) if row.get("date") == run_date]


def failure_bucket(records: Dict[str, Optional[Dict[str, object]]]) -> str:
    existing = {stage: record for stage, record in records.items() if record is not None}
    if not existing:
        return "missing_pipeline_records"
    preopen = existing.get("preopen")
    if preopen and not preopen.get("ok"):
        cache_health = preopen.get("cache_health")
        if isinstance(cache_health, dict) and not cache_health.get("ok"):
            return "data_cache_unhealthy"
        return "preopen_failed"
    for stage in ("open", "midday", "afternoon", "close"):
        record = existing.get(stage)
        if record and not record.get("ok"):
            return f"{stage}_failed"
    return "pipeline_ok"


def action_from_bucket(bucket: str, equity: Optional[Dict[str, str]], orders: List[Dict[str, str]]) -> str:
    if bucket == "missing_pipeline_records":
        return "补齐五阶段 --record 自动化；没有记录就无法训练反馈模型。"
    if bucket == "data_cache_unhealthy":
        return "先修复行情缓存刷新或供应商推送，再允许策略优化/纸面执行。"
    if bucket.endswith("_failed"):
        return f"排查 {bucket.replace('_failed', '')} 阶段失败链路，保留原始 JSON 证据。"
    if equity and equity.get("risk_state") in {"ALERT", "STOP"}:
        return "账户风险状态触线，下一交易日降低策略晋级和新增仓位权限。"
    if not orders:
        return "流水线成功但无纸面成交，复核是否因阈值过严、股票池过窄或策略未触发。"
    return "保留当前纸面策略，继续积累样本；未满足长期稳定盈利证明前不进入真实交易。"


def review_pipeline_day(run_date: str, root: Path = PIPELINE_RUNS_DIR) -> Dict[str, object]:
    records = load_stage_records(run_date, root=root)
    present = [stage for stage, record in records.items() if record is not None]
    missing = [stage for stage, record in records.items() if record is None]
    bucket = failure_bucket(records)
    equity = latest_equity_for_date(run_date)
    orders = orders_for_date(run_date)
    stage_status = {
        stage: (
            "missing"
            if record is None
            else "ok"
            if record.get("ok")
            else "failed"
        )
        for stage, record in records.items()
    }
    return {
        "ok": bucket == "pipeline_ok",
        "reviewed_at": datetime.now().isoformat(timespec="seconds"),
        "run_date": run_date,
        "failure_bucket": bucket,
        "stage_status": stage_status,
        "present_stages": present,
        "missing_stages": missing,
        "order_count": len(orders),
        "equity": equity or {},
        "next_action": action_from_bucket(bucket, equity, orders),
        "risk_note": "仅用于训练/研究和纸面交易反馈，不构成投资建议、稳定盈利承诺或真实交易指令。",
    }


def render_review(review: Dict[str, object]) -> str:
    lines = [
        "A股日内流水线反馈",
        "==================",
        f"日期: {review.get('run_date')}",
        f"反馈桶: {review.get('failure_bucket')}",
        f"阶段状态: {review.get('stage_status')}",
        f"纸面成交数: {review.get('order_count')}",
        f"下一步: {review.get('next_action')}",
        "风险提示: 仅用于训练/研究和纸面交易反馈，不构成投资建议、稳定盈利承诺或真实交易指令。",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="复盘 A 股日内流水线运行记录")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    review = review_pipeline_day(args.date)
    if args.json:
        print(json.dumps(review, ensure_ascii=False, indent=2))
    else:
        print(render_review(review))
    return 0 if review.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
