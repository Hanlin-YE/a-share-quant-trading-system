from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import MarketStock

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
FIELDS = "f12,f13,f14,f2,f3,f4,f5,f6,f8,f10,f62,f100,f102,f103,f184"


def fetch_json(url: str, params: dict[str, Any], timeout: int = 12) -> dict[str, Any]:
    request = Request(url + "?" + urlencode(params), headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_realtime_rows(max_pages: int = 20, stop_pct_below: float = 6.5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "pn": page,
            "pz": 100,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": FIELDS,
        }
        page_rows = fetch_json(CLIST_URL, params).get("data", {}).get("diff", []) or []
        rows.extend(page_rows)
        if not page_rows:
            break
        min_pct = min(float(row.get("f3") or -999) for row in page_rows)
        if min_pct < stop_pct_below:
            break
        time.sleep(0.05)
    return rows


def is_limit_up(row: dict[str, Any]) -> bool:
    code = str(row.get("f12", ""))
    pct = float(row.get("f3") or 0)
    if code.startswith(("300", "301", "688")):
        return pct >= 19.8
    if code.startswith(("8", "4")):
        return pct >= 29.0
    return pct >= 9.8


def row_themes(row: dict[str, Any]) -> list[str]:
    themes: list[str] = []
    for key in ["f100", "f103"]:
        value = row.get(key)
        if value and value != "-":
            themes.extend(part.strip() for part in str(value).split(",") if part.strip())
    return list(dict.fromkeys(themes))


def secid(row: dict[str, Any]) -> str:
    code = str(row.get("f12"))
    market = row.get("f13")
    if market in (0, 1):
        return f"{market}.{code}"
    return ("1." if code.startswith(("6", "9", "688")) else "0.") + code


def fetch_kline(row: dict[str, Any], limit: int = 140) -> list[dict[str, float | str]]:
    params = {
        "secid": secid(row),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": 101,
        "fqt": 1,
        "end": "20500101",
        "lmt": limit,
    }
    klines = fetch_json(KLINE_URL, params).get("data", {}).get("klines", []) or []
    parsed = []
    for line in klines:
        parts = line.split(",")
        parsed.append({"date": parts[0], "close": float(parts[2]), "volume": float(parts[5])})
    return parsed


def moving_average(values: list[float], n: int) -> float:
    if len(values) < n:
        return 0.0
    return sum(values[-n:]) / n


def consecutive_down_days(closes: list[float]) -> int:
    down = 0
    for index in range(len(closes) - 1, 0, -1):
        if closes[index] < closes[index - 1]:
            down += 1
        else:
            break
    return down


def build_market_snapshot(rows: list[dict[str, Any]], hot_terms: list[str]) -> tuple[list[MarketStock], dict[str, Any]]:
    hot_set = {term for term in hot_terms if term}
    anchors = [row for row in rows if is_limit_up(row)]
    anchor_by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in anchors:
        for theme in row_themes(row):
            anchor_by_theme[theme].append(row)

    selected_rows: list[dict[str, Any]] = []
    for row in rows:
        themes = row_themes(row)
        if hot_set and not hot_set.intersection(themes + [str(row.get("f14", "")), str(row.get("f12", ""))]):
            continue
        if is_limit_up(row):
            selected_rows.append(row)
            continue
        if not any(theme in anchor_by_theme for theme in themes):
            continue
        pct = float(row.get("f3") or 0)
        if not (5.0 <= pct <= 8.5):
            continue
        selected_rows.append(row)

    stocks: list[MarketStock] = []
    ranking_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected_rows:
        for theme in row_themes(row):
            ranking_groups[theme].append(row)
    rank_by_code: dict[str, int] = {}
    for group_rows in ranking_groups.values():
        ranked = sorted(group_rows, key=lambda item: float(item.get("f3") or 0), reverse=True)
        for idx, row in enumerate(ranked[:5], start=1):
            code = str(row.get("f12"))
            rank_by_code[code] = min(rank_by_code.get(code, idx), idx) if code in rank_by_code else idx

    for row in selected_rows:
        try:
            klines = fetch_kline(row)
        except Exception:
            klines = []
        closes = [float(item["close"]) for item in klines]
        volumes = [float(item["volume"]) for item in klines]
        volume = volumes[-1] if volumes else float(row.get("f5") or 0)
        volume_ma4 = moving_average(volumes, 4)
        volume_ma11 = moving_average(volumes, 11)
        volume_ma117 = moving_average(volumes, 117)
        close_ma5 = moving_average(closes, 5)
        close_ma10 = moving_average(closes, 10)
        close_ma20 = moving_average(closes, 20)
        pct = float(row.get("f3") or 0)
        code = str(row.get("f12", "")).zfill(6)
        stocks.append(
            MarketStock(
                code=code,
                name=str(row.get("f14", "")),
                themes=row_themes(row),
                pct_change=pct,
                close=float(row.get("f2") or 0),
                volume=volume,
                volume_ma4=volume_ma4,
                volume_ma11=volume_ma11,
                volume_ma117=volume_ma117,
                large_order_ratio=float(row.get("f184") or 0) / 100.0,
                main_force_net=float(row.get("f62") or 0),
                turnover=float(row.get("f8") or 0),
                close_ma5=close_ma5,
                close_ma10=close_ma10,
                close_ma20=close_ma20,
                consecutive_down_days=consecutive_down_days(closes),
                risk_flags=["st"] if "ST" in str(row.get("f14", "")).upper() else [],
                breakout_a=close_ma5 > close_ma10 > close_ma20 > 0 and pct >= 5.0,
                breakout_b=pct >= 6.0 and float(row.get("f62") or 0) > 0,
                is_limit_up=is_limit_up(row),
                is_fast_sealed=is_limit_up(row) and pct >= 9.8,
                leader_rank=rank_by_code.get(code, 0),
            )
        )
        time.sleep(0.02)
    meta = {"rows_scanned": len(rows), "limit_up_count": len(anchors), "selected_snapshot_rows": len(stocks)}
    return stocks, meta
