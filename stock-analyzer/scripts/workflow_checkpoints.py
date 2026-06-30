#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable checkpoint ledger for daily paper-trading workflow audits."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_DIR = ROOT / "trading-journal"
CHECKPOINT_PATH = JOURNAL_DIR / "workflow-checkpoints.csv"
PIPELINE_RUNS_DIR = JOURNAL_DIR / "pipeline-runs"

FIELDS = [
    "date",
    "checkpoint",
    "due_time",
    "status",
    "completed_at",
    "evidence",
    "notes",
]


@dataclass(frozen=True)
class CheckpointSpec:
    checkpoint: str
    due_time: str
    evidence: str
    notes: str


DEFAULT_CHECKPOINTS = [
    CheckpointSpec("preopen_plan", "08:50", "daily log / preopen pipeline record", "盘前计划、观察池、无效条件。"),
    CheckpointSpec("open_snapshot", "09:40", "open pipeline record / data-check output", "开盘行情和数据链路检查。"),
    CheckpointSpec("morning_review", "10:30", "manual review / intraday check row", "复核早盘触发、无效、止损纪律。"),
    CheckpointSpec("midday_plan", "12:10", "midday pipeline record / daily log", "上午结果和下午执行计划。"),
    CheckpointSpec("afternoon_review", "14:00", "afternoon pipeline record / intraday check row", "午后加减仓或继续观察复核。"),
    CheckpointSpec("close_settlement", "15:20", "DAY_SUMMARY / close pipeline record", "结算权益、现金、持仓、盈亏和风险状态。"),
    CheckpointSpec("post_close_audit", "16:30", "pipeline_review / ops report", "审计缺失阶段、失败链路和次日动作。"),
]

PIPELINE_CHECKPOINTS = {
    "preopen": "preopen_plan",
    "open": "open_snapshot",
    "midday": "midday_plan",
    "afternoon": "afternoon_review",
    "close": "close_settlement",
}


def ensure_parent(path: Path = CHECKPOINT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_rows(path: Path = CHECKPOINT_PATH) -> List[Dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(rows: Iterable[Dict[str, str]], path: Path = CHECKPOINT_PATH) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in FIELDS})


def seed_day(run_date: str, path: Path = CHECKPOINT_PATH) -> List[Dict[str, str]]:
    rows = read_rows(path)
    existing = {(row.get("date"), row.get("checkpoint")) for row in rows}
    added = []
    for spec in DEFAULT_CHECKPOINTS:
        key = (run_date, spec.checkpoint)
        if key in existing:
            continue
        added.append(
            {
                "date": run_date,
                "checkpoint": spec.checkpoint,
                "due_time": spec.due_time,
                "status": "pending",
                "completed_at": "",
                "evidence": spec.evidence,
                "notes": spec.notes,
            }
        )
    if added:
        rows.extend(added)
        write_rows(rows, path)
    return [row for row in rows if row.get("date") == run_date]


def parse_dt(run_date: str, due_time: str) -> datetime:
    return datetime.strptime(f"{run_date} {due_time}", "%Y-%m-%d %H:%M")


def infer_status(row: Dict[str, str], now: datetime) -> str:
    status = row.get("status") or "pending"
    if status in {"done", "waived", "failed"}:
        return status
    due = parse_dt(row["date"], row["due_time"])
    return "overdue" if now > due else "pending"


def audit_day(
    run_date: str,
    *,
    path: Path = CHECKPOINT_PATH,
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    current = now or datetime.now()
    rows = seed_day(run_date, path)
    updated = []
    counts = {"done": 0, "pending": 0, "overdue": 0, "failed": 0, "waived": 0}
    for row in rows:
        row = dict(row)
        row["status"] = infer_status(row, current)
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        updated.append(row)
    all_rows = [row for row in read_rows(path) if row.get("date") != run_date] + updated
    write_rows(all_rows, path)
    return {
        "date": run_date,
        "audited_at": current.isoformat(timespec="seconds"),
        "counts": counts,
        "missing": [row for row in updated if row.get("status") in {"pending", "overdue", "failed"}],
        "rows": updated,
    }


def mark_checkpoint(
    run_date: str,
    checkpoint: str,
    *,
    status: str = "done",
    evidence: str = "",
    notes: str = "",
    completed_at: Optional[str] = None,
    path: Path = CHECKPOINT_PATH,
) -> Dict[str, str]:
    if status not in {"done", "failed", "waived", "pending"}:
        raise ValueError("status must be done, failed, waived, or pending")
    seed_day(run_date, path)
    rows = read_rows(path)
    updated: Optional[Dict[str, str]] = None
    for row in rows:
        if row.get("date") == run_date and row.get("checkpoint") == checkpoint:
            row["status"] = status
            row["completed_at"] = completed_at or datetime.now().isoformat(timespec="seconds")
            if evidence:
                row["evidence"] = evidence
            if notes:
                row["notes"] = notes
            updated = row
            break
    if updated is None:
        raise ValueError(f"unknown checkpoint for {run_date}: {checkpoint}")
    write_rows(rows, path)
    return updated


def stage_path(run_date: str, stage: str, root: Path = PIPELINE_RUNS_DIR) -> Path:
    return root / run_date / f"{stage}.json"


def import_pipeline_records(
    run_date: str,
    *,
    root: Path = PIPELINE_RUNS_DIR,
    path: Path = CHECKPOINT_PATH,
) -> List[Dict[str, str]]:
    marked = []
    for stage, checkpoint in PIPELINE_CHECKPOINTS.items():
        record_path = stage_path(run_date, stage, root=root)
        if not record_path.exists():
            continue
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        status = "done" if payload.get("ok") else "failed"
        marked.append(
            mark_checkpoint(
                run_date,
                checkpoint,
                status=status,
                evidence=str(record_path),
                notes=f"pipeline {stage} {'ok' if status == 'done' else 'failed'}",
                path=path,
            )
        )
    return marked


def render_audit(audit: Dict[str, object]) -> str:
    counts = audit["counts"]
    lines = [
        "A股每日流程检查",
        "==============",
        f"日期: {audit['date']}",
        f"统计: done={counts.get('done', 0)}, pending={counts.get('pending', 0)}, overdue={counts.get('overdue', 0)}, failed={counts.get('failed', 0)}, waived={counts.get('waived', 0)}",
    ]
    missing = audit.get("missing") or []
    if missing:
        lines.append("未闭环检查点:")
        for row in missing:
            lines.append(f"- {row['checkpoint']} {row['due_time']} {row['status']}: {row.get('notes', '')}")
    else:
        lines.append("未闭环检查点: 无")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="维护每日纸面交易流程检查账本")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="为指定日期生成默认检查点")
    seed.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))

    audit = sub.add_parser("audit", help="审计指定日期的未完成检查点")
    audit.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    audit.add_argument("--json", action="store_true")

    mark = sub.add_parser("mark", help="标记一个检查点")
    mark.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    mark.add_argument("--checkpoint", required=True)
    mark.add_argument("--status", choices=["done", "failed", "waived", "pending"], default="done")
    mark.add_argument("--evidence", default="")
    mark.add_argument("--notes", default="")

    ingest = sub.add_parser("import-pipeline", help="用已记录的 pipeline JSON 自动标记检查点")
    ingest.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))

    args = parser.parse_args(argv)
    if args.command == "seed":
        rows = seed_day(args.date)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if args.command == "audit":
        result = audit_day(args.date)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(render_audit(result))
        return 0 if not result.get("missing") else 2
    if args.command == "mark":
        row = mark_checkpoint(
            args.date,
            args.checkpoint,
            status=args.status,
            evidence=args.evidence,
            notes=args.notes,
        )
        print(json.dumps(row, ensure_ascii=False, indent=2))
        return 0
    if args.command == "import-pipeline":
        rows = import_pipeline_records(args.date)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
