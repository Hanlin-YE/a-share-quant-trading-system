from __future__ import annotations

import csv
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _curl_text(url: str, timeout: int = 8, encoding: str = "utf-8", referer: str = "") -> str:
    cmd = ["curl", "-sS", "-L", "-m", str(timeout), "-A", _UA]
    if referer:
        cmd += ["-H", f"Referer: {referer}"]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, timeout=timeout + 4)
    return result.stdout.decode(encoding, errors="ignore")


def _curl_json(url: str, timeout: int = 8, referer: str = "") -> Any:
    text = _curl_text(url, timeout, referer=referer)
    if not text.strip() or "<html" in text[:50].lower():
        raise RuntimeError(f"non-json response (len={len(text)})")
    return json.loads(text)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_baidu_hot(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_baidu_hot:
        return [], {"source": "baidu_hot", "status": "disabled"}
    try:
        payload = _curl_json("https://top.baidu.com/api/board?platform=wise&tab=realtime", referer="https://top.baidu.com/")
        items: list[dict[str, Any]] = []
        for card in payload.get("data", {}).get("cards", []):
            for group in card.get("content", []):
                for content in group.get("content", []):
                    title = content.get("word") or content.get("query") or content.get("name") or ""
                    desc = content.get("desc", "")
                    if title:
                        items.append({"source": "baidu_hot", "title": str(title), "summary": str(desc), "published_at": now_iso()})
        return items[:10], {"source": "baidu_hot", "status": "ok", "count": len(items[:10])}
    except Exception as exc:  # noqa: BLE001
        return [], {"source": "baidu_hot", "status": "blocked", "error": f"{type(exc).__name__}: {exc}"}


def fetch_toutiao_hot(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_toutiao_hot:
        return [], {"source": "toutiao_hot", "status": "disabled"}
    try:
        payload = _curl_json("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc")
        items: list[dict[str, Any]] = []
        for entry in payload.get("data", [])[:10]:
            title = entry.get("Title") or entry.get("title") or ""
            cluster = entry.get("ClusterIdStr") or entry.get("ClusterId") or ""
            if title:
                items.append({"source": "toutiao_hot", "title": str(title), "summary": f"头条热搜 cluster={cluster}", "published_at": now_iso()})
        return items, {"source": "toutiao_hot", "status": "ok", "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return [], {"source": "toutiao_hot", "status": "blocked", "error": f"{type(exc).__name__}: {exc}"}


def fetch_google_trends(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_google_trends:
        return [], {"source": "google_trends", "status": "disabled"}
    try:
        text = _curl_text("https://trends.google.com/trends/trendingsearches/daily/rss?geo=CN")
        items = []
        for chunk in text.split("<item>")[1:11]:
            title = chunk.split("<title>", 1)[1].split("</title>", 1)[0] if "<title>" in chunk else ""
            if title:
                items.append({"source": "google_trends", "title": title, "summary": "Google Trends daily RSS", "published_at": now_iso()})
        return items, {"source": "google_trends", "status": "ok", "count": len(items)}
    except Exception as exc:  # noqa: BLE001
        return [], {"source": "google_trends", "status": "blocked", "error": f"{type(exc).__name__}: {exc}"}


def _extract_titles_from_html(html_text: str, source_url: str) -> list[dict[str, Any]]:
    """从新闻列表页 HTML 提取真实标题（<a>标签文本），过滤导航类，保留含财经关键词的。"""
    finance_keywords = ["股", "债", "基金", "经济", "金融", "央行", "科技", "半导", "芯片", "AI", "人工", "机器",
                        "新能", "锂电", "光伏", "算力", "数据", "消费", "医药", "生物", "军工", "航天", "低空",
                        "政策", "改革", "投资", "产业", "制造", "汽车", "数字", "绿电", "储能", "材料"]
    raw_titles = re.findall(r"<a[^>]*>([^<]{6,50})</a>", html_text)
    seen = set()
    items = []
    for title in raw_titles:
        clean = title.strip()
        if not clean or clean in seen:
            continue
        if not any(kw in clean for kw in finance_keywords):
            continue
        seen.add(clean)
        items.append({"source": "official_media", "title": clean, "summary": f"官媒列表页 {source_url}", "published_at": now_iso()})
    return items


def fetch_official_media(settings: Settings) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not settings.enable_official_media:
        return [], {"source": "official_media", "status": "disabled"}
    feeds = ["http://www.news.cn/fortune/index.htm", "http://finance.people.com.cn/"]
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in feeds:
        try:
            text = _curl_text(url, timeout=10)
            extracted = _extract_titles_from_html(text, url)
            items.extend(extracted)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    # 去重
    seen = set()
    deduped = []
    for item in items:
        if item["title"] not in seen:
            seen.add(item["title"])
            deduped.append(item)
    status = "ok" if deduped else "blocked"
    return deduped[:20], {"source": "official_media", "status": status, "count": len(deduped), "errors": errors[:2]}


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
            payload = _curl_json(settings.jin10_api_url)
            rows = payload.get("data", payload) if isinstance(payload, dict) else payload
            if isinstance(rows, dict):
                rows = rows.get("items") or rows.get("list") or []
            items = [normalize_news_item("jin10", row) for row in rows if isinstance(row, dict)]
            return items[:50], {"source": "jin10", "status": "ok", "mode": "api", "count": len(items)}
        except Exception as exc:  # noqa: BLE001
            return [], {"source": "jin10", "status": "blocked", "mode": "api", "error": f"{type(exc).__name__}: {exc}"}
    if settings.jin10_mode == "public":
        try:
            html = _curl_text("https://www.jin10.com/")
            keywords = ["央行", "美联储", "黄金", "原油", "A股", "人工智能", "半导体", "新能源", "机器人"]
            items = [{"source": "jin10", "title": kw, "summary": "金十公开页面命中关键词；非授权API，仅作降级信号", "published_at": now_iso()} for kw in keywords if kw in html]
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
            return [], {"source": "wind", "status": "blocked", "mode": "windpy", "reason": "WindPy available, but news query entitlement/function must be configured"}
        except Exception as exc:  # noqa: BLE001
            return [], {"source": "wind", "status": "blocked", "mode": "windpy", "error": f"{type(exc).__name__}: {exc}"}
    return [], {"source": "wind", "status": "blocked", "reason": f"unknown WIND_MODE={settings.wind_mode}"}


def collect_news(settings: Settings) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_items: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for fetcher in [fetch_jin10, fetch_wind, fetch_baidu_hot, fetch_toutiao_hot, fetch_google_trends, fetch_official_media]:
        items, status = fetcher(settings)
        all_items.extend(items)
        statuses.append(status)
    return all_items, statuses
