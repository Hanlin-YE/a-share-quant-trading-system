#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Small web front-end for the A-share analyzer.

The app intentionally uses only the Python standard library so the project can
be opened as a portfolio demo without adding a separate backend stack.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse


ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "web"
ANALYZE_PATH = ROOT_DIR / "scripts" / "analyze.py"

SPEC = importlib.util.spec_from_file_location("analyze", ANALYZE_PATH)
analyze = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = analyze
SPEC.loader.exec_module(analyze)


ERROR_PREFIXES = (
    "股票代码格式错误",
    "无法获取",
    "数据检查失败",
    "可用数据不足",
)

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml; charset=utf-8",
}


def parse_float(value: str) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_percent(value: str) -> Optional[float]:
    cleaned = value.strip().rstrip("%")
    return parse_float(cleaned)


def extract_line(report: str, label: str) -> str:
    prefix = f"{label}:"
    for line in report.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.split(":", 1)[1].strip()
    return ""


def extract_bullets(report: str, heading: str, stop_headings: List[str]) -> List[str]:
    lines = report.splitlines()
    bullets: List[str] = []
    in_section = False
    stops = set(stop_headings)
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line == heading:
            in_section = True
            continue
        if in_section and line in stops:
            break
        if in_section and line.startswith("- "):
            bullets.append(line[2:].strip())
    return bullets


def extract_score(report: str, label: str) -> Optional[float]:
    line = extract_line(report, label)
    if not line:
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*/\s*100", line)
    return parse_float(match.group(1)) if match else None


def extract_metric(report: str, pattern: str, percent: bool = False) -> Optional[float]:
    match = re.search(pattern, report)
    if not match:
        return None
    value = match.group(1)
    return parse_percent(value) if percent else parse_float(value)


def parse_technical_metrics(report: str) -> Dict[str, Optional[float]]:
    technical_text = "\n".join(
        extract_bullets(
            report,
            "技术指标",
            ["信号解释", "机器学习与统计层", "风控", "系统可行性结论", "风险提示"],
        )
    )
    metric_source = technical_text or report
    return {
        "ma_5": extract_metric(metric_source, r"\bMA5=([-\d.]+)"),
        "ma_10": extract_metric(metric_source, r"\bMA10=([-\d.]+)"),
        "ma_20": extract_metric(metric_source, r"\bMA20=([-\d.]+)"),
        "ma_60": extract_metric(metric_source, r"\bMA60=([-\d.]+)"),
        "rsi_14": extract_metric(metric_source, r"RSI\(14\)=([-\d.]+)"),
        "kdj_j": extract_metric(metric_source, r"KDJ-J=([-\d.]+)"),
        "macd_hist": extract_metric(metric_source, r"MACD柱=([-\d.]+)"),
        "volume_ratio_5": extract_metric(report, r"量比=([-\d.]+)"),
        "volatility_20_pct": extract_metric(metric_source, r"20日年化波动率=([-\d.]+%)", percent=True),
        "atr_pct_14": extract_metric(metric_source, r"ATR\(14\)/收盘价=([-\d.]+%)", percent=True),
        "max_drawdown_pct": extract_metric(report, r"最大回撤:\s*([-\d.]+)%"),
    }


def parse_report_summary(report: str) -> Dict[str, Any]:
    title_match = re.search(r"量化研究决策报告\s*-\s*(\d{6})\s*\(([^)]+)\)", report)
    current_price = extract_line(report, "当前价格")
    price_match = re.search(r"(-?\d+(?:\.\d+)?)\s*\(([-+]\d+(?:\.\d+)?)%\)", current_price)
    data_range = extract_line(report, "数据范围")
    date_match = re.match(r"(.+?)\s+至\s+(.+?)\s+\((\d+)个交易日\)", data_range)

    risk_controls = extract_bullets(
        report,
        "风控",
        ["系统可行性结论", "风险提示"],
    )
    signals = extract_bullets(
        report,
        "信号解释",
        ["机器学习与统计层", "风控", "系统可行性结论"],
    )
    model_evidence = extract_bullets(
        report,
        "机器学习与统计层",
        ["风控", "系统可行性结论"],
    )

    return {
        "stock_code": title_match.group(1) if title_match else "",
        "stock_name": title_match.group(2) if title_match else "",
        "analysis_time": extract_line(report, "分析时间"),
        "data_source": extract_line(report, "数据源"),
        "data_note": extract_line(report, "数据说明"),
        "data_range": {
            "start": date_match.group(1) if date_match else "",
            "end": date_match.group(2) if date_match else "",
            "trading_days": int(date_match.group(3)) if date_match else None,
        },
        "price": {
            "close": parse_float(price_match.group(1)) if price_match else None,
            "change_pct": parse_float(price_match.group(2)) if price_match else None,
        },
        "scores": {
            "final": extract_score(report, "综合评分"),
            "technical": extract_score(report, "- 技术指标分"),
            "machine_learning": extract_score(report, "- 机器学习分"),
            "risk": extract_score(report, "- 风险韧性分"),
        },
        "technical_metrics": parse_technical_metrics(report),
        "suggestion": extract_line(report, "交易建议"),
        "signals": signals[:6],
        "model_evidence": model_evidence[:8],
        "risk_controls": risk_controls[:6],
    }


def build_analysis_response(stock: str, days: int = 360, source: str = "auto", horizon: int = 5) -> Dict[str, Any]:
    report = analyze.analyze_stock(stock, days=days, source=source, horizon=horizon)
    is_error = any(report.startswith(prefix) for prefix in ERROR_PREFIXES)
    if is_error:
        return {
            "ok": False,
            "error": report,
            "report": report,
            "disclaimer": "本系统仅用于量化研究和商业咨询展示，不构成投资建议或自动交易指令。",
        }

    payload = parse_report_summary(report)
    payload.update(
        {
            "ok": True,
            "report": report,
            "request": {
                "stock": stock,
                "days": days,
                "source": source,
                "horizon": horizon,
            },
            "disclaimer": "本系统仅用于量化研究和商业咨询展示，不构成投资建议或自动交易指令。实盘前必须结合回测、交易成本、流动性和人工复核。",
        }
    )
    return payload


def split_symbols(value: str) -> List[str]:
    symbols = [item.strip() for item in re.split(r"[,，\s]+", value or "") if item.strip()]
    return symbols[:100]


def webhook_secret() -> str:
    return os.environ.get("DATA_WEBHOOK_SECRET", "")


def refresh_secret() -> str:
    return os.environ.get("REFRESH_SECRET", "")


def expected_secret_for(path: str) -> str:
    if path == "/api/refresh":
        return refresh_secret() or webhook_secret()
    return webhook_secret()


def data_source_catalog() -> Dict[str, Any]:
    tushare_enabled = bool(analyze.tushare_token())
    push_enabled = bool(webhook_secret())
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "policy": "供应商推送优先，Tushare Pro 自动拉取次优先，多源交叉回退。",
        "sources": [
            {
                "id": "premium",
                "name": "专业优先",
                "tier": "primary",
                "enabled": True,
                "refresh": "推送缓存优先；无推送时交易日日频自动拉取",
                "description": "面向正式咨询演示的默认策略，先用供应商推送，再用可审计 API Key 数据源。",
            },
            {
                "id": "push",
                "name": "供应商推送",
                "tier": "realtime",
                "enabled": push_enabled,
                "refresh": "由数据供应商主动推送；系统收到后立即写入缓存",
                "description": "配置 DATA_WEBHOOK_SECRET 后启用 /api/webhooks/market-data 接收口。",
            },
            {
                "id": "tushare",
                "name": "Tushare Pro",
                "tier": "licensed",
                "enabled": tushare_enabled,
                "refresh": "交易日收盘后更新，具体以账号权限和接口返回为准",
                "description": "配置 TUSHARE_TOKEN 后启用；可提供 A 股日线、复权因子等结构化数据。",
            },
            {
                "id": "tencent",
                "name": "腾讯财经",
                "tier": "fallback",
                "enabled": True,
                "refresh": "交易日近实时/日线更新，免费接口稳定性需监控",
                "description": "当前 A 股免费主力兜底源，支持前复权日线和实时行情兜底。",
            },
            {
                "id": "eastmoney",
                "name": "东方财富",
                "tier": "fallback",
                "enabled": True,
                "refresh": "交易日更新，作为多源交叉校验和降级路径",
                "description": "免费实验源，适合在腾讯链路异常时辅助取数。",
            },
        ],
    }


def clamp_int(value: str, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


class ConsultingRequestHandler(BaseHTTPRequestHandler):
    server_version = "StockConsultingWeb/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - inherited name
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def send_bytes(
        self,
        body: bytes,
        status: HTTPStatus = HTTPStatus.OK,
        content_type: str = "text/plain",
        include_body: bool = True,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_bytes(body, status=status, content_type="application/json; charset=utf-8")

    def read_json_body(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 2_000_000:
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def secret_authorized(self, path: str) -> bool:
        expected = expected_secret_for(path)
        if not expected:
            return True
        provided = self.headers.get("X-Data-Secret") or self.headers.get("X-Webhook-Secret") or ""
        if not provided:
            parsed = urlparse(self.path)
            provided = (parse_qs(parsed.query).get("secret") or [""])[0]
        return provided == expected

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_json({"ok": True, "service": "stock-analyzer"})
            return

        if parsed.path == "/api/sources":
            self.send_json(data_source_catalog())
            return

        if parsed.path == "/api/analyze":
            params = parse_qs(parsed.query)
            stock = (params.get("stock") or [""])[0].strip()
            if not stock:
                self.send_json({"ok": False, "error": "请输入 6 位 A 股代码，例如 600519。"}, HTTPStatus.BAD_REQUEST)
                return
            days = clamp_int((params.get("days") or ["360"])[0], 360, 80, 1200)
            horizon = clamp_int((params.get("horizon") or ["5"])[0], 5, 1, 20)
            source = (params.get("source") or ["auto"])[0]
            if source not in {"auto", "premium", "push", "pull", "tushare", "tencent", "eastmoney", "stooq"}:
                source = "auto"
            status = HTTPStatus.OK
            payload = build_analysis_response(stock, days=days, source=source, horizon=horizon)
            if not payload.get("ok"):
                status = HTTPStatus.BAD_REQUEST
            self.send_json(payload, status)
            return

        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/webhooks/market-data":
            if not self.secret_authorized(parsed.path):
                self.send_json({"ok": False, "error": "Webhook secret 不正确"}, HTTPStatus.UNAUTHORIZED)
                return
            payload = self.read_json_body()
            if payload is None:
                self.send_json({"ok": False, "error": "请求体必须是 JSON 对象，且大小不超过 2MB"}, HTTPStatus.BAD_REQUEST)
                return
            result = analyze.save_pushed_market_data(payload)
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self.send_json(result, status)
            return

        if parsed.path == "/api/refresh":
            if not self.secret_authorized(parsed.path):
                self.send_json({"ok": False, "error": "Refresh secret 不正确"}, HTTPStatus.UNAUTHORIZED)
                return
            payload = self.read_json_body() or {}
            query = parse_qs(parsed.query)
            stocks = payload.get("stocks")
            if isinstance(stocks, list):
                stock_list = [str(item).strip() for item in stocks if str(item).strip()]
            else:
                stock_list = split_symbols(str(stocks or (query.get("stocks") or [""])[0]))
            if not stock_list:
                stock_list = ["600519", "000001", "300750"]
            days = clamp_int(str(payload.get("days") or (query.get("days") or ["720"])[0]), 720, 80, 1200)
            source = str(payload.get("source") or (query.get("source") or ["premium"])[0])
            if source not in {"premium", "pull", "tushare", "tencent", "eastmoney"}:
                source = "premium"
            self.send_json(analyze.refresh_market_cache(stock_list, days=days, source=source))
            return

        self.send_json({"ok": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        self.serve_static(parsed.path, include_body=False)

    def serve_static(self, request_path: str, include_body: bool = True) -> None:
        relative_path = "index.html" if request_path in {"/", ""} else request_path.lstrip("/")
        target = (STATIC_DIR / relative_path).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError:
            self.send_bytes(b"Not found", HTTPStatus.NOT_FOUND, include_body=include_body)
            return
        if not target.exists() or not target.is_file():
            self.send_bytes(b"Not found", HTTPStatus.NOT_FOUND, include_body=include_body)
            return
        content_type = MIME_TYPES.get(target.suffix, "application/octet-stream")
        self.send_bytes(target.read_bytes(), content_type=content_type, include_body=include_body)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    httpd = ThreadingHTTPServer((host, port), ConsultingRequestHandler)
    print(f"股票量化咨询网站已启动: http://{host}:{port}")
    httpd.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 A 股量化咨询网站")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=env_int("PORT", 8765))
    args = parser.parse_args()
    run(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
