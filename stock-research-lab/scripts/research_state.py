#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local stock research state manager.

Stores watchlist and thesis records as JSON under ../state by default.
This is intentionally small and deterministic so the skill can preserve
research assets without requiring an external data service.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_STATE_DIR = SCRIPT_DIR.parent / "state"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_ticker(value: str) -> str:
    text = value.strip().upper()
    match = re.search(r"(\d{6})", text)
    if match:
        return match.group(1)
    return text


def state_path(state_dir: Path, name: str) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{name}.json"


def load_state(state_dir: Path, name: str) -> Dict[str, object]:
    path = state_path(state_dir, name)
    if not path.exists():
        return {"records": []}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError(f"state file is invalid: {path}")
    return data


def save_state(state_dir: Path, name: str, data: Dict[str, object]) -> None:
    path = state_path(state_dir, name)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def upsert(records: List[Dict[str, object]], ticker: str, payload: Dict[str, object]) -> Dict[str, object]:
    for record in records:
        if record.get("ticker") == ticker:
            record.update(payload)
            record["updated_at"] = now_iso()
            return record
    record = {"ticker": ticker, "created_at": now_iso(), "updated_at": now_iso(), **payload}
    records.append(record)
    return record


def remove(records: List[Dict[str, object]], ticker: str) -> bool:
    before = len(records)
    records[:] = [record for record in records if record.get("ticker") != ticker]
    return len(records) < before


def cmd_watchlist(args: argparse.Namespace) -> int:
    data = load_state(args.state_dir, "watchlist")
    records: List[Dict[str, object]] = data["records"]  # type: ignore[assignment]
    if args.action == "add":
        ticker = clean_ticker(args.ticker)
        record = upsert(records, ticker, {"note": args.note or "", "tags": args.tags or []})
        save_state(args.state_dir, "watchlist", data)
        print(json.dumps({"ok": True, "record": record}, ensure_ascii=False, indent=2))
        return 0
    if args.action == "remove":
        ticker = clean_ticker(args.ticker)
        ok = remove(records, ticker)
        save_state(args.state_dir, "watchlist", data)
        print(json.dumps({"ok": ok, "ticker": ticker}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_thesis(args: argparse.Namespace) -> int:
    data = load_state(args.state_dir, "theses")
    records: List[Dict[str, object]] = data["records"]  # type: ignore[assignment]
    if args.action == "add":
        ticker = clean_ticker(args.ticker)
        payload = {
            "status": "active",
            "thesis": args.thesis,
            "sell_conditions": [item for item in (args.sell or []) if item],
            "evidence_date": args.evidence_date or "",
            "notes": args.note or "",
        }
        record = upsert(records, ticker, payload)
        save_state(args.state_dir, "theses", data)
        print(json.dumps({"ok": True, "record": record}, ensure_ascii=False, indent=2))
        return 0
    if args.action == "close":
        ticker = clean_ticker(args.ticker)
        for record in records:
            if record.get("ticker") == ticker:
                record["status"] = "closed"
                record["close_reason"] = args.reason or ""
                record["updated_at"] = now_iso()
                save_state(args.state_dir, "theses", data)
                print(json.dumps({"ok": True, "record": record}, ensure_ascii=False, indent=2))
                return 0
        print(json.dumps({"ok": False, "error": "thesis not found", "ticker": ticker}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def health_band(score: int) -> str:
    if score >= 85:
        return "healthy"
    if score >= 65:
        return "needs-review"
    return "at-risk"


def cmd_health(args: argparse.Namespace) -> int:
    watchlist = load_state(args.state_dir, "watchlist")["records"]
    theses = load_state(args.state_dir, "theses")["records"]
    watch_tickers = {record.get("ticker") for record in watchlist}
    thesis_tickers = {record.get("ticker") for record in theses if record.get("status") == "active"}
    orphan_watch = sorted(str(ticker) for ticker in watch_tickers - thesis_tickers if ticker)
    thesis_without_watch = sorted(str(ticker) for ticker in thesis_tickers - watch_tickers if ticker)
    missing_sell = sorted(
        str(record.get("ticker"))
        for record in theses
        if record.get("status") == "active" and not record.get("sell_conditions")
    )
    issue_count = len(orphan_watch) + len(thesis_without_watch) + len(missing_sell)
    score = max(0, 100 - issue_count * 12)
    result = {
        "report_date": now_iso(),
        "score": score,
        "band": health_band(score),
        "counts": {
            "watchlist": len(watchlist),
            "active_theses": len(thesis_tickers),
            "orphan_watchlist_items": len(orphan_watch),
            "theses_without_watchlist": len(thesis_without_watch),
            "theses_missing_sell_conditions": len(missing_sell),
        },
        "top_actions": [],
    }
    actions = result["top_actions"]
    if orphan_watch:
        actions.append({"action": "write_or_link_thesis", "tickers": orphan_watch, "reason": "watchlist item has no active thesis"})
    if thesis_without_watch:
        actions.append({"action": "add_to_watchlist_or_close", "tickers": thesis_without_watch, "reason": "active thesis is not monitored"})
    if missing_sell:
        actions.append({"action": "add_sell_conditions", "tickers": missing_sell, "reason": "active thesis has no explicit exit rule"})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local stock research state")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR, help="state directory")
    sub = parser.add_subparsers(dest="command", required=True)

    watch = sub.add_parser("watchlist")
    watch_sub = watch.add_subparsers(dest="action", required=True)
    watch_add = watch_sub.add_parser("add")
    watch_add.add_argument("--ticker", required=True)
    watch_add.add_argument("--note", default="")
    watch_add.add_argument("--tags", action="append", default=[])
    watch_remove = watch_sub.add_parser("remove")
    watch_remove.add_argument("--ticker", required=True)
    watch_sub.add_parser("list")
    watch.set_defaults(func=cmd_watchlist)

    thesis = sub.add_parser("thesis")
    thesis_sub = thesis.add_subparsers(dest="action", required=True)
    thesis_add = thesis_sub.add_parser("add")
    thesis_add.add_argument("--ticker", required=True)
    thesis_add.add_argument("--thesis", required=True)
    thesis_add.add_argument("--sell", action="append", default=[])
    thesis_add.add_argument("--evidence-date", default="")
    thesis_add.add_argument("--note", default="")
    thesis_close = thesis_sub.add_parser("close")
    thesis_close.add_argument("--ticker", required=True)
    thesis_close.add_argument("--reason", default="")
    thesis_sub.add_parser("list")
    thesis.set_defaults(func=cmd_thesis)

    health = sub.add_parser("health")
    health.set_defaults(func=cmd_health)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
