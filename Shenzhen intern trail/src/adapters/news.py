from __future__ import annotations

import json
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ..config import Settings


def fetch_json(url: str, timeout: int = 10) -> Any:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_baidu_hot(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_baidu_hot:
        return [], {"source": "baidu_hot", "status": "disabled"}
    url = "https://top.baidu.com/board?tab=realtime"
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")
        # Baidu page is not a stable public JSON API. Keep titles from embedded text when available.
        items = []
        for marker in ["热搜", "财经", "股票", "半导体", "机器人", "AI", "低空经济", "新能源"]:
            if marker in html:
                items.append({"source": "baidu_hot", "title": marker, "summary": "百度热搜页面命中关键词", "published_at": now_iso()})
        return items[:10], {"source": "baidu_hot", "status": "ok", "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return [], {"source": "baidu_hot", "status": "blocked", "error": f"{type(exc).__name__}: {exc}"}


def fetch_google_trends(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_google_trends:
        return [], {"source": "google_trends", "status": "disabled"}
    # Public Google Trends daily feed is region specific and may be blocked; fail explicitly if inaccessible.
    url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=CN"
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=10) as response:
            text = response.read().decode("utf-8", errors="ignore")
        items = []
        for chunk in text.split("<item>")[1:11]:
            title = chunk.split("<title>", 1)[1].split("</title>", 1)[0] if "<title>" in chunk else ""
            if title:
                items.append({"source": "google_trends", "title": title, "summary": "Google Trends daily RSS", "published_at": now_iso()})
        return items, {"source": "google_trends", "status": "ok", "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return [], {"source": "google_trends", "status": "blocked", "error": f"{type(exc).__name__}: {exc}"}


def fetch_official_media(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_official_media:
        return [], {"source": "official_media", "status": "disabled"}
    feeds = [
        "http://www.news.cn/fortune/index.htm",
        "http://finance.people.com.cn/",
    ]
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in feeds:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=10) as response:
                text = response.read().decode("utf-8", errors="ignore")
            for keyword in ["人工智能", "半导体", "机器人", "低空经济", "新能源", "算力", "数据中心", "消费电子"]:
                if keyword in text:
                    items.append({"source": "official_media", "title": keyword, "summary": f"官媒页面 {url} 命中关键词", "published_at": now_iso()})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    status = "ok" if items else "blocked"
    return items[:20], {"source": "official_media", "status": status, "count": len(items), "errors": errors[:2]}


def normalize_news_item(source: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("title") or payload.get("content") or payload.get("news") or payload.get("text") or ""
    summary = payload.get("summary") or payload.get("content") or payload.get("text") or ""
    published_at = payload.get("published_at") or payload.get("time") or payload.get("datetime") or now_iso()
    return {"source": source, "title": str(title), "summary": str(summary), "published_at": str(published_at)}


def fetch_jin10(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_jin10 or settings.jin10_mode == "disabled":
        return [], {"source": "jin10", "status": "disabled", "reason": "set ENABLE_JIN10=true and JIN10_MODE=api/public"}
    if settings.jin10_mode == "api":
        if not settings.jin10_api_url:
            return [], {"source": "jin10", "status": "blocked", "reason": "JIN10_API_URL missing"}
        try:
            request = Request(settings.jin10_api_url, headers={"User-Agent": "Mozilla/5.0"})
            if settings.jin10_api_key:
                request.add_header("Authorization", f"Bearer {settings.jin10_api_key}")
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            rows = payload.get("data", payload) if isinstance(payload, dict) else payload
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("list") or []
            items = [normalize_news_item("jin10", row) for row in rows if isinstance(row, dict)]
            return items[:50], {"source": "jin10", "status": "ok", "mode": "api", "count": len(items)}
        except Exception as exc:  # noqa: BLE001
            return [], {"source": "jin10", "status": "blocked", "mode": "api", "error": f"{type(exc).__name__}: {exc}"}
    if settings.jin10_mode == "public":
        # Public site fallback is best-effort and should be treated as degraded, not equivalent to licensed API.
        try:
            request = Request("https://www.jin10.com/", headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=10) as response:
                html = response.read().decode("utf-8", errors="ignore")
            keywords = ["央行", "美联储", "黄金", "原油", "A股", "人工智能", "半导体", "新能源", "机器人"]
            items = [
                {"source": "jin10", "title": keyword, "summary": "金十公开页面命中关键词；非授权API，仅作降级信号", "published_at": now_iso()}
                for keyword in keywords
                if keyword in html
            ]
            return items[:20], {"source": "jin10", "status": "degraded", "mode": "public", "count": len(items)}
        except Exception as exc:  # noqa: BLE001
            return [], {"source": "jin10", "status": "blocked", "mode": "public", "error": f"{type(exc).__name__}: {exc}"}
    return [], {"source": "jin10", "status": "blocked", "reason": f"unknown JIN10_MODE={settings.jin10_mode}"}


def fetch_wind_from_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [normalize_news_item("wind", row) for row in rows]


def fetch_wind(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_wind or settings.wind_mode == "disabled":
        return [], {"source": "wind", "status": "disabled", "reason": "set ENABLE_WIND=true and WIND_MODE=windpy/csv"}
    if settings.wind_mode == "csv":
        if not settings.wind_csv_path:
            return [], {"source": "wind", "status": "blocked", "mode": "csv", "reason": "WIND_CSV_PATH missing"}
        path = Path(settings.wind_csv_path).expanduser()
        if not path.exists():
            return [], {"source": "wind", "status": "blocked", "mode": "csv", "reason": f"CSV not found: {path}"}
        try:
            items = fetch_wind_from_csv(path)
            return items[:100], {"source": "wind", "status": "ok", "mode": "csv", "count": len(items)}
        except Exception as exc:  # noqa: BLE001
            return [], {"source": "wind", "status": "blocked", "mode": "csv", "error": f"{type(exc).__name__}: {exc}"}
    if settings.wind_mode == "windpy":
        try:
            from WindPy import w  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return [], {"source": "wind", "status": "blocked", "mode": "windpy", "reason": f"WindPy unavailable: {type(exc).__name__}: {exc}"}
        try:
            started = w.start()
            if getattr(started, "ErrorCode", 0) not in (0, None):
                return [], {"source": "wind", "status": "blocked", "mode": "windpy", "reason": f"w.start ErrorCode={started.ErrorCode}"}
            # Wind news APIs vary by entitlement. Expose a clear adapter point instead of guessing silently.
            return [], {"source": "wind", "status": "blocked", "mode": "windpy", "reason": "WindPy available, but news query entitlement/function must be configured"}
        except Exception as exc:  # noqa: BLE001
            return [], {"source": "wind", "status": "blocked", "mode": "windpy", "error": f"{type(exc).__name__}: {exc}"}
    return [], {"source": "wind", "status": "blocked", "reason": f"unknown WIND_MODE={settings.wind_mode}"}


def collect_news(settings: Settings) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_items: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for fetcher in [fetch_jin10, fetch_wind, fetch_baidu_hot, fetch_google_trends, fetch_official_media]:
        items, status = fetcher(settings)
        all_items.extend(items)
        statuses.append(status)
    return all_items, statuses
