from __future__ import annotations

import json
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlencode

from ..models import MarketStock

CLIST_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
FFLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
INDEX_QT_URL = "https://qt.gtimg.cn/q=sh000001,sz399001"
FIELDS = "f12,f13,f14,f2,f3,f4,f5,f6,f8,f10,f62,f100,f102,f103,f184"

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def _curl_text(url: str, timeout: int = 8, encoding: str = "utf-8") -> str:
    result = subprocess.run(
        ["curl", "-sS", "-L", "-m", str(timeout), "-A", _UA, "-H", "Referer: https://quote.eastmoney.com/", url],
        capture_output=True,
        timeout=timeout + 4,
    )
    return result.stdout.decode(encoding, errors="ignore")


def fetch_json(url: str, params: dict[str, Any], timeout: int = 8, retries: int = 2) -> dict[str, Any]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    full = url + "?" + query
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            text = _curl_text(full, timeout)
            if not text.strip() or "502 Bad Gateway" in text or "<html" in text[:50].lower():
                raise RuntimeError(f"non-json response (len={len(text)})")
            return json.loads(text)
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(0.4 + attempt * 0.3)
    raise last_exc  # type: ignore[misc]


def fetch_market_total_amount() -> float:
    """两市成交额（元）：上证指数 + 深证成指。用腾讯 qt 指数接口。"""
    try:
        text = _curl_text(INDEX_QT_URL, timeout=8, encoding="gbk")
    except Exception:
        return 0.0
    total = 0.0
    for line in text.split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue
        payload = line.split("=", 1)[1].strip('"')
        parts = payload.split("~")
        if len(parts) < 50:
            continue
        combo = parts[43] if len(parts) > 43 else ""
        if "/" in combo:
            chunks = combo.split("/")
            if len(chunks) >= 3:
                try:
                    total += float(chunks[2])
                    continue
                except ValueError:
                    pass
        try:
            total += float(parts[37]) * 10000
        except (ValueError, IndexError):
            pass
    return total


def fetch_realtime_rows(max_pages: int = 20, stop_pct_below: float = 6.0) -> list[dict[str, Any]]:
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
        try:
            page_rows = fetch_json(CLIST_URL, params).get("data", {}).get("diff", []) or []
        except Exception:
            page_rows = []
        rows.extend(page_rows)
        if not page_rows:
            break
        min_pct = min(float(row.get("f3") or -999) for row in page_rows)
        if min_pct < stop_pct_below:
            break
        time.sleep(0.03)
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
        parsed.append({"date": parts[0], "close": float(parts[2]), "high": float(parts[3]), "volume": float(parts[5])})
    return parsed


def fetch_main_force_history(row: dict[str, Any], days: int = 20) -> list[float]:
    """近 N 日主力净流入序列（元）。东方财富资金流日K，f52=主力净流入。失败返回空列表。"""
    params = {
        "secid": secid(row),
        "lmt": days,
        "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55",
    }
    try:
        klines = fetch_json(FFLOW_URL, params).get("data", {}).get("klines", []) or []
    except Exception:
        return []
    series: list[float] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                series.append(float(parts[1]))  # f52 主力净流入
            except ValueError:
                continue
    return series


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


def compute_ema(values: list[float], n: int) -> list[float]:
    if not values:
        return []
    k = 2 / (n + 1)
    emas = [values[0]]
    for price in values[1:]:
        emas.append(price * k + emas[-1] * (1 - k))
    return emas


def compute_dif(closes: list[float]) -> float:
    if len(closes) < 26:
        return 0.0
    ema12 = compute_ema(closes, 12)
    ema26 = compute_ema(closes, 26)
    return ema12[-1] - ema26[-1]


def detect_bottom_divergence(closes: list[float], dif_series: list[float]) -> tuple[float, bool]:
    if len(dif_series) < 10 or len(closes) < 10:
        prev_low = dif_series[0] if dif_series else 0.0
        return prev_low, False
    window = min(len(dif_series) // 2, 10)
    recent_close_low = min(closes[-window:])
    prev_close_low = min(closes[-2 * window:-window]) if len(closes) >= 2 * window else min(closes[:-window])
    recent_dif_low = min(dif_series[-window:])
    prev_dif_low = min(dif_series[-2 * window:-window]) if len(dif_series) >= 2 * window else min(dif_series[:-window])
    bottom_div = recent_close_low < prev_close_low and recent_dif_low > prev_dif_low
    return prev_dif_low, bottom_div


def detect_consolidation(closes: list[float], volumes: list[float]) -> bool:
    if len(closes) < 10 or len(volumes) < 10:
        return False
    recent_c = closes[-10:]
    recent_v = volumes[-10:]
    amplitude = (max(recent_c) - min(recent_c)) / min(recent_c) if min(recent_c) > 0 else 0
    v_mean = sum(recent_v) / len(recent_v) if recent_v else 1
    v_std = (sum((v - v_mean) ** 2 for v in recent_v) / len(recent_v)) ** 0.5
    v_cv = v_std / v_mean if v_mean > 0 else 0
    return amplitude < 0.08 and v_cv < 0.4


def detect_breakout(closes: list[float], highs: list[float], volumes: list[float], lookback: int) -> bool:
    """突破前高：close > max(前 lookback 日最高价) 且当日放量（vol > vol_ma5）。"""
    if len(highs) < lookback + 1 or len(volumes) < 5:
        return False
    prev_high = max(highs[-(lookback + 1):-1])
    vol_ma5 = moving_average(volumes, 5)
    return closes[-1] > prev_high > 0 and volumes[-1] > vol_ma5 > 0


def rank_leader_ladder(selected_rows: list[dict[str, Any]]) -> dict[str, int]:
    """同板块龙头梯队：封板涨停=龙一(rank1)，非涨停按涨幅排龙二/龙三。"""
    ranking_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in selected_rows:
        for theme in row_themes(row):
            ranking_groups[theme].append(row)
    rank_by_code: dict[str, int] = {}
    for group_rows in ranking_groups.values():
        sealed = [r for r in group_rows if is_limit_up(r)]
        non_sealed = [r for r in group_rows if not is_limit_up(r)]
        sealed.sort(key=lambda r: float(r.get("f3") or 0), reverse=True)
        non_sealed.sort(key=lambda r: float(r.get("f3") or 0), reverse=True)
        ladder: list[tuple[str, int]] = []
        for idx in range(1, min(len(sealed), 1) + 1):
            ladder.append((str(sealed[idx - 1].get("f12")), idx))
        for idx, r in enumerate(non_sealed[:2], start=2):
            ladder.append((str(r.get("f12")), idx))
        for code, rank in ladder:
            if code not in rank_by_code or rank < rank_by_code[code]:
                rank_by_code[code] = rank
    return rank_by_code


def _hot_match(hot_set: set[str], tags: list[str]) -> bool:
    """子串包含匹配：任一 hot_term 是任一 tag 的子串，或反之。处理'机器人'匹配'机器人概念'等情况。"""
    for tag in tags:
        if not tag:
            continue
        for term in hot_set:
            if not term:
                continue
            if term in tag or tag in term:
                return True
    return False


def _select_rows(rows: list[dict[str, Any]], hot_set: set[str]) -> list[dict[str, Any]]:
    """筛选候选：涨停锚全留 + 热点命中且有同板块涨停的非涨停股(涨幅≥6%，限前15只)。"""
    anchors = [row for row in rows if is_limit_up(row)]
    anchor_by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in anchors:
        for theme in row_themes(row):
            anchor_by_theme[theme].append(row)

    selected: list[dict[str, Any]] = []
    non_sealed_candidates: list[dict[str, Any]] = []
    for row in rows:
        themes = row_themes(row)
        tags = themes + [str(row.get("f14", "")), str(row.get("f12", ""))]
        if hot_set and not _hot_match(hot_set, tags):
            continue
        if is_limit_up(row):
            selected.append(row)
            continue
        if not any(theme in anchor_by_theme for theme in themes):
            continue
        pct = float(row.get("f3") or 0)
        if pct >= 6.0:
            non_sealed_candidates.append(row)

    # 非涨停候选按涨幅降序取前15只，控制 scan 耗时
    non_sealed_candidates.sort(key=lambda r: float(r.get("f3") or 0), reverse=True)
    selected.extend(non_sealed_candidates[:15])
    return selected


def _enrich_stock(row: dict[str, Any], hot_set: set[str], rank_by_code: dict[str, int]) -> MarketStock | None:
    """对单只候选拉 kline+fflow，构造 MarketStock。失败字段降级。"""
    try:
        klines = fetch_kline(row)
    except Exception:
        klines = []
    closes = [float(item["close"]) for item in klines]
    highs = [float(item["high"]) for item in klines]
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

    # 多日主力资金：优先 fflow 序列；失败降级用当日 f62
    mf_series = fetch_main_force_history(row, 20)
    mf_degraded = False
    if mf_series:
        mf_5d = sum(mf_series[-5:]) if len(mf_series) >= 5 else sum(mf_series)
        mf_10d = sum(mf_series[-10:]) if len(mf_series) >= 10 else sum(mf_series)
        mf_20d = sum(mf_series[-20:]) if len(mf_series) >= 20 else sum(mf_series)
    else:
        mf_degraded = True
        today_mf = float(row.get("f62") or 0)
        mf_5d = mf_10d = mf_20d = today_mf

    dif_now = compute_dif(closes)
    dif_series = []
    if len(closes) >= 30:
        for end in range(26, len(closes) + 1):
            dif_series.append(compute_dif(closes[:end]))
    _, bottom_div = detect_bottom_divergence(closes, dif_series)

    consolidation = detect_consolidation(closes, volumes)
    themes = row_themes(row)
    business_ratio = 1.0 if (hot_set and hot_set.intersection(themes)) else 0.0

    # A/B 突破：突破前高（真突破），非均线多头
    breakout_a = detect_breakout(closes, highs, volumes, 20)
    breakout_b = detect_breakout(closes, highs, volumes, 60)

    return MarketStock(
        code=code,
        name=str(row.get("f14", "")),
        themes=themes,
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
        breakout_a=breakout_a,
        breakout_b=breakout_b,
        is_limit_up=is_limit_up(row),
        is_fast_sealed=is_limit_up(row) and pct >= 9.8,
        leader_rank=rank_by_code.get(code, 0),
        amount=float(row.get("f6") or 0),
        active_buy_ratio=float(row.get("f184") or 0) / 100.0,
        main_force_net_5d=mf_5d,
        main_force_net_10d=mf_10d,
        main_force_net_20d=mf_20d,
        dif_value=dif_now,
        is_consolidating=consolidation,
        business_ratio=business_ratio,
        is_bottom_divergence=bottom_div,
    )


def build_market_snapshot(rows: list[dict[str, Any]], hot_terms: list[str]) -> tuple[list[MarketStock], dict[str, Any]]:
    hot_set = {term for term in hot_terms if term}
    anchors = [row for row in rows if is_limit_up(row)]
    selected_rows = _select_rows(rows, hot_set)
    rank_by_code = rank_leader_ladder(selected_rows)
    market_total = fetch_market_total_amount()

    # 并发 enrich，控制总耗时
    stocks: list[MarketStock] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_enrich_stock, row, hot_set, rank_by_code): row for row in selected_rows}
        for future in as_completed(futures):
            try:
                stock = future.result()
                if stock:
                    stocks.append(stock)
            except Exception:
                continue

    meta = {
        "rows_scanned": len(rows),
        "limit_up_count": len(anchors),
        "selected_snapshot_rows": len(stocks),
        "market_total_amount": market_total,
    }
    return stocks, meta
