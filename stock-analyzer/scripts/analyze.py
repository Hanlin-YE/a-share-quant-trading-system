#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A-share quantitative stock analyzer.

The script keeps the original technical-analysis workflow, then adds a
lightweight machine-learning layer that is appropriate for a local skill:
feature normalization, time-series train/test split, tree models, instance
learning, regularized classification, SVM, neural net, PCA, clustering,
Markov regime transition, Bayesian win-rate estimation, and ensemble voting.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests

_CPU_COUNT = os.cpu_count() or 1
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(max(1, _CPU_COUNT - 1)))


try:
    from pandas_datareader.stooq import StooqDailyReader
except Exception:  # pragma: no cover - optional source
    StooqDailyReader = None

try:
    from scipy.stats import beta as beta_dist
except Exception:  # pragma: no cover - optional confidence interval
    beta_dist = None

try:
    from sklearn.base import clone
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    from sklearn.tree import DecisionTreeClassifier

    SKLEARN_AVAILABLE = True
except Exception:  # pragma: no cover - skill can still run TA-only
    SKLEARN_AVAILABLE = False


STOCK_NAME_MAP = {
    "000001": "平安银行",
    "000858": "五粮液",
    "002594": "比亚迪",
    "002920": "德赛西威",
    "300750": "宁德时代",
    "600519": "贵州茅台",
}
DEFAULT_HEALTH_CHECK_STOCKS = ["600519", "000001", "300750"]
DEFAULT_OBSERVE_SCAN_STOCKS = ["600519", "000001", "000858", "600000", "300750", "002594", "002920"]
DEFAULT_POOL_UNIVERSE_LIMIT = 50
SECTOR_REPRESENTATIVE_STOCKS: Dict[str, List[str]] = {
    "白酒消费": ["600519", "000858", "000568", "600809"],
    "银行金融": ["000001", "600000", "600036", "601398"],
    "券商保险": ["600030", "300059", "601318", "601688"],
    "新能源车": ["300750", "002594", "601012", "002460"],
    "半导体": ["688981", "603986", "002371", "300661"],
    "AI算力光模块": ["300308", "300502", "000977", "603019"],
    "通信设备": ["600487", "000063", "600522", "300394"],
    "汽车零部件": ["002920", "601689", "600660", "002050"],
    "军工": ["600760", "000768", "002179", "600893"],
    "医药医疗": ["300760", "600276", "000661", "300015"],
    "消费电子": ["002475", "300433", "002241", "601138"],
    "机器人自动化": ["300124", "002747", "688017", "002008"],
}

FEATURE_COLUMNS = [
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "ma_gap_5_20",
    "ma_gap_10_60",
    "close_z_20",
    "volume_z_20",
    "rsi_14",
    "kdj_j",
    "macd_hist",
    "volatility_20",
    "atr_pct_14",
    "drawdown_60",
]

DEFAULT_MIN_EDGE = 0.003
MIN_MODEL_AUC = 0.50
DATA_FETCH_ERRORS: List[Tuple[str, str]] = []
CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "market_data"
PUSH_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "pushed_market_data"


@dataclass
class DataResult:
    frame: pd.DataFrame
    stock_code: str
    stock_name: str
    source: str
    source_note: str = ""


@dataclass
class MLResult:
    available: bool
    probability: Optional[float] = None
    score: Optional[float] = None
    model_rows: int = 0
    horizon: int = 5
    min_edge: float = DEFAULT_MIN_EDGE
    model_votes: Optional[List[Tuple[str, float, Optional[float], Optional[float]]]] = None
    ensemble_note: str = ""
    pca_components: Optional[int] = None
    pca_explained: Optional[float] = None
    cluster_id: Optional[int] = None
    cluster_win_rate: Optional[float] = None
    cluster_avg_forward_return: Optional[float] = None
    markov_state: str = ""
    markov_probs: Optional[Dict[str, float]] = None
    bayes_mean: Optional[float] = None
    bayes_interval: Optional[Tuple[float, float]] = None
    warning: str = ""


@dataclass
class DataCheckProbe:
    passed: bool
    stock_code: str
    stock_name: str = "未知"
    source: str = ""
    row_count: int = 0
    start_date: str = ""
    end_date: str = ""
    latest_line: str = ""
    source_note: str = ""
    realtime_quote: str = ""
    error_summary: str = ""
    staged_error_summary: str = ""


# ============ Data source layer ============


def reset_fetch_errors() -> None:
    DATA_FETCH_ERRORS.clear()


def record_fetch_error(source: str, detail: str) -> None:
    DATA_FETCH_ERRORS.append((source, detail))


def fetch_error_summary() -> str:
    if not DATA_FETCH_ERRORS:
        return "未记录到具体失败原因。"
    return "；".join(f"{source}: {detail}" for source, detail in DATA_FETCH_ERRORS)


def fetch_error_summary_by_stage() -> str:
    if not DATA_FETCH_ERRORS:
        return "未记录到具体失败原因。"

    stage_details: Dict[str, List[str]] = {}
    for source, detail in DATA_FETCH_ERRORS:
        stage_details.setdefault(source, [])
        if detail not in stage_details[source]:
            stage_details[source].append(detail)

    ordered_parts = []
    for source, details in stage_details.items():
        ordered_parts.append(f"{source}[{len(details)}]: {' | '.join(details)}")
    return "；".join(ordered_parts)


def cache_path(provider: str, stock_code: str, days: int) -> Path:
    return CACHE_DIR / f"{provider}_{stock_code}_{days}.json"


def cached_payload_candidates(provider: str, stock_code: str, days: int) -> List[Tuple[int, Path]]:
    exact = cache_path(provider, stock_code, days)
    candidates: List[Tuple[int, Path]] = [(days, exact)]
    try:
        longer = []
        for candidate in CACHE_DIR.glob(f"{provider}_{stock_code}_*.json"):
            try:
                candidate_days = int(candidate.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                continue
            if candidate_days >= days and candidate != exact:
                longer.append((candidate_days, candidate))
        candidates.extend(sorted(longer))
    except Exception:
        pass
    return candidates


def pushed_cache_path(stock_code: str) -> Path:
    return PUSH_CACHE_DIR / f"{stock_code}.json"


def save_cached_payload(provider: str, stock_code: str, days: int, text: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path(provider, stock_code, days).write_text(
            json.dumps(
                {"saved_at": datetime.now().isoformat(timespec="seconds"), "text": text},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        record_fetch_error("行情缓存", f"写入失败: {exc}")


def cache_max_age_hours() -> int:
    try:
        return max(1, int(os.environ.get("A_SHARE_CACHE_MAX_AGE_HOURS", "72")))
    except ValueError:
        return 72


def load_cached_payload(provider: str, stock_code: str, days: int, max_age_hours: Optional[int] = None) -> Optional[Tuple[str, str]]:
    max_age = max_age_hours if max_age_hours is not None else cache_max_age_hours()
    paths = [path for _, path in cached_payload_candidates(provider, stock_code, days)]
    missing = []
    expired = []
    for candidate_path in paths:
        loaded = load_cached_payload_file(candidate_path, max_age_hours=max_age)
        if loaded:
            return loaded
        if candidate_path.exists():
            expired.append(candidate_path.name)
        else:
            missing.append(candidate_path.name)
    if expired:
        record_fetch_error("行情缓存", f"{' | '.join(expired)} 已过期或无效")
    elif missing:
        record_fetch_error("行情缓存", f"{' | '.join(missing)} 不存在")
    return None


def load_cached_payload_file(path: Path, max_age_hours: int = 72) -> Optional[Tuple[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        saved_at_text = payload.get("saved_at")
        text = payload.get("text")
        if not saved_at_text or not text:
            return None
        saved_at = datetime.fromisoformat(saved_at_text)
        age = datetime.now() - saved_at
        if age > timedelta(hours=max_age_hours):
            return None
        return text, saved_at_text
    except FileNotFoundError:
        return None
    except Exception as exc:
        record_fetch_error("行情缓存", f"读取失败: {exc}")
    return None


def normalize_pushed_bar(item: Dict[str, object]) -> Optional[Dict[str, object]]:
    date_value = item.get("date") or item.get("trade_date") or item.get("交易日期")
    if not date_value:
        return None
    parsed_date = pd.to_datetime(str(date_value), format="%Y%m%d", errors="coerce")
    if pd.isna(parsed_date):
        parsed_date = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(parsed_date):
        return None

    volume = item.get("volume", item.get("vol", item.get("成交量")))
    return {
        "date": parsed_date.strftime("%Y-%m-%d"),
        "open": item.get("open", item.get("开盘价")),
        "high": item.get("high", item.get("最高价")),
        "low": item.get("low", item.get("最低价")),
        "close": item.get("close", item.get("收盘价")),
        "volume": volume,
    }


def extract_pushed_bars(payload: Dict[str, object]) -> List[Dict[str, object]]:
    bars = payload.get("bars") or payload.get("items") or payload.get("data")
    if isinstance(bars, dict):
        fields = bars.get("fields")
        items = bars.get("items")
        if isinstance(fields, list) and isinstance(items, list):
            bars = [dict(zip(fields, row)) for row in items if isinstance(row, list)]
    if not isinstance(bars, list):
        return []

    normalized: List[Dict[str, object]] = []
    for item in bars:
        if isinstance(item, dict):
            bar = normalize_pushed_bar(item)
            if bar:
                normalized.append(bar)
    return normalized


def save_pushed_market_data(payload: Dict[str, object]) -> Dict[str, object]:
    stock_code = str(payload.get("stock_code") or payload.get("symbol") or payload.get("code") or "").strip()
    ts_code = str(payload.get("ts_code") or "").strip()
    if not stock_code and ts_code:
        stock_code = ts_code.split(".", 1)[0]
    stock_code = normalize_stock_code(stock_code)
    if not stock_code.isdigit() or len(stock_code) != 6:
        return {"ok": False, "error": "推送数据缺少 6 位 A 股代码"}

    bars = extract_pushed_bars(payload)
    if not bars:
        return {"ok": False, "error": "推送数据缺少 bars/items/data 行情数组"}

    frame, quality_notes = validate_ohlcv_frame(pd.DataFrame(bars))
    if frame.empty:
        return {"ok": False, "error": "推送数据未通过 OHLCV 质量检查"}

    provider = str(payload.get("provider") or payload.get("source") or "external-push").strip()
    stock_name = str(payload.get("stock_name") or payload.get("name") or STOCK_NAME_MAP.get(stock_code, "未知")).strip()
    received_at = datetime.now().isoformat(timespec="seconds")
    output = {
        "provider": provider,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "received_at": received_at,
        "source_note": str(payload.get("source_note") or "由数据供应商推送进入本地缓存"),
        "quality_notes": quality_notes,
        "bars": [
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            }
            for row in frame.itertuples(index=False)
        ],
    }
    try:
        PUSH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        pushed_cache_path(stock_code).write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        return {"ok": False, "error": f"推送缓存写入失败: {exc}"}

    return {
        "ok": True,
        "provider": provider,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "rows": len(output["bars"]),
        "start": output["bars"][0]["date"],
        "end": output["bars"][-1]["date"],
        "received_at": received_at,
    }


def import_market_csv_to_cache(
    *,
    csv_path: Path,
    stock_code: str,
    stock_name: str = "",
    provider: str = "local-csv",
    source_note: str = "由本地 CSV 导入推送快照缓存",
) -> Dict[str, object]:
    try:
        frame = pd.read_csv(csv_path)
    except Exception as exc:
        return {"ok": False, "error": f"CSV读取失败: {exc}"}
    bars = []
    records = frame.to_dict(orient="records")
    for row in records:
        bars.append(
            {
                "date": row.get("date") or row.get("trade_date") or row.get("日期") or row.get("交易日期"),
                "open": row.get("open") or row.get("开盘") or row.get("开盘价"),
                "high": row.get("high") or row.get("最高") or row.get("最高价"),
                "low": row.get("low") or row.get("最低") or row.get("最低价"),
                "close": row.get("close") or row.get("收盘") or row.get("收盘价"),
                "volume": row.get("volume") or row.get("vol") or row.get("成交量"),
            }
        )
    return save_pushed_market_data(
        {
            "provider": provider,
            "stock_code": stock_code,
            "stock_name": stock_name or STOCK_NAME_MAP.get(normalize_stock_code(stock_code), "未知"),
            "source_note": source_note,
            "bars": bars,
        }
    )


def get_pushed_data(stock_code: str, days: int = 360, max_age_hours: int = 36) -> Optional[DataResult]:
    stock_code = normalize_stock_code(stock_code)
    path = pushed_cache_path(stock_code)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        received_at = datetime.fromisoformat(payload.get("received_at", ""))
        if datetime.now() - received_at > timedelta(hours=max_age_hours):
            record_fetch_error("推送缓存", f"{stock_code} 推送缓存已过期")
            return None
        bars = payload.get("bars") or []
        frame, quality_notes = validate_ohlcv_frame(pd.DataFrame(bars))
        frame = frame.tail(days).reset_index(drop=True)
        if frame.empty:
            return None
        provider = payload.get("provider") or "external-push"
        note_parts = [
            payload.get("source_note") or "由数据供应商推送进入本地缓存",
            f"推送接收时间={payload.get('received_at')}",
            *quality_notes,
            *(payload.get("quality_notes") or []),
        ]
        return DataResult(
            frame,
            stock_code,
            payload.get("stock_name") or STOCK_NAME_MAP.get(stock_code, "未知"),
            f"{provider} 推送缓存",
            "；".join(str(part) for part in note_parts if part),
        )
    except FileNotFoundError:
        record_fetch_error("推送缓存", f"{path.name} 不存在")
    except Exception as exc:
        record_fetch_error("推送缓存", f"读取失败: {exc}")
    return None


def save_data_result_snapshot(provider: str, result: DataResult) -> Dict[str, object]:
    payload = {
        "provider": provider,
        "stock_code": result.stock_code,
        "stock_name": result.stock_name,
        "source_note": result.source_note or result.source,
        "bars": [
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            }
            for row in result.frame.itertuples(index=False)
        ],
    }
    return save_pushed_market_data(payload)


def refresh_market_cache(stocks: List[str], days: int = 720, source: str = "premium") -> Dict[str, object]:
    results = []
    for stock in stocks:
        stock_code = normalize_stock_code(stock)
        reset_fetch_errors()
        pull_source = "tushare" if source == "push" else source
        data = get_stock_data(stock_code, days, pull_source)
        if not data:
            results.append(
                {
                    "ok": False,
                    "stock_code": stock_code,
                    "error": fetch_error_summary_by_stage(),
                }
            )
            continue
        saved = save_data_result_snapshot(f"{data.source} 自动刷新", data)
        results.append(saved)
    return {
        "ok": all(bool(item.get("ok")) for item in results) if results else False,
        "refreshed_at": datetime.now().isoformat(timespec="seconds"),
        "count": len(results),
        "results": results,
    }


def file_age_hours(path: Path) -> Optional[float]:
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    except FileNotFoundError:
        return None
    return (datetime.now() - modified_at).total_seconds() / 3600.0


def inspect_pushed_cache(stock_code: str, min_rows: int, max_age_hours: int) -> Dict[str, object]:
    path = pushed_cache_path(stock_code)
    status: Dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "ok": False,
    }
    if not path.exists():
        status["error"] = "推送缓存不存在"
        return status
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        received_at = datetime.fromisoformat(payload.get("received_at", ""))
        age_hours = (datetime.now() - received_at).total_seconds() / 3600.0
        frame, quality_notes = validate_ohlcv_frame(pd.DataFrame(payload.get("bars") or []))
        rows = len(frame)
        status.update(
            {
                "provider": payload.get("provider") or "external-push",
                "stock_name": payload.get("stock_name") or STOCK_NAME_MAP.get(stock_code, "未知"),
                "received_at": payload.get("received_at"),
                "age_hours": round(age_hours, 2),
                "rows": rows,
                "start": str(frame["date"].iloc[0].date()) if rows else "",
                "end": str(frame["date"].iloc[-1].date()) if rows else "",
                "fresh": age_hours <= max_age_hours,
                "enough_rows": rows >= min_rows,
                "quality_notes": quality_notes + list(payload.get("quality_notes") or []),
            }
        )
        status["ok"] = bool(status["fresh"] and status["enough_rows"])
        if not status["fresh"]:
            status["error"] = f"推送缓存已过期，age_hours={status['age_hours']}"
        elif not status["enough_rows"]:
            status["error"] = f"推送缓存行数不足，rows={rows}, min_rows={min_rows}"
    except Exception as exc:
        status["error"] = f"推送缓存读取失败: {exc}"
    return status


def inspect_pull_cache(stock_code: str, days: int, max_age_hours: int) -> List[Dict[str, object]]:
    statuses: List[Dict[str, object]] = []
    for provider in ("tencent", "eastmoney"):
        candidates = cached_payload_candidates(provider, stock_code, days)
        path = candidates[0][1]
        usable_candidate = None
        for candidate_days, candidate_path in candidates:
            age_hours = file_age_hours(candidate_path)
            if age_hours is not None and age_hours <= max_age_hours:
                usable_candidate = (candidate_days, candidate_path, age_hours)
                break
        if usable_candidate:
            candidate_days, path, age_hours = usable_candidate
        else:
            age_hours = file_age_hours(path)
            candidate_days = days
        item: Dict[str, object] = {
            "provider": provider,
            "path": str(path),
            "exists": path.exists(),
            "ok": False,
            "cache_days": candidate_days,
        }
        if age_hours is None:
            item["error"] = "缓存不存在"
        else:
            item["age_hours"] = round(age_hours, 2)
            item["fresh"] = age_hours <= max_age_hours
            item["ok"] = bool(item["fresh"])
            if not item["fresh"]:
                item["error"] = f"缓存已过期，age_hours={item['age_hours']}"
        statuses.append(item)
    return statuses


def inspect_market_cache(
    stocks: List[str],
    days: int = 720,
    min_rows: int = 80,
    max_age_hours: int = 36,
) -> Dict[str, object]:
    results = []
    for stock in stocks:
        stock_code = normalize_stock_code(stock)
        pushed = inspect_pushed_cache(stock_code, min_rows=min_rows, max_age_hours=max_age_hours)
        pull_caches = inspect_pull_cache(stock_code, days=days, max_age_hours=max_age_hours)
        usable_pull = [item for item in pull_caches if item.get("ok")]
        usable = bool(pushed.get("ok") or usable_pull)
        if pushed.get("ok"):
            source_hint = "premium/push 可用：推送快照缓存新鲜且行数足够"
        elif usable_pull:
            source_hint = "auto/tencent/eastmoney 可用：存在指定 days 的新鲜拉取缓存"
        else:
            source_hint = "不可用：没有新鲜且足够的缓存"
        results.append(
            {
                "stock_code": stock_code,
                "stock_name": pushed.get("stock_name") or STOCK_NAME_MAP.get(stock_code, "未知"),
                "usable": usable,
                "source_hint": source_hint,
                "pushed_cache": pushed,
                "pull_caches": pull_caches,
            }
        )
    return {
        "ok": all(bool(item["usable"]) for item in results) if results else False,
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "min_rows": min_rows,
        "max_age_hours": max_age_hours,
        "results": results,
    }


def discover_cached_stock_pool(
    days: int = 260,
    min_rows: int = 80,
    max_age_hours: int = 36,
    limit: int = 20,
) -> Dict[str, object]:
    symbols = set()
    for provider in ("tencent", "eastmoney"):
        try:
            for candidate in CACHE_DIR.glob(f"{provider}_*.json"):
                parts = candidate.stem.split("_")
                if len(parts) != 3:
                    continue
                _, stock_code, raw_days = parts
                try:
                    candidate_days = int(raw_days)
                except ValueError:
                    continue
                if candidate_days >= days:
                    symbols.add(stock_code)
        except Exception:
            pass
    try:
        for pushed in PUSH_CACHE_DIR.glob("*.json"):
            symbols.add(pushed.stem)
    except Exception:
        pass
    health = inspect_market_cache(sorted(symbols), days=days, min_rows=min_rows, max_age_hours=max_age_hours)
    usable = [item for item in health.get("results", []) if item.get("usable")]
    usable = usable[: max(1, limit)]
    return {
        "ok": bool(usable),
        "discovered_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "min_rows": min_rows,
        "max_age_hours": max_age_hours,
        "limit": limit,
        "stocks": [str(item["stock_code"]) for item in usable],
        "results": usable,
        "risk_note": "仅用于训练/研究的数据池发现，不构成投资建议或真实交易指令。",
    }


def render_market_cache_health(payload: Dict[str, object]) -> str:
    lines = [
        "A股行情缓存健康检查",
        "====================",
        f"检查时间: {payload.get('checked_at')}",
        f"样本窗口: {payload.get('days')}个交易日",
        f"最少行数: {payload.get('min_rows')}",
        f"最大缓存年龄: {payload.get('max_age_hours')}小时",
        f"总体结论: {'通过' if payload.get('ok') else '失败'}",
        "",
        "缓存状态",
    ]
    for item in payload.get("results", []):
        prefix = "OK" if item.get("usable") else "FAIL"
        lines.append(f"- {prefix} {item.get('stock_code')} {item.get('stock_name')}: {item.get('source_hint')}")
        pushed = item.get("pushed_cache") or {}
        if pushed.get("exists"):
            lines.append(
                f"  推送缓存: rows={pushed.get('rows', 'N/A')}，"
                f"age_hours={pushed.get('age_hours', 'N/A')}，"
                f"{pushed.get('start', '')}至{pushed.get('end', '')}"
            )
        else:
            lines.append(f"  推送缓存: {pushed.get('error')}")
        pull_parts = []
        for cache in item.get("pull_caches") or []:
            if cache.get("exists"):
                pull_parts.append(
                    f"{cache.get('provider')} age_hours={cache.get('age_hours')} "
                    f"{'OK' if cache.get('ok') else '过期'}"
                )
            else:
                pull_parts.append(f"{cache.get('provider')} 不存在")
        lines.append(f"  拉取缓存: {'；'.join(pull_parts)}")
    lines.extend(
        [
            "",
            "门禁: 缓存健康通过后，才建议运行自动回测/参数优化；失败时先刷新缓存或修复外部行情源。",
            "风险提示: 缓存健康只证明数据可用，不证明策略有效或可稳定盈利。",
        ]
    )
    return "\n".join(lines)


def normalize_stock_code(stock: str) -> str:
    stock = stock.strip().upper()
    if stock in STOCK_NAME_MAP:
        return stock
    for code, name in STOCK_NAME_MAP.items():
        if stock in name:
            return code
    return stock


def a_share_market(stock_code: str) -> str:
    if stock_code.startswith(("0", "2", "3")):
        return "sz"
    return "sh"


def validate_ohlcv_frame(frame: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    required = ["date", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"行情字段缺失: {', '.join(missing)}")

    df = frame[required].copy()
    notes: List[str] = []
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    before = len(df)
    df = df.dropna(subset=required)
    if len(df) < before:
        notes.append(f"已剔除{before - len(df)}条缺失行情")

    before = len(df)
    df = df.sort_values("date").drop_duplicates("date", keep="last")
    if len(df) < before:
        notes.append(f"已合并{before - len(df)}条重复日期行情")

    valid = (
        (df["open"] > 0)
        & (df["high"] > 0)
        & (df["low"] > 0)
        & (df["close"] > 0)
        & (df["volume"] >= 0)
        & (df["high"] >= df[["open", "close", "low"]].max(axis=1))
        & (df["low"] <= df[["open", "close", "high"]].min(axis=1))
    )
    invalid_count = int((~valid).sum())
    if invalid_count:
        notes.append(f"已剔除{invalid_count}条OHLC异常行情")
    return df.loc[valid].reset_index(drop=True), notes


def decode_response_body(body: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def fetch_text_via_curl(url: str, timeout: int = 15, retries: int = 3) -> Optional[str]:
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            completed = subprocess.run(
                [
                    "curl",
                    "-L",
                    "--connect-timeout",
                    "8",
                    "--max-time",
                    str(timeout),
                    "-sS",
                    "-H",
                    "User-Agent: Mozilla/5.0",
                    "-H",
                    "Referer: https://quote.eastmoney.com/",
                    url,
                ],
                capture_output=True,
                check=False,
            )
        except Exception as exc:
            last_error = f"启动失败: {exc}"
            if attempt < retries:
                time.sleep(0.8 * attempt)
                continue
            record_fetch_error("curl", last_error)
            return None

        if completed.returncode != 0:
            stderr = decode_response_body(completed.stderr).strip()
            last_error = f"退出码{completed.returncode}{(': ' + stderr[:120]) if stderr else ''}"
            if attempt < retries:
                time.sleep(0.8 * attempt)
                continue
            record_fetch_error("curl", last_error)
            return None

        text = decode_response_body(completed.stdout).strip()
        if not text or text.startswith("<html") or text == "Forbidden":
            last_error = "返回为空、HTML或Forbidden"
            if attempt < retries:
                time.sleep(0.8 * attempt)
                continue
            record_fetch_error("curl", last_error)
            return None
        return text

    if last_error:
        record_fetch_error("curl", last_error)
    return None


def get_tencent_data(stock_code: str, days: int = 360) -> Optional[DataResult]:
    """Fetch A-share daily bars from Tencent Finance."""
    market = a_share_market(stock_code)
    full_code = f"{market}{stock_code}"
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"_var": "kline_dayqfq", "param": f"{full_code},day,,,{days},qfq"}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        text = resp.text
        if "=" not in text:
            record_fetch_error("腾讯requests", "返回不是kline_dayqfq赋值格式")
            return None
        payload = json.loads(text.split("=", 1)[1])
        if payload.get("code") != 0:
            record_fetch_error("腾讯requests", f"接口code={payload.get('code')} msg={payload.get('msg')}")
            return None
        stock_data = payload.get("data", {}).get(full_code, {})
        qfq_kline = stock_data.get("qfqday")
        raw_kline = stock_data.get("day")
        kline = qfq_kline or raw_kline or []
        if not kline:
            record_fetch_error("腾讯requests", "未返回qfqday/day K线")
            return None

        rows = []
        for item in kline:
            rows.append(
                {
                    "date": pd.to_datetime(item[0]),
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                }
            )
        frame, quality_notes = validate_ohlcv_frame(pd.DataFrame(rows))
        if frame.empty:
            return None
        name = stock_data.get("name") or STOCK_NAME_MAP.get(stock_code, "未知")
        source = "腾讯财经 前复权日线" if qfq_kline else "腾讯财经 日线（未确认复权）"
        notes = quality_notes
        if not qfq_kline and raw_kline:
            notes.insert(0, "腾讯未返回前复权字段，已退回普通日线；复权一致性需二次确认")
        return DataResult(frame, stock_code, name, source, "；".join(notes))
    except Exception as exc:
        record_fetch_error("腾讯requests", str(exc))
        return None


def get_tencent_data_via_curl(stock_code: str, days: int = 360, allow_network: bool = True) -> Optional[DataResult]:
    market = a_share_market(stock_code)
    full_code = f"{market}{stock_code}"
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?_var=kline_dayqfq&param={full_code},day,,,{days},qfq"
    )
    cache_note = ""
    text = fetch_text_via_curl(url) if allow_network else None
    if text and "=" in text:
        save_cached_payload("tencent", stock_code, days, text)
    else:
        if allow_network:
            record_fetch_error("腾讯curl", "返回为空或不是kline_dayqfq赋值格式")
        cached = load_cached_payload("tencent", stock_code, days)
        if not cached:
            return None
        text, saved_at = cached
        cache_note = f"使用本地缓存兜底，缓存时间={saved_at}"

    try:
        payload = json.loads(text.split("=", 1)[1])
        if payload.get("code") != 0:
            record_fetch_error("腾讯curl", f"接口code={payload.get('code')} msg={payload.get('msg')}")
            return None
        stock_data = payload.get("data", {}).get(full_code, {})
        qfq_kline = stock_data.get("qfqday")
        raw_kline = stock_data.get("day")
        kline = qfq_kline or raw_kline or []
        if not kline:
            record_fetch_error("腾讯curl", "未返回qfqday/day K线")
            return None

        rows = []
        for item in kline:
            rows.append(
                {
                    "date": pd.to_datetime(item[0]),
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]),
                }
            )
        frame, quality_notes = validate_ohlcv_frame(pd.DataFrame(rows))
        if frame.empty:
            return None
        name = stock_data.get("name") or STOCK_NAME_MAP.get(stock_code, "未知")
        source = "腾讯财经 前复权日线（curl兜底）" if qfq_kline else "腾讯财经 日线（curl兜底）"
        notes = quality_notes
        if not qfq_kline and raw_kline:
            notes.insert(0, "腾讯未返回前复权字段，已退回普通日线；复权一致性需二次确认")
        if cache_note:
            notes.append(cache_note)
        return DataResult(frame, stock_code, name, source, "；".join(notes))
    except Exception as exc:
        record_fetch_error("腾讯curl", str(exc))
        return None


def eastmoney_secid(stock_code: str) -> str:
    market_id = "0" if stock_code.startswith(("0", "2", "3")) else "1"
    return f"{market_id}.{stock_code}"


def tushare_ts_code(stock_code: str) -> str:
    suffix = "SZ" if stock_code.startswith(("0", "2", "3")) else "SH"
    return f"{stock_code}.{suffix}"


def tushare_token() -> str:
    return os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_PRO_TOKEN") or ""


def fetch_tushare_api(api_name: str, params: Dict[str, str], fields: str) -> Optional[pd.DataFrame]:
    token = tushare_token()
    if not token:
        record_fetch_error("Tushare Pro", "未配置 TUSHARE_TOKEN / TUSHARE_PRO_TOKEN")
        return None

    url = os.environ.get("TUSHARE_API_URL", "http://api.tushare.pro")
    try:
        response = requests.post(
            url,
            json={"api_name": api_name, "token": token, "params": params, "fields": fields},
            timeout=18,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        record_fetch_error("Tushare Pro", f"{api_name} 请求失败: {exc}")
        return None

    if payload.get("code") != 0:
        record_fetch_error("Tushare Pro", f"{api_name} code={payload.get('code')} msg={payload.get('msg')}")
        return None

    data = payload.get("data") or {}
    columns = data.get("fields") or []
    rows = data.get("items") or []
    if not columns or not rows:
        record_fetch_error("Tushare Pro", f"{api_name} 未返回数据")
        return None
    return pd.DataFrame(rows, columns=columns)


def get_tushare_data(stock_code: str, days: int = 360) -> Optional[DataResult]:
    """Fetch A-share daily bars from Tushare Pro when a token is configured."""
    ts_code = tushare_ts_code(stock_code)
    end_date = datetime.today().strftime("%Y%m%d")
    start_date = (datetime.today() - timedelta(days=max(days * 2 + 45, 420))).strftime("%Y%m%d")
    daily = fetch_tushare_api(
        "daily",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount",
    )
    if daily is None or daily.empty:
        return None

    rows = daily.rename(columns={"trade_date": "date", "vol": "volume"}).copy()
    rows["date"] = pd.to_datetime(rows["date"], format="%Y%m%d", errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    frame, quality_notes = validate_ohlcv_frame(rows[["date", "open", "high", "low", "close", "volume"]])
    frame = frame.tail(days).reset_index(drop=True)
    if frame.empty:
        return None

    adjustment_note = "Tushare daily 为未复权行情"
    factors = fetch_tushare_api(
        "adj_factor",
        {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        "ts_code,trade_date,adj_factor",
    )
    if factors is not None and not factors.empty:
        factor_frame = factors.rename(columns={"trade_date": "date"}).copy()
        factor_frame["date"] = pd.to_datetime(factor_frame["date"], format="%Y%m%d", errors="coerce")
        factor_frame["adj_factor"] = pd.to_numeric(factor_frame["adj_factor"], errors="coerce")
        merged = frame.merge(factor_frame[["date", "adj_factor"]], on="date", how="left")
        latest_factor = merged["adj_factor"].dropna().iloc[-1] if not merged["adj_factor"].dropna().empty else None
        if latest_factor and math.isfinite(float(latest_factor)) and float(latest_factor) != 0:
            ratio = merged["adj_factor"] / float(latest_factor)
            for column in ["open", "high", "low", "close"]:
                merged[column] = merged[column] * ratio
            frame = merged[["date", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
            adjustment_note = "Tushare daily + adj_factor 已折算为前复权口径"

    if frame.empty:
        return None
    name = STOCK_NAME_MAP.get(stock_code, "未知")
    note = "；".join(
        [
            *quality_notes,
            adjustment_note,
            "交易日约 15:00-16:00 入库，适合作为日频研究主源",
        ]
    )
    return DataResult(frame, stock_code, name, "Tushare Pro A股日线", note)


def get_eastmoney_data(stock_code: str, days: int = 360) -> Optional[DataResult]:
    secid = eastmoney_secid(stock_code)
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={secid}&klt=101&fqt=1&lmt={days}"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
    )

    payload_text: Optional[str] = None
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
        )
        resp.raise_for_status()
        payload_text = resp.text
    except Exception as exc:
        record_fetch_error("东方财富requests", str(exc))
        payload_text = fetch_text_via_curl(url)

    if not payload_text:
        record_fetch_error("东方财富", "未取得响应文本")
        cached = load_cached_payload("eastmoney", stock_code, days)
        if not cached:
            return None
        payload_text, cached_at = cached
    else:
        cached_at = ""
        save_cached_payload("eastmoney", stock_code, days, payload_text)

    try:
        payload = json.loads(payload_text)
        data = payload.get("data") or {}
        klines = data.get("klines") or []
        if not klines:
            record_fetch_error("东方财富", "未返回klines")
            return None

        rows = []
        for item in klines:
            parts = item.split(",")
            if len(parts) < 6:
                continue
            rows.append(
                {
                    "date": pd.to_datetime(parts[0]),
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": float(parts[5]),
                }
            )
        frame, quality_notes = validate_ohlcv_frame(pd.DataFrame(rows))
        if frame.empty:
            return None
        name = data.get("name") or STOCK_NAME_MAP.get(stock_code, "未知")
        note = "东方财富接口为实验入口，部分标的可能返回空数据"
        if cached_at:
            note += f"；使用本地缓存兜底，缓存时间={cached_at}"
        merged_note = "；".join([*quality_notes, note]) if quality_notes else note
        return DataResult(frame, stock_code, name, "东方财富 前复权日线", merged_note)
    except Exception as exc:
        record_fetch_error("东方财富", str(exc))
        return None


def get_tencent_realtime_quote(stock_code: str) -> Optional[str]:
    market = a_share_market(stock_code)
    full_code = f"{market}{stock_code}"
    text = fetch_text_via_curl(f"https://qt.gtimg.cn/q={full_code}")
    if not text or "~" not in text:
        record_fetch_error("腾讯实时行情", "实时报价为空或格式异常")
        return None
    try:
        quote = text.split('"', 2)[1]
        parts = quote.split("~")
        if len(parts) < 38:
            record_fetch_error("腾讯实时行情", "字段数量不足")
            return None
        name = parts[1] or STOCK_NAME_MAP.get(stock_code, "未知")
        return (
            f"实时行情兜底: {full_code} {name} 当前价={parts[3]}，昨收={parts[4]}，"
            f"今开={parts[5]}，涨跌={parts[31]}，涨跌幅={parts[32]}%，最高={parts[33]}，最低={parts[34]}，"
            f"时间={parts[30]}"
        )
    except Exception as exc:
        record_fetch_error("腾讯实时行情", str(exc))
        return None


def get_stooq_data(symbol: str, days: int = 720) -> Optional[DataResult]:
    """Fetch via pandas-datareader StooqDailyReader.

    StooqDailyReader is useful as an adapter, but its official reader does not
    list mainland China suffixes among supported country suffixes. In A-share
    mode this function is intentionally best-effort and will usually fall back.
    """
    if StooqDailyReader is None:
        return None

    end = datetime.today()
    start = end - timedelta(days=max(days * 2, 365))
    candidates = [symbol]
    if symbol.isdigit() and len(symbol) == 6:
        market = "SZ" if symbol.startswith(("0", "2", "3")) else "SH"
        candidates.extend([f"{symbol}.{market}", f"{symbol}.CN"])

    for candidate in dict.fromkeys(candidates):
        try:
            raw = StooqDailyReader(symbols=candidate, start=start, end=end).read()
            if raw is None or raw.empty:
                continue
            raw = raw.reset_index().rename(columns=str.lower)
            if "date" not in raw.columns:
                raw = raw.rename(columns={raw.columns[0]: "date"})
            required = {"date", "open", "high", "low", "close", "volume"}
            if not required.issubset(set(raw.columns)):
                continue
            frame = raw[["date", "open", "high", "low", "close", "volume"]].copy()
            frame, quality_notes = validate_ohlcv_frame(frame)
            frame = frame.tail(days).reset_index(drop=True)
            if len(frame) >= 60:
                return DataResult(
                    frame,
                    symbol,
                    STOCK_NAME_MAP.get(symbol, candidate),
                    "pandas-datareader / Stooq",
                    "；".join(
                        [
                            "Stooq 对中国 A 股覆盖有限；若代码被解析到其他市场，请优先使用 auto/tencent",
                            *quality_notes,
                        ]
                    ),
                )
        except Exception as exc:
            record_fetch_error("Stooq", f"{candidate}: {exc}")
            continue
    return None


def get_stock_data(stock_code: str, days: int, source: str = "auto") -> Optional[DataResult]:
    if source == "push":
        return get_pushed_data(stock_code, days)
    if source == "tushare":
        return get_tushare_data(stock_code, days)
    if source == "premium":
        result = (
            get_pushed_data(stock_code, days)
            or get_tushare_data(stock_code, days)
            or get_tencent_data_via_curl(stock_code, days)
            or get_tencent_data(stock_code, days)
            or get_eastmoney_data(stock_code, days)
        )
        if result:
            premium_note = "高质量源策略：供应商推送缓存优先，Tushare Pro 次优先，失败后回退腾讯/东方财富并保留数据链路说明"
            result.source_note = f"{result.source_note}；{premium_note}" if result.source_note else premium_note
            return result
        return None
    if source == "pull":
        result = (
            get_tushare_data(stock_code, days)
            or get_tencent_data_via_curl(stock_code, days)
            or get_tencent_data(stock_code, days)
            or get_eastmoney_data(stock_code, days)
        )
        if result:
            premium_note = "自动拉取策略：Tushare Pro 优先，失败后回退腾讯/东方财富并保留数据链路说明"
            result.source_note = f"{result.source_note}；{premium_note}" if result.source_note else premium_note
            return result
        return None
    if source == "stooq":
        return get_stooq_data(stock_code, days)
    if source == "tencent":
        return get_tencent_data_via_curl(stock_code, days) or get_tencent_data(stock_code, days)
    if source == "eastmoney":
        return get_eastmoney_data(stock_code, days)

    # For China A shares, prefer Tencent curl qfq daily first, then Tencent requests,
    # then Eastmoney. Stooq remains an experimental backup for degraded cases.
    if stock_code.isdigit() and len(stock_code) == 6:
        result = (
            get_tencent_data_via_curl(stock_code, days)
            or get_tencent_data(stock_code, days)
            or get_eastmoney_data(stock_code, days)
        )
        if result:
            auto_note = "A 股优先使用腾讯/东方财富多源日线；Stooq 保留为可选实验源"
            result.source_note = f"{result.source_note}；{auto_note}" if result.source_note else auto_note
            return result
    return (
        get_stooq_data(stock_code, days)
        or get_eastmoney_data(stock_code, days)
        or get_tencent_data_via_curl(stock_code, days)
        or get_tencent_data(stock_code, days)
    )


def a_share_network_preflight() -> Tuple[bool, str]:
    reset_fetch_errors()
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param=sh600519,day,,,1,qfq"
    text = fetch_text_via_curl(url, timeout=5, retries=1)
    if text and "kline_dayqfq=" in text:
        return True, "腾讯行情域名预检通过"
    return False, fetch_error_summary_by_stage()


def fetch_eastmoney_a_share_universe(limit: int = DEFAULT_POOL_UNIVERSE_LIMIT) -> Tuple[List[str], str]:
    limit = max(1, min(limit, 500))
    url = (
        "https://push2.eastmoney.com/api/qt/clist/get"
        f"?pn=1&pz={limit}&po=1&np=1"
        "&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f6"
        "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
        "&fields=f12,f14,f2,f3,f5,f6"
    )
    text = fetch_text_via_curl(url, timeout=8, retries=1)
    if not text:
        return [], f"东方财富A股列表获取失败: {fetch_error_summary_by_stage()}"
    try:
        payload = json.loads(text)
        rows = payload.get("data", {}).get("diff") or []
        codes = []
        for row in rows:
            code = str(row.get("f12", "")).strip()
            name = str(row.get("f14", "")).strip()
            if code.isdigit() and len(code) == 6:
                codes.append(code)
                if name and code not in STOCK_NAME_MAP:
                    STOCK_NAME_MAP[code] = name
        total = payload.get("data", {}).get("total", "?")
        return list(dict.fromkeys(codes)), f"东方财富A股列表: 取成交额前{len(codes)}只/总数{total}"
    except Exception as exc:
        return [], f"东方财富A股列表解析失败: {exc}"


def build_sector_representative_universe(include_dynamic: bool, dynamic_limit: int) -> Tuple[List[str], str]:
    sector_codes: List[str] = []
    for codes in SECTOR_REPRESENTATIVE_STOCKS.values():
        sector_codes.extend(codes)

    notes = [f"板块代表池: {len(SECTOR_REPRESENTATIVE_STOCKS)}个板块/{len(dict.fromkeys(sector_codes))}只"]
    if include_dynamic:
        dynamic_codes, dynamic_note = fetch_eastmoney_a_share_universe(dynamic_limit)
        sector_codes.extend(dynamic_codes)
        notes.append(dynamic_note)

    return list(dict.fromkeys(sector_codes)), "；".join(notes)


# ============ Indicators and feature engineering ============


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy().sort_values("date").reset_index(drop=True)
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    for period in [5, 10, 20, 60]:
        df[f"ma_{period}"] = close.rolling(period).mean()
    df["ret_1"] = close.pct_change()
    df["ret_3"] = close.pct_change(3)
    df["ret_5"] = close.pct_change(5)
    df["ret_10"] = close.pct_change(10)
    df["ma_gap_5_20"] = df["ma_5"] / df["ma_20"] - 1
    df["ma_gap_10_60"] = df["ma_10"] / df["ma_60"] - 1
    df["close_z_20"] = (close - close.rolling(20).mean()) / close.rolling(20).std()
    df["volume_z_20"] = (volume - volume.rolling(20).mean()) / volume.rolling(20).std()
    df["rsi_14"] = rsi(close)

    low_n = low.rolling(9).min()
    high_n = high.rolling(9).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    df["kdj_k"] = rsv.ewm(com=2, adjust=False).mean()
    df["kdj_d"] = df["kdj_k"].ewm(com=2, adjust=False).mean()
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]

    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    df["macd_dif"] = ema_12 - ema_26
    df["macd_dea"] = df["macd_dif"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = (df["macd_dif"] - df["macd_dea"]) * 2

    prev_close = close.shift(1)
    true_range = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    df["atr_14"] = true_range.rolling(14).mean()
    df["atr_pct_14"] = df["atr_14"] / close
    df["volatility_20"] = df["ret_1"].rolling(20).std() * math.sqrt(252)
    df["drawdown_60"] = close / close.rolling(60).max() - 1
    df["volume_ratio_5"] = volume / volume.shift(1).rolling(5).mean()
    return df.replace([np.inf, -np.inf], np.nan)


def calc_max_drawdown(closes: Iterable[float]) -> float:
    series = pd.Series(list(closes), dtype="float64")
    if len(series) < 2:
        return 0.0
    drawdown = series / series.cummax() - 1
    return round(abs(drawdown.min()) * 100, 2)


def technical_score(df: pd.DataFrame) -> Tuple[float, List[str]]:
    latest = df.iloc[-1]
    score = 50.0
    signals: List[str] = []

    ma_points = 0
    ma_text = []
    for fast, slow in [(5, 10), (10, 20), (20, 60)]:
        f_col = f"ma_{fast}"
        s_col = f"ma_{slow}"
        if pd.notna(latest.get(f_col)) and pd.notna(latest.get(s_col)):
            if latest[f_col] > latest[s_col]:
                ma_points += 10
                ma_text.append(f"MA{fast}>MA{slow}")
            else:
                ma_text.append(f"MA{fast}<MA{slow}")
    score += ma_points - 15
    signals.append(f"均线结构: {', '.join(ma_text) if ma_text else '样本不足'}")

    rsi_val = latest.get("rsi_14", np.nan)
    if pd.notna(rsi_val):
        if rsi_val < 30:
            score += 12
            signals.append(f"RSI(14)={rsi_val:.2f}，短线超卖")
        elif rsi_val > 70:
            score -= 12
            signals.append(f"RSI(14)={rsi_val:.2f}，短线超买")
        else:
            signals.append(f"RSI(14)={rsi_val:.2f}，处于中性区")

    kdj_j = latest.get("kdj_j", np.nan)
    if pd.notna(kdj_j):
        if kdj_j < 20:
            score += 10
            signals.append(f"KDJ-J={kdj_j:.2f}，偏超卖")
        elif kdj_j > 80:
            score -= 10
            signals.append(f"KDJ-J={kdj_j:.2f}，偏超买")
        else:
            signals.append(f"KDJ-J={kdj_j:.2f}")

    macd_hist = latest.get("macd_hist", np.nan)
    if pd.notna(macd_hist):
        if macd_hist > 0:
            score += 8
            signals.append(f"MACD 柱={macd_hist:.4f}，多头动能占优")
        else:
            score -= 4
            signals.append(f"MACD 柱={macd_hist:.4f}，动能偏弱")

    volume_ratio = latest.get("volume_ratio_5", np.nan)
    if pd.notna(volume_ratio):
        if volume_ratio > 1.5:
            score += 6
            signals.append(f"量比={volume_ratio:.2f}，近期放量")
        elif volume_ratio < 0.5:
            score -= 4
            signals.append(f"量比={volume_ratio:.2f}，交投收缩")
        else:
            signals.append(f"量比={volume_ratio:.2f}")

    return float(max(0, min(100, score))), signals


# ============ Machine learning layer ============


def safe_auc(y_true: np.ndarray, y_prob: np.ndarray) -> Optional[float]:
    try:
        if len(set(y_true.tolist())) < 2:
            return None
        return float(roc_auc_score(y_true, y_prob))
    except Exception:
        return None


def predict_positive_probability(model, row: pd.DataFrame) -> Optional[float]:
    try:
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(row)
            classes = getattr(model, "classes_", None)
            if classes is None and hasattr(model, "named_steps"):
                classes = getattr(model.named_steps.get("model"), "classes_", None)
            if classes is not None:
                class_list = list(classes)
                if 1 in class_list:
                    return float(probabilities[0][class_list.index(1)])
                return 1.0 if class_list and class_list[0] == 1 else 0.0
            if probabilities.shape[1] > 1:
                return float(probabilities[0][1])
            return float(probabilities[0][0])
        if hasattr(model, "decision_function"):
            raw = float(model.decision_function(row)[0])
            return 1 / (1 + math.exp(-raw))
    except Exception:
        return None
    return None


def build_ml_dataset(
    df: pd.DataFrame, horizon: int, min_edge: float = DEFAULT_MIN_EDGE
) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    feature_df = df[FEATURE_COLUMNS].copy()
    target_return = df["close"].shift(-horizon) / df["close"] - 1
    dataset = pd.concat([feature_df, target_return.rename("forward_return")], axis=1).dropna()
    dataset["target"] = (dataset["forward_return"] > min_edge).astype(int)
    if len(dataset) < 80:
        return pd.DataFrame(), pd.Series(dtype=int), feature_df.tail(1), pd.Series(dtype="float64")
    return (
        dataset[FEATURE_COLUMNS],
        dataset["target"].astype(int),
        feature_df.tail(1),
        dataset["forward_return"].astype("float64"),
    )


def make_time_series_splitter(horizon: int) -> TimeSeriesSplit:
    return TimeSeriesSplit(n_splits=3, gap=max(1, horizon))


def run_time_series_cv(model, x: pd.DataFrame, y: pd.Series, horizon: int) -> Tuple[Optional[float], Optional[float]]:
    if len(x) < 120:
        return None, None
    splitter = make_time_series_splitter(horizon)
    accuracies: List[float] = []
    aucs: List[float] = []
    for train_idx, test_idx in splitter.split(x):
        x_train, x_test = x.iloc[train_idx], x.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        try:
            fold_model = clone(model)
            fold_model.fit(x_train, y_train)
            pred = fold_model.predict(x_test)
            accuracies.append(float(accuracy_score(y_test, pred)))
            if hasattr(fold_model, "predict_proba"):
                probabilities_raw = fold_model.predict_proba(x_test)
                classes = getattr(fold_model, "classes_", None)
                if classes is None and hasattr(fold_model, "named_steps"):
                    classes = getattr(fold_model.named_steps.get("model"), "classes_", None)
                if classes is not None and 1 in list(classes):
                    probabilities = probabilities_raw[:, list(classes).index(1)]
                elif probabilities_raw.shape[1] > 1:
                    probabilities = probabilities_raw[:, 1]
                else:
                    probabilities = probabilities_raw[:, 0]
            elif hasattr(fold_model, "decision_function"):
                raw = fold_model.decision_function(x_test)
                probabilities = 1 / (1 + np.exp(-raw))
            else:
                probabilities = None
            if probabilities is not None:
                auc = safe_auc(y_test.to_numpy(), probabilities)
                if auc is not None:
                    aucs.append(auc)
        except Exception:
            continue
    acc = float(np.mean(accuracies)) if accuracies else None
    auc = float(np.mean(aucs)) if aucs else None
    return acc, auc


def make_models() -> List[Tuple[str, object]]:
    return [
        (
            "正则化逻辑回归",
            Pipeline(
                [
                    ("scaler", StandardScaler()),
                    ("model", LogisticRegression(C=0.8, max_iter=1200, class_weight="balanced")),
                ]
            ),
        ),
        ("决策树", DecisionTreeClassifier(max_depth=4, min_samples_leaf=10, random_state=42)),
        (
            "随机森林",
            RandomForestClassifier(
                n_estimators=180,
                max_depth=5,
                min_samples_leaf=8,
                random_state=42,
                class_weight="balanced_subsample",
            ),
        ),
        (
            "极端随机树",
            ExtraTreesClassifier(
                n_estimators=220,
                max_depth=5,
                min_samples_leaf=8,
                random_state=42,
                class_weight="balanced",
            ),
        ),
        (
            "支持向量机",
            Pipeline(
                [
                    ("scaler", StandardScaler()),
                    ("model", SVC(C=0.9, kernel="rbf", probability=True, class_weight="balanced")),
                ]
            ),
        ),
        (
            "KNN实例学习",
            Pipeline(
                [
                    ("scaler", StandardScaler()),
                    ("model", KNeighborsClassifier(n_neighbors=11, weights="distance")),
                ]
            ),
        ),
        (
            "神经网络MLP",
            Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "model",
                        MLPClassifier(
                            hidden_layer_sizes=(32, 16),
                            alpha=0.01,
                            max_iter=800,
                            random_state=42,
                            early_stopping=True,
                        ),
                    ),
                ]
            ),
        ),
    ]


def markov_regime(df: pd.DataFrame) -> Tuple[str, Dict[str, float]]:
    ret = df["ret_1"].dropna()
    if len(ret) < 40:
        return "样本不足", {}
    states = pd.cut(
        ret,
        bins=[-np.inf, -0.005, 0.005, np.inf],
        labels=["下跌", "震荡", "上涨"],
    )
    transitions = pd.DataFrame({"state": states, "next": states.shift(-1)}).dropna()
    current = str(states.iloc[-1])
    current_transitions = transitions[transitions["state"] == current]["next"]
    if current_transitions.empty:
        return current, {}
    probs = current_transitions.value_counts(normalize=True).to_dict()
    return current, {str(k): float(v) for k, v in probs.items()}


def bayesian_win_rate(y: pd.Series) -> Tuple[float, Optional[Tuple[float, float]]]:
    wins = int(y.sum())
    losses = int(len(y) - wins)
    alpha = 1 + wins
    beta = 1 + losses
    mean = alpha / (alpha + beta)
    if beta_dist is None:
        return mean, None
    return mean, (float(beta_dist.ppf(0.05, alpha, beta)), float(beta_dist.ppf(0.95, alpha, beta)))


def cluster_profile(
    x: pd.DataFrame,
    latest: pd.DataFrame,
    forward_return: pd.Series,
) -> Tuple[Optional[int], Optional[float], Optional[float]]:
    if len(x) < 100:
        return None, None, None
    try:
        scaler = StandardScaler()
        scaled = scaler.fit_transform(x)
        model = KMeans(n_clusters=3, n_init=20, random_state=42)
        labels = model.fit_predict(scaled)
        current_cluster = int(model.predict(scaler.transform(latest[FEATURE_COLUMNS]))[0])
        aligned_returns = forward_return.loc[x.index]
        cluster_returns = aligned_returns[pd.Series(labels, index=x.index) == current_cluster].dropna()
        if cluster_returns.empty:
            return current_cluster, None, None
        return current_cluster, float((cluster_returns > 0).mean()), float(cluster_returns.mean())
    except Exception:
        return None, None, None


def pca_profile(x: pd.DataFrame) -> Tuple[Optional[int], Optional[float]]:
    if len(x) < 80:
        return None, None
    try:
        scaled = StandardScaler().fit_transform(x)
        pca = PCA(n_components=0.85, random_state=42)
        pca.fit(scaled)
        return int(pca.n_components_), float(np.sum(pca.explained_variance_ratio_))
    except Exception:
        return None, None


def run_ml_models(df: pd.DataFrame, horizon: int = 5, min_edge: float = DEFAULT_MIN_EDGE) -> MLResult:
    if not SKLEARN_AVAILABLE:
        return MLResult(False, horizon=horizon, min_edge=min_edge, warning="未安装 scikit-learn，已退回技术指标模型。")

    x, y, latest, forward_return = build_ml_dataset(df, horizon, min_edge)
    if x.empty or latest.empty or latest.isna().any(axis=None):
        return MLResult(
            False,
            model_rows=len(x),
            horizon=horizon,
            min_edge=min_edge,
            warning="可训练样本不足，建议至少 180 个交易日。",
        )

    votes: List[Tuple[str, float, Optional[float], Optional[float]]] = []
    skipped_for_auc = 0
    for name, model in make_models():
        try:
            acc, auc = run_time_series_cv(model, x, y, horizon)
            if auc is not None and auc < MIN_MODEL_AUC:
                skipped_for_auc += 1
                continue
            model.fit(x, y)
            probability = predict_positive_probability(model, latest[FEATURE_COLUMNS])
            if probability is not None and np.isfinite(probability):
                votes.append((name, probability, acc, auc))
        except Exception:
            continue

    if not votes:
        warning = "模型训练失败，已退回技术指标模型。"
        if skipped_for_auc:
            warning = f"全部候选模型的样本外 AUC 低于 {MIN_MODEL_AUC:.2f} 或训练失败，已退回技术指标模型。"
        return MLResult(False, model_rows=len(x), horizon=horizon, min_edge=min_edge, warning=warning)

    probabilities = np.array([item[1] for item in votes], dtype="float64")
    ensemble_prob = float(np.mean(probabilities))
    cluster_id, cluster_wr, cluster_ret = cluster_profile(x, latest, forward_return)
    pca_components, pca_explained = pca_profile(x)
    state, transition_probs = markov_regime(df)
    bayes_mean, bayes_interval = bayesian_win_rate(y)
    ensemble_note = (
        f"标签为未来{horizon}日收益超过{min_edge * 100:.2f}%的概率，"
        f"CV使用{horizon}日gap避免标签跨期泄漏；"
        f"过滤样本外AUC低于{MIN_MODEL_AUC:.2f}的模型后简单平均。"
    )
    if skipped_for_auc:
        ensemble_note += f" 已过滤{skipped_for_auc}个弱验证模型。"

    return MLResult(
        available=True,
        probability=ensemble_prob,
        score=ensemble_prob * 100,
        model_rows=len(x),
        horizon=horizon,
        min_edge=min_edge,
        model_votes=votes,
        ensemble_note=ensemble_note,
        pca_components=pca_components,
        pca_explained=pca_explained,
        cluster_id=cluster_id,
        cluster_win_rate=cluster_wr,
        cluster_avg_forward_return=cluster_ret,
        markov_state=state,
        markov_probs=transition_probs,
        bayes_mean=bayes_mean,
        bayes_interval=bayes_interval,
    )


# ============ Decision and report ============


def risk_score(df: pd.DataFrame, max_drawdown: float) -> float:
    latest = df.iloc[-1]
    annual_vol = latest.get("volatility_20", np.nan)
    atr_pct = latest.get("atr_pct_14", np.nan)
    penalty = min(max_drawdown * 1.4, 45)
    if pd.notna(annual_vol):
        penalty += min(annual_vol * 55, 30)
    if pd.notna(atr_pct):
        penalty += min(atr_pct * 500, 20)
    return float(max(0, min(100, 100 - penalty)))


def final_decision(ta_score: float, ml: MLResult, risk: float) -> Tuple[float, str]:
    if ml.available and ml.score is not None:
        score = 0.50 * ta_score + 0.35 * ml.score + 0.15 * risk
    else:
        score = 0.75 * ta_score + 0.25 * risk

    score = float(max(0, min(100, score)))
    if risk < 25:
        return score, "高风险观察 / 不开新仓"
    if score >= 72:
        return score, "强研究信号 / 等回测确认后分批"
    if score >= 58:
        return score, "偏积极观察 / 等待确认"
    if score >= 45:
        return score, "观望"
    if score >= 32:
        return score, "减仓或回避"
    return score, "高风险回避"


def position_advice(final_score: float, max_drawdown: float, annual_vol: Optional[float]) -> str:
    if final_score < 45 or max_drawdown > 35:
        return "单标的仓位建议 0%，当前仅保留观察，不开新仓。"
    cap = 20.0
    if final_score < 58:
        cap = 0.0
    elif final_score < 72:
        cap = 12.0
    if max_drawdown > 20:
        cap *= 0.5
    if annual_vol is not None and pd.notna(annual_vol) and annual_vol > 0.45:
        cap *= 0.75
    if cap <= 0:
        return "单标的仓位建议 0%，等待评分和风险状态改善。"
    return f"研究仓位上限 ≤{cap:.1f}%，仅适合回测验证后的分批试错，跌破风控位减仓。"


def format_pct(value: Optional[float], digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value * 100:.{digits}f}%"


def feasibility_summary() -> str:
    return (
        "方法取舍: 已落地归一化、决策树、随机森林、极端随机树、正则化逻辑回归、"
        "KNN实例学习、SVM、MLP神经网络、PCA降维、KMeans聚类、马尔可夫状态转移、"
        "贝叶斯胜率估计和集成概率；ML 验证使用时间序列 gap，标签按交易摩擦阈值过滤。暂不引入重量级概率编程/深度时序网络作为默认路径，"
        "原因是单只 A 股历史样本偏少，容易过拟合；更适合在全市场因子库和回测框架完善后加入。"
    )


def analyze_stock(stock: str, days: int = 360, source: str = "auto", horizon: int = 5) -> str:
    reset_fetch_errors()
    stock_code = normalize_stock_code(stock)
    if not (stock_code.isdigit() and len(stock_code) == 6):
        return "股票代码格式错误：当前 A 股模式请输入 6 位代码，例如 600519、000001、300750。"

    data = get_stock_data(stock_code, days, source)
    if not data or data.frame.empty:
        realtime_quote = get_tencent_realtime_quote(stock_code)
        quote_line = f"\n{realtime_quote}" if realtime_quote else "\n实时行情兜底也失败。"
        return (
            f"无法获取 {stock_code} 的历史行情。"
            "A 股建议优先使用 --source auto 或 --source tencent；"
            "eastmoney 为实验入口。"
            f"\n失败链路: {fetch_error_summary()}"
            f"\n分层诊断: {fetch_error_summary_by_stage()}"
            f"{quote_line}"
        )

    df = add_indicators(data.frame)
    if len(df) < 80:
        return f"{stock_code} 可用数据不足，至少需要约 80 个交易日。"

    closes = df["close"].tolist()
    ta_score, signals = technical_score(df)
    max_dd = calc_max_drawdown(closes)
    risk = risk_score(df, max_dd)
    ml = run_ml_models(df, horizon)
    final_score, suggestion = final_decision(ta_score, ml, risk)

    latest = df.iloc[-1]
    previous = df.iloc[-2]
    change_pct = (latest["close"] / previous["close"] - 1) * 100
    annual_vol = latest.get("volatility_20", np.nan)
    position = position_advice(final_score, max_dd, annual_vol)

    model_lines = []
    if ml.available and ml.model_votes:
        top_votes = sorted(ml.model_votes, key=lambda item: item[1], reverse=True)
        for name, probability, acc, auc in top_votes:
            acc_text = f", CV准确率={acc:.2f}" if acc is not None else ""
            auc_text = f", AUC={auc:.2f}" if auc is not None else ""
            model_lines.append(f"  - {name}: edge概率={probability * 100:.1f}%{acc_text}{auc_text}")
    else:
        model_lines.append(f"  - 机器学习层未启用: {ml.warning}")

    markov_text = "N/A"
    if ml.markov_probs:
        markov_text = ", ".join(f"{state}:{prob * 100:.1f}%" for state, prob in ml.markov_probs.items())

    bayes_text = "N/A"
    if ml.bayes_mean is not None:
        bayes_text = f"后验均值={ml.bayes_mean * 100:.1f}%"
        if ml.bayes_interval:
            bayes_text += f"，90%区间={ml.bayes_interval[0] * 100:.1f}%~{ml.bayes_interval[1] * 100:.1f}%"

    cluster_text = "N/A"
    if ml.cluster_id is not None:
        cluster_text = f"簇{ml.cluster_id}"
        if ml.cluster_win_rate is not None:
            cluster_text += f"，历史胜率={ml.cluster_win_rate * 100:.1f}%"
        if ml.cluster_avg_forward_return is not None:
            cluster_text += f"，平均{horizon}日收益={ml.cluster_avg_forward_return * 100:.2f}%"

    pca_text = "N/A"
    if ml.pca_components is not None and ml.pca_explained is not None:
        pca_text = f"{ml.pca_components}个主成分解释{ml.pca_explained * 100:.1f}%特征方差"

    if ml.available and ml.score is not None and ml.probability is not None:
        ml_score_line = (
            f"- 机器学习分: {ml.score:.1f}/100，"
            f"未来{horizon}日收益超过{ml.min_edge * 100:.2f}%的概率={ml.probability * 100:.1f}%"
        )
    else:
        ml_score_line = f"- 机器学习分: 未启用，{ml.warning}"

    report = f"""
量化研究决策报告 - {data.stock_code} ({data.stock_name})
============================================================
分析时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
数据源: {data.source}
数据范围: {df["date"].iloc[0].date()} 至 {df["date"].iloc[-1].date()} ({len(df)}个交易日)
数据说明: {data.source_note or "日线行情用于研究分析，未包含财务、公告和交易成本。"}

当前价格: {latest["close"]:.2f} ({change_pct:+.2f}%)
综合评分: {final_score:.1f}/100
交易建议: {suggestion}

评分拆解
- 技术指标分: {ta_score:.1f}/100
{ml_score_line}
- 风险韧性分: {risk:.1f}/100
"""

    report += f"""
技术指标
- MA5={latest.get("ma_5", np.nan):.2f}, MA10={latest.get("ma_10", np.nan):.2f}, MA20={latest.get("ma_20", np.nan):.2f}, MA60={latest.get("ma_60", np.nan):.2f}
- RSI(14)={latest.get("rsi_14", np.nan):.2f}, KDJ-J={latest.get("kdj_j", np.nan):.2f}, MACD柱={latest.get("macd_hist", np.nan):.4f}
- 20日年化波动率={format_pct(annual_vol)}, ATR(14)/收盘价={format_pct(latest.get("atr_pct_14", np.nan))}

信号解释
"""
    for signal in signals:
        report += f"- {signal}\n"

    report += "\n机器学习与统计层\n"
    report += "\n".join(model_lines)
    report += f"""
- 集成说明: {ml.ensemble_note if ml.available else "样本或依赖不足时自动退回技术指标。"}
- PCA降维: {pca_text}
- 聚类分析: {cluster_text}
- 马尔可夫链: 当前状态={ml.markov_state or "N/A"}，下一日转移概率={markov_text}
- 贝叶斯胜率: {bayes_text}

风控
- 近{days}日最大回撤: {max_dd:.2f}% {"OK" if max_dd <= 20 else "超过20%，需降低仓位"}
- {position}
- 止损参考: 若跌破20日均线且机器学习 edge 概率低于50%，优先降仓；若最大回撤继续扩大，暂停加仓。

系统可行性结论
- {feasibility_summary()}

风险提示: 本报告只用于量化研究和辅助决策，不构成投资建议或自动交易信号。A 股存在涨跌停、停牌、流动性和政策冲击，实盘前必须做全市场回测、交易成本建模和样本外验证。
"""
    return report.strip()


def check_stock_data(stock: str, days: int = 120, source: str = "auto") -> str:
    probe = probe_stock_data(stock, days=days, source=source)
    return render_data_check_probe(probe)


def probe_stock_data(stock: str, days: int = 120, source: str = "auto") -> DataCheckProbe:
    reset_fetch_errors()
    stock_code = normalize_stock_code(stock)
    if not (stock_code.isdigit() and len(stock_code) == 6):
        return DataCheckProbe(
            passed=False,
            stock_code=stock_code,
            error_summary="股票代码格式错误：当前 A 股模式请输入 6 位代码，例如 600519、000001、300750。",
            staged_error_summary="输入校验未通过。",
        )

    data = get_stock_data(stock_code, days, source)
    realtime_quote = get_tencent_realtime_quote(stock_code) or ""
    if not data or data.frame.empty:
        return DataCheckProbe(
            passed=False,
            stock_code=stock_code,
            realtime_quote=realtime_quote,
            error_summary=fetch_error_summary(),
            staged_error_summary=fetch_error_summary_by_stage(),
        )

    latest = data.frame.iloc[-1]
    return DataCheckProbe(
        passed=True,
        stock_code=data.stock_code,
        stock_name=data.stock_name,
        source=data.source,
        row_count=len(data.frame),
        start_date=str(data.frame["date"].iloc[0].date()),
        end_date=str(latest["date"].date()),
        latest_line=(
            f"收盘={latest['close']:.2f}，开盘={latest['open']:.2f}，"
            f"最高={latest['high']:.2f}，最低={latest['low']:.2f}，成交量={latest['volume']:.0f}"
        ),
        source_note=data.source_note or "日线行情用于研究分析，未包含财务、公告和交易成本。",
        realtime_quote=realtime_quote,
        error_summary=fetch_error_summary(),
        staged_error_summary=fetch_error_summary_by_stage(),
    )


def render_data_check_probe(probe: DataCheckProbe) -> str:
    if not probe.passed:
        quote_line = f"\n{probe.realtime_quote}" if probe.realtime_quote else "\n实时行情兜底也失败。"
        return (
            f"数据检查失败 - {probe.stock_code}\n"
            f"历史行情: 未取得\n"
            f"失败链路: {probe.error_summary}"
            f"\n分层诊断: {probe.staged_error_summary}"
            f"{quote_line}"
        )

    return (
        f"数据检查通过 - {probe.stock_code} ({probe.stock_name})\n"
        f"历史行情: {probe.source}，{probe.row_count}个交易日，"
        f"{probe.start_date} 至 {probe.end_date}\n"
        f"最新K线: {probe.latest_line}\n"
        f"数据说明: {probe.source_note}"
        f"{chr(10) + probe.realtime_quote if probe.realtime_quote else ''}"
    )


def split_stock_list(value: str) -> List[str]:
    stocks = []
    for item in value.replace("，", ",").split(","):
        item = item.strip()
        if item:
            stocks.append(item)
    return stocks


def render_health_check(stocks: List[str], days: int = 120, source: str = "auto") -> str:
    probes = [probe_stock_data(stock, days=days, source=source) for stock in stocks]
    passed = [probe for probe in probes if probe.passed]
    failed = [probe for probe in probes if not probe.passed]

    if not probes:
        return "数据链路健康检查失败：未提供哨兵股票。"

    status = "通过" if not failed else "失败"
    lines = [
        "A股数据链路健康检查",
        "====================",
        f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"数据源策略: {source}",
        f"样本窗口: {days}个交易日",
        f"总体结论: {status} ({len(passed)}/{len(probes)} 通过)",
        "",
        "哨兵标的",
    ]
    for probe in probes:
        if probe.passed:
            lines.append(
                f"- OK {probe.stock_code} {probe.stock_name}: {probe.source}，"
                f"{probe.row_count}条，{probe.start_date}至{probe.end_date}"
            )
        else:
            lines.append(f"- FAIL {probe.stock_code}: {probe.error_summary}")

    if failed:
        lines.extend(["", "失败诊断"])
        for probe in failed:
            quote = probe.realtime_quote or "实时行情兜底也失败"
            lines.append(f"- {probe.stock_code}: {probe.staged_error_summary}；{quote}")
        lines.extend(
            [
                "",
                "产品门禁: 不建议继续跑完整分析、训练或自动化复盘；先修复历史行情源，避免空数据报告。",
            ]
        )
    else:
        sources = sorted({probe.source for probe in passed})
        lines.extend(
            [
                "",
                f"可用源: {'；'.join(sources)}",
                "产品门禁: 可以继续跑完整单票分析、题材复盘或自动化训练；实盘前仍需回测、交易成本和人工复核。",
            ]
        )
    return "\n".join(lines)


def render_observe_scan(stocks: List[str], days: int = 120, source: str = "auto") -> str:
    probes = [probe_stock_data(stock, days=days, source=source) for stock in stocks]
    passed = [probe for probe in probes if probe.passed]
    failed = [probe for probe in probes if not probe.passed]

    if not probes:
        return "交易观测池扫描失败：未提供候选股票。"

    lines = [
        "A股交易观测池扫描",
        "==================",
        f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"数据源策略: {source}",
        f"样本窗口: {days}个交易日",
        f"当前可观测: {len(passed)}/{len(probes)}",
        "",
        "可进入实盘训练观察",
    ]

    if passed:
        for probe in passed:
            realtime = f"；{probe.realtime_quote}" if probe.realtime_quote else "；实时行情未返回，仅使用历史日线"
            lines.append(
                f"- {probe.stock_code} {probe.stock_name}: {probe.source}，"
                f"{probe.row_count}条，{probe.start_date}至{probe.end_date}{realtime}"
            )
    else:
        lines.append("- 无")

    if failed:
        lines.extend(["", "暂不纳入观察"])
        for probe in failed:
            lines.append(f"- {probe.stock_code}: {probe.staged_error_summary}")

    lines.extend(
        [
            "",
            "训练门禁: 只对可观测标的做实盘判断；失败标的仅作为数据链路故障样本，不做交易判断。",
        ]
    )
    return "\n".join(lines)


def render_pool_scan(
    stocks: List[str],
    days: int = 120,
    source: str = "auto",
    horizon: int = 5,
    allow_cache_pool: bool = False,
    universe_note: str = "",
) -> str:
    if not stocks:
        return "股票池构建失败：未提供候选股票。"

    network_ok, network_note = a_share_network_preflight()
    if not network_ok and not allow_cache_pool:
        return "\n".join(
            [
                "股票池构建失败",
                "==============",
                f"构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"网络预检: 失败 - {network_note}",
                "实盘训练门禁: 当前环境无法访问实时/准实时公开行情源，不构建股票池。",
                "下一步: 必须在外部网络可用环境中重跑同一命令；如只做离线回放，显式添加 --allow-cache-pool。",
            ]
        )

    picked = []
    rejected = []
    failed = []

    for stock in stocks:
        reset_fetch_errors()
        stock_code = normalize_stock_code(stock)
        if network_ok:
            data = get_stock_data(stock_code, days, source)
        elif source in ("auto", "tencent") and stock_code.isdigit() and len(stock_code) == 6:
            data = get_tencent_data_via_curl(stock_code, days, allow_network=False)
        else:
            data = None
        if not data or data.frame.empty:
            failed.append((stock_code, fetch_error_summary_by_stage()))
            continue

        df = add_indicators(data.frame)
        if len(df) < 80:
            rejected.append((stock_code, data.stock_name, "可用数据不足80个交易日"))
            continue

        latest = df.iloc[-1]
        previous = df.iloc[-2]
        ta_score, signals = technical_score(df)
        max_dd = calc_max_drawdown(df["close"].tolist())
        risk = risk_score(df, max_dd)
        ml = run_ml_models(df, horizon)
        final_score, suggestion = final_decision(ta_score, ml, risk)
        change_pct = (latest["close"] / previous["close"] - 1) * 100
        volume_z = latest.get("volume_z_20", np.nan)
        trend_text = "弱势"
        if latest.get("ma_5", np.nan) > latest.get("ma_10", np.nan) > latest.get("ma_20", np.nan):
            trend_text = "短线偏强"
        elif latest.get("close", np.nan) > latest.get("ma_5", np.nan) > latest.get("ma_10", np.nan):
            trend_text = "尝试转强"

        picked.append(
            {
                "stock_code": data.stock_code,
                "stock_name": data.stock_name,
                "source": data.source,
                "row_count": len(df),
                "latest_date": str(latest["date"].date()),
                "close": float(latest["close"]),
                "change_pct": float(change_pct),
                "final_score": float(final_score),
                "ta_score": float(ta_score),
                "risk_score": float(risk),
                "suggestion": suggestion,
                "trend": trend_text,
                "volume_state": "放量" if pd.notna(volume_z) and volume_z > 0.8 else "缩量或正常",
                "position": position_advice(final_score, max_dd, latest.get("volatility_20", np.nan)),
                "signals": signals[:3],
            }
        )

    picked.sort(key=lambda item: item["final_score"], reverse=True)
    watch_pool = [item for item in picked if item["final_score"] >= 45]
    defense_pool = [item for item in picked if item["final_score"] < 45]

    lines = [
        "A股训练股票池构建",
        "==================",
        f"构建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"数据源策略: {source}",
        f"样本窗口: {days}个交易日",
        f"网络预检: {'通过' if network_ok else '失败'} - {network_note}",
        f"缓存池模式: {'允许' if allow_cache_pool else '禁止'}",
        f"股票宇宙: {universe_note or '用户指定候选'}",
        f"候选数量: {len(stocks)}",
        f"可评分: {len(picked)}",
        f"进入观察池: {len(watch_pool)}",
        "",
        "观察池",
    ]

    if watch_pool:
        for item in watch_pool:
            lines.append(
                f"- {item['stock_code']} {item['stock_name']}: {item['final_score']:.1f}/100，"
                f"{item['suggestion']}，{item['trend']}，{item['volume_state']}，"
                f"收盘={item['close']:.2f}({item['change_pct']:+.2f}%)"
            )
    else:
        lines.append("- 无；当前没有达到45分观察门槛的标的。")

    lines.append("")
    lines.append("防守样本")
    if defense_pool:
        for item in defense_pool:
            lines.append(
                f"- {item['stock_code']} {item['stock_name']}: {item['final_score']:.1f}/100，"
                f"{item['suggestion']}，仅用于判断对错训练。"
            )
    else:
        lines.append("- 无")

    if rejected:
        lines.extend(["", "数据不足剔除"])
        for stock_code, stock_name, reason in rejected:
            lines.append(f"- {stock_code} {stock_name}: {reason}")

    if failed:
        lines.extend(["", "取数失败剔除"])
        for stock_code, reason in failed:
            lines.append(f"- {stock_code}: {reason}")

    lines.extend(
        [
            "",
            "训练门禁: 股票池只用于训练/研究；未进入观察池的标的不做交易判断，观察池标的也不构成投资建议。",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="A股量化分析与机器学习选股辅助")
    parser.add_argument("--stock", "-s", type=str, help="股票代码或内置名称")
    parser.add_argument("--days", "-d", type=int, default=360, help="分析天数，建议 240-720")
    parser.add_argument(
        "--source",
        choices=["auto", "premium", "push", "pull", "tushare", "tencent", "eastmoney", "stooq"],
        default="premium",
        help="数据源。premium=推送缓存优先+专业源回退；push=只读推送缓存；pull=主动拉取专业/免费源。",
    )
    parser.add_argument("--horizon", type=int, default=5, help="机器学习预测未来N日方向")
    parser.add_argument(
        "--data-check",
        action="store_true",
        help="只检查行情数据源和实时报价，不运行指标和机器学习模型。",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="批量检查 A 股数据链路健康度；用于自动化和完整分析前的产品门禁。",
    )
    parser.add_argument(
        "--cache-health",
        action="store_true",
        help="检查本地行情缓存是否足够新鲜，作为自动回测/参数优化前的离线门禁。",
    )
    parser.add_argument(
        "--discover-cache-pool",
        action="store_true",
        help="扫描本地缓存，输出满足窗口/年龄的可回测股票池 JSON。",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="主动刷新行情缓存，并把拉取结果保存为推送快照缓存。",
    )
    parser.add_argument(
        "--import-cache-csv",
        type=str,
        default="",
        help="从本地 CSV 导入 OHLCV 行情并写入推送快照缓存。",
    )
    parser.add_argument(
        "--observe-scan",
        action="store_true",
        help="扫描当前可进入实盘训练观察的标的；失败标的不会阻断已通过标的。",
    )
    parser.add_argument(
        "--pool-scan",
        action="store_true",
        help="遍历候选股票并按既有量化逻辑构建训练股票池。",
    )
    parser.add_argument(
        "--allow-cache-pool",
        action="store_true",
        help="允许网络预检失败时用本地缓存构建离线训练池；实盘训练默认不要使用。",
    )
    parser.add_argument(
        "--health-stocks",
        type=str,
        default=",".join(DEFAULT_HEALTH_CHECK_STOCKS),
        help="健康检查哨兵股票，逗号分隔，默认 600519,000001,300750。",
    )
    parser.add_argument(
        "--cache-stocks",
        type=str,
        default=",".join(DEFAULT_HEALTH_CHECK_STOCKS),
        help="缓存健康检查或刷新标的，逗号分隔。",
    )
    parser.add_argument(
        "--cache-stock-name",
        type=str,
        default="",
        help="--import-cache-csv 时可指定股票名称。",
    )
    parser.add_argument(
        "--cache-provider",
        type=str,
        default="local-csv",
        help="--import-cache-csv 时写入缓存的 provider 名称。",
    )
    parser.add_argument(
        "--cache-max-age-hours",
        type=int,
        default=36,
        help="缓存健康检查允许的最大缓存年龄。",
    )
    parser.add_argument(
        "--cache-min-rows",
        type=int,
        default=80,
        help="缓存健康检查要求的最少 OHLCV 行数。",
    )
    parser.add_argument(
        "--cache-pool-limit",
        type=int,
        default=20,
        help="--discover-cache-pool 输出的最大股票数量。",
    )
    parser.add_argument(
        "--observe-stocks",
        type=str,
        default=",".join(DEFAULT_OBSERVE_SCAN_STOCKS),
        help="交易观测池候选股票，逗号分隔。",
    )
    parser.add_argument(
        "--pool-stocks",
        type=str,
        default="",
        help="股票池构建候选股票，逗号分隔；留空时按成交额拉取动态A股候选。",
    )
    parser.add_argument(
        "--pool-limit",
        type=int,
        default=DEFAULT_POOL_UNIVERSE_LIMIT,
        help="未指定 --pool-stocks 时，从动态A股列表按成交额取前N只。",
    )
    parser.add_argument(
        "--pool-universe",
        choices=["sector", "dynamic", "sector+dynamic"],
        default="sector+dynamic",
        help="未指定 --pool-stocks 时的股票宇宙：板块代表池、成交额动态池或两者叠加。",
    )
    args = parser.parse_args(argv)

    days = max(80, min(args.days, 1200))
    horizon = max(1, min(args.horizon, 20))
    if args.discover_cache_pool:
        result = discover_cached_stock_pool(
            days=days,
            min_rows=max(1, args.cache_min_rows),
            max_age_hours=max(1, args.cache_max_age_hours),
            limit=max(1, args.cache_pool_limit),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    if args.import_cache_csv:
        cache_stocks = split_stock_list(args.cache_stocks)
        if len(cache_stocks) != 1:
            parser.error("--import-cache-csv 需要 --cache-stocks 指定且只能指定一个 6 位代码。")
        result = import_market_csv_to_cache(
            csv_path=Path(args.import_cache_csv),
            stock_code=cache_stocks[0],
            stock_name=args.cache_stock_name,
            provider=args.cache_provider,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    if args.refresh_cache:
        result = refresh_market_cache(split_stock_list(args.cache_stocks), days=days, source=args.source)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    if args.cache_health:
        result = inspect_market_cache(
            split_stock_list(args.cache_stocks),
            days=days,
            min_rows=max(1, args.cache_min_rows),
            max_age_hours=max(1, args.cache_max_age_hours),
        )
        print(render_market_cache_health(result))
        return 0 if result.get("ok") else 2
    if args.health_check:
        print(render_health_check(split_stock_list(args.health_stocks), days=days, source=args.source))
    elif args.observe_scan:
        print(render_observe_scan(split_stock_list(args.observe_stocks), days=days, source=args.source))
    elif args.pool_scan:
        pool_stocks = split_stock_list(args.pool_stocks)
        universe_note = "用户指定候选"
        if not pool_stocks:
            if args.pool_universe == "dynamic":
                pool_stocks, universe_note = fetch_eastmoney_a_share_universe(args.pool_limit)
            elif args.pool_universe == "sector":
                pool_stocks, universe_note = build_sector_representative_universe(
                    include_dynamic=False,
                    dynamic_limit=args.pool_limit,
                )
            else:
                pool_stocks, universe_note = build_sector_representative_universe(
                    include_dynamic=True,
                    dynamic_limit=args.pool_limit,
                )
        print(
            render_pool_scan(
                pool_stocks,
                days=days,
                source=args.source,
                horizon=horizon,
                allow_cache_pool=args.allow_cache_pool,
                universe_note=universe_note,
            )
        )
    elif args.data_check:
        if not args.stock:
            parser.error("--data-check 需要 --stock。若要批量检查，请使用 --health-check。")
        print(check_stock_data(args.stock, days=days, source=args.source))
    else:
        if not args.stock:
            parser.error("完整分析需要 --stock。若要批量检查，请使用 --health-check。")
        print(analyze_stock(args.stock, days=days, source=args.source, horizon=horizon))
    return 0


if __name__ == "__main__":
    sys.exit(main())
