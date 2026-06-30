from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .adapters.deepseek import DeepSeekError, analyze_news_with_deepseek, check_deepseek
from .adapters.eastmoney import build_market_snapshot, fetch_realtime_rows
from .adapters.news import collect_news
from .config import load_settings
from .pipeline import load_market_snapshot, load_news, run_pipeline
from .report import write_html_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Shenzhen intern trail stock screener")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the local-file pipeline for tests/demo only")
    run_parser.add_argument("--news", required=True, type=Path, help="Normalized news JSON path")
    run_parser.add_argument("--market", required=True, type=Path, help="Market snapshot CSV path")
    run_parser.add_argument("--out", type=Path, help="Optional JSON output path")

    subparsers.add_parser("doctor", help="Check env, DeepSeek, and data source readiness")

    scan_parser = subparsers.add_parser("scan", help="Run one production scan with real adapters")
    scan_parser.add_argument("--runs-dir", default=Path("runs"), type=Path)
    scan_parser.add_argument("--timezone", default="Asia/Shanghai")
    scan_parser.add_argument("--allow-degraded", action="store_true", help="Allow market scan when some optional news sources are blocked")

    watch_parser = subparsers.add_parser("watch", help="Run production scan every N minutes")
    watch_parser.add_argument("--interval-minutes", type=int, default=None)
    watch_parser.add_argument("--runs-dir", default=Path("runs"), type=Path)
    watch_parser.add_argument("--timezone", default="Asia/Shanghai")
    watch_parser.add_argument("--max-runs", type=int, default=0, help="Testing guard; 0 means run forever")
    watch_parser.add_argument("--allow-degraded", action="store_true")

    daily_parser = subparsers.add_parser("daily", help="Deprecated demo update; use scan/watch for production")
    daily_parser.add_argument("--news", default=Path("data/examples/news_items.json"), type=Path)
    daily_parser.add_argument("--market", default=Path("data/examples/market_snapshot.csv"), type=Path)
    daily_parser.add_argument("--runs-dir", default=Path("runs"), type=Path)
    daily_parser.add_argument("--timezone", default="Asia/Shanghai")
    return parser


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def execute_run(news_path: Path, market_path: Path) -> dict:
    news_items = load_news(news_path)
    stocks = load_market_snapshot(market_path)
    return run_pipeline(news_items, stocks)


def command_doctor() -> int:
    settings = load_settings()
    checks = []
    checks.append({"name": ".env", "ok": (settings.project_root / ".env").exists()})
    checks.append({"name": "DEEPSEEK_API_KEY", "ok": bool(settings.deepseek_api_key)})
    ok, message = check_deepseek(settings)
    checks.append({"name": "DeepSeek", "ok": ok, "message": message})
    try:
        rows = fetch_realtime_rows(max_pages=1)
        checks.append({"name": "Eastmoney realtime", "ok": bool(rows), "rows": len(rows)})
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "Eastmoney realtime", "ok": False, "message": f"{type(exc).__name__}: {exc}"})
    news_items, statuses = collect_news(settings)
    checks.append({"name": "News adapters", "ok": bool(news_items), "statuses": statuses})
    blocked = [check for check in checks if not check.get("ok")]
    result = {"strict_status": "PASS" if not blocked else "BLOCKED", "checks": checks}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not blocked else 2


def hot_terms_from_deepseek(analysis: dict) -> list[str]:
    terms: list[str] = []
    for theme in analysis.get("hot_themes", []) or []:
        value = theme.get("theme") if isinstance(theme, dict) else str(theme)
        if value:
            terms.append(str(value))
    for stock in analysis.get("mentioned_stocks", []) or []:
        if not isinstance(stock, dict):
            continue
        for key in ["code", "name", "theme"]:
            value = stock.get(key)
            if value:
                terms.append(str(value))
    return list(dict.fromkeys(terms))


def command_scan(runs_dir: Path, timezone: str, allow_degraded: bool = False) -> dict:
    settings = load_settings()
    now = datetime.now(ZoneInfo(timezone))
    run_date = now.strftime("%Y-%m-%d")
    run_slot = now.strftime("%H%M")
    source_statuses = []

    if not settings.deepseek_api_key:
        result = blocked_result(now, "DEEPSEEK_API_KEY missing", source_statuses)
        persist_scan_outputs(runs_dir, run_date, run_slot, result)
        return result

    news_items, news_statuses = collect_news(settings)
    source_statuses.extend(news_statuses)
    if settings.strict_news_required and not news_items:
        result = blocked_result(now, "No real news source available; refusing to use examples", source_statuses)
        persist_scan_outputs(runs_dir, run_date, run_slot, result)
        return result

    try:
        news_analysis = analyze_news_with_deepseek(settings, news_items)
        source_statuses.append({"source": "deepseek", "status": "ok", "model": settings.deepseek_model})
    except DeepSeekError as exc:
        result = blocked_result(now, str(exc), source_statuses + [{"source": "deepseek", "status": "blocked"}])
        persist_scan_outputs(runs_dir, run_date, run_slot, result)
        return result

    hot_terms = hot_terms_from_deepseek(news_analysis)
    try:
        rows = fetch_realtime_rows()
        stocks, market_meta = build_market_snapshot(rows, hot_terms)
        source_statuses.append({"source": "eastmoney", "status": "ok", **market_meta})
    except Exception as exc:  # noqa: BLE001
        result = blocked_result(now, f"Market adapter failed: {type(exc).__name__}: {exc}", source_statuses)
        persist_scan_outputs(runs_dir, run_date, run_slot, result)
        return result

    pipeline_news = [
        {
            "source": item.get("source", "news"),
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "published_at": item.get("published_at", ""),
        }
        for item in news_items
    ]
    result = run_pipeline(load_news_items_from_dicts(pipeline_news), stocks)
    result.update(
        {
            "strict_status": "PASS" if result.get("buy_plans") else "NO_SIGNAL",
            "run_timestamp": now.isoformat(timespec="seconds"),
            "run_date": run_date,
            "run_slot": run_slot,
            "source_statuses": source_statuses,
            "deepseek_analysis": news_analysis,
            "production_note": "Production scan used real adapters; data/examples are not used.",
        }
    )
    persist_scan_outputs(runs_dir, run_date, run_slot, result)
    return result


def load_news_items_from_dicts(items: list[dict]) -> list:
    from .models import NewsItem

    return [NewsItem(source=str(item.get("source", "")), title=str(item.get("title", "")), summary=str(item.get("summary", "")), published_at=str(item.get("published_at", ""))) for item in items]


def blocked_result(now: datetime, reason: str, source_statuses: list[dict]) -> dict:
    return {
        "system": "Shenzhen intern trail",
        "strict_status": "BLOCKED",
        "run_timestamp": now.isoformat(timespec="seconds"),
        "blocked_reason": reason,
        "source_statuses": source_statuses,
        "hot_pool": [],
        "layer_results": [],
        "buy_plans": [],
        "risk_note": "研究用途，不构成投资建议；未满足生产门禁，不输出买入计划。",
    }


def persist_scan_outputs(runs_dir: Path, run_date: str, run_slot: str, result: dict) -> None:
    dated = runs_dir / run_date / f"{run_slot}.json"
    latest = runs_dir / "latest.json"
    write_json(dated, result)
    write_json(latest, result)
    write_html_report(runs_dir / "latest.html", result)


def command_watch(interval_minutes: int | None, runs_dir: Path, timezone: str, max_runs: int, allow_degraded: bool) -> int:
    settings = load_settings()
    interval = interval_minutes or settings.scan_interval_minutes
    runs = 0
    while True:
        result = command_scan(runs_dir, timezone, allow_degraded)
        print(json.dumps({"run_timestamp": result.get("run_timestamp"), "strict_status": result.get("strict_status"), "buy_plan_count": len(result.get("buy_plans", []))}, ensure_ascii=False))
        runs += 1
        if max_runs and runs >= max_runs:
            return 0
        time.sleep(interval * 60)


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "run":
        result = execute_run(args.news, args.market)
        if args.out:
            write_json(args.out, result)
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "doctor":
        return command_doctor()
    elif args.command == "scan":
        result = command_scan(args.runs_dir, args.timezone, args.allow_degraded)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("strict_status") != "BLOCKED" else 2
    elif args.command == "watch":
        return command_watch(args.interval_minutes, args.runs_dir, args.timezone, args.max_runs, args.allow_degraded)
    elif args.command == "daily":
        now = datetime.now(ZoneInfo(args.timezone))
        run_date = now.strftime("%Y-%m-%d")
        result = execute_run(args.news, args.market)
        result["run_date"] = run_date
        result["run_timestamp"] = now.isoformat(timespec="seconds")
        result["daily_update_note"] = "deprecated demo update; use scan/watch for production"
        write_json(args.runs_dir / run_date / "latest.json", result)
        write_json(args.runs_dir / "latest.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
