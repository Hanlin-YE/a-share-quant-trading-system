#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Import Shenzhen intern trail buy plans into the paper-trading ledger.

The Shenzhen screener remains an independent research input. This bridge only
creates TRADE_PLAN rows; it never records executed trades.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import paper_account


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_PATH = ROOT / "Shenzhen intern trail" / "runs" / "latest.json"
STRATEGY_ID = "shenzhen-intern-trail-v1"


def load_payload(path: Path) -> Dict[str, object]:
    if not path.exists():
        raise FileNotFoundError(f"Shenzhen trail run not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Shenzhen trail run must be a JSON object: {path}")
    return payload


def imported_key(row: Dict[str, str]) -> tuple[str, str, str, str]:
    return (
        row.get("date", ""),
        row.get("row_type", ""),
        row.get("symbol", ""),
        row.get("strategy_id", ""),
    )


def existing_import_keys(rows: List[Dict[str, str]]) -> set[tuple[str, str, str, str]]:
    return {
        imported_key(row)
        for row in rows
        if row.get("row_type") == "TRADE_PLAN" and row.get("strategy_id") == STRATEGY_ID
    }


def plan_to_ledger_row(plan: Dict[str, object], payload: Dict[str, object], run_path: Path) -> Dict[str, object]:
    run_date = str(payload.get("run_date") or datetime.now().strftime("%Y-%m-%d"))
    run_time = str(payload.get("run_slot") or "")
    if len(run_time) == 4 and run_time.isdigit():
        run_time = f"{run_time[:2]}:{run_time[2:]}"
    symbol = str(plan.get("code") or "").zfill(6)
    name = str(plan.get("name") or "")
    trigger = str(plan.get("trigger") or "")
    limit_price = plan.get("limit_price") or ""
    leader_rank = plan.get("leader_rank") or ""
    hot_reason = str(plan.get("reason") or "")
    risk_note = str(plan.get("risk_note") or "")
    fallback_from = str(plan.get("fallback_from") or "")
    thesis_parts = [
        f"trigger={trigger}",
        f"leader_rank={leader_rank}",
        f"pct_change_at_plan={plan.get('pct_change_at_plan', '')}",
    ]
    if fallback_from:
        thesis_parts.append(f"fallback_from={fallback_from}")
    return {
        "date": run_date,
        "section": f"{run_date} 深圳实习生选股计划",
        "row_type": "TRADE_PLAN",
        "time": run_time,
        "symbol": symbol,
        "name": name,
        "side": "BUY",
        "action": "深圳实习生选股观察计划",
        "quantity": "",
        "price": limit_price,
        "gross_amount": "",
        "strategy_tag": STRATEGY_ID,
        "strategy_id": STRATEGY_ID,
        "score_profile": "Shenzhen intern trail: news + technical + volume + dragon-two plan",
        "factor_weights": json.dumps(payload.get("thresholds", {}), ensure_ascii=False, sort_keys=True),
        "strategy_status": str(payload.get("strict_status") or ""),
        "reason": hot_reason,
        "thesis": "；".join(thesis_parts),
        "review_date": run_date,
        "status": "pending",
        "notes": (
            f"{risk_note}；source={run_path}; production_note={payload.get('production_note', '')}; "
            "仅导入为TRADE_PLAN，不自动成交。"
        ),
    }


def import_plans(run_path: Path = DEFAULT_RUN_PATH, *, sync_workbook: bool = True) -> Dict[str, object]:
    payload = load_payload(run_path)
    plans = payload.get("buy_plans") or []
    if not isinstance(plans, list):
        raise ValueError("Shenzhen trail payload field buy_plans must be a list")

    paper_account.ensure_ledger_files()
    rows = paper_account.read_rows(paper_account.PORTFOLIO_LEDGER_PATH)
    existing = existing_import_keys(rows)
    appended: List[Dict[str, object]] = []
    skipped: List[Dict[str, object]] = []
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        row = plan_to_ledger_row(plan, payload, run_path)
        key = imported_key(
            {
                "date": str(row.get("date", "")),
                "row_type": str(row.get("row_type", "")),
                "symbol": str(row.get("symbol", "")),
                "strategy_id": str(row.get("strategy_id", "")),
            }
        )
        if key in existing:
            skipped.append(row)
            continue
        paper_account.append_portfolio_row(row)
        existing.add(key)
        appended.append(row)

    if appended:
        paper_account.sync_compatibility_ledgers()
    if sync_workbook:
        paper_account.sync_workbook()

    return {
        "ok": True,
        "source": str(run_path),
        "run_date": payload.get("run_date", ""),
        "strict_status": payload.get("strict_status", ""),
        "plan_count": len(plans),
        "appended_count": len(appended),
        "skipped_existing_count": len(skipped),
        "appended": appended,
        "risk_note": "深圳实习生选股仅接入为研究/计划，不构成投资建议或真实交易指令。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Shenzhen intern trail plans into portfolio ledger")
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN_PATH, help="Shenzhen trail JSON run path")
    parser.add_argument("--no-sync-workbook", action="store_true")
    args = parser.parse_args()
    result = import_plans(args.run, sync_workbook=not args.no_sync_workbook)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
