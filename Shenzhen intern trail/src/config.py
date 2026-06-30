from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_root: Path
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: int
    scan_interval_minutes: int
    run_during_market_hours_only: bool
    strict_news_required: bool
    enable_jin10: bool
    enable_wind: bool
    enable_baidu_hot: bool
    enable_google_trends: bool
    enable_official_media: bool
    jin10_mode: str
    jin10_api_url: str
    jin10_api_key: str
    wind_mode: str
    wind_csv_path: str


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(project_root: Path | None = None) -> Settings:
    root = project_root or Path(__file__).resolve().parents[1]
    env_values = load_env_file(root / ".env")

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key, env_values.get(key, default))

    return Settings(
        project_root=root,
        deepseek_api_key=get("DEEPSEEK_API_KEY"),
        deepseek_base_url=get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=get("DEEPSEEK_MODEL", "deepseek-chat"),
        deepseek_timeout_seconds=int(get("DEEPSEEK_TIMEOUT_SECONDS", "60") or "60"),
        scan_interval_minutes=int(get("SCAN_INTERVAL_MINUTES", "30") or "30"),
        run_during_market_hours_only=parse_bool(get("RUN_DURING_MARKET_HOURS_ONLY", "true"), True),
        strict_news_required=parse_bool(get("STRICT_NEWS_REQUIRED", "true"), True),
        enable_jin10=parse_bool(get("ENABLE_JIN10", "false")),
        enable_wind=parse_bool(get("ENABLE_WIND", "false")),
        enable_baidu_hot=parse_bool(get("ENABLE_BAIDU_HOT", "true"), True),
        enable_google_trends=parse_bool(get("ENABLE_GOOGLE_TRENDS", "true"), True),
        enable_official_media=parse_bool(get("ENABLE_OFFICIAL_MEDIA", "true"), True),
        jin10_mode=get("JIN10_MODE", "disabled").lower(),
        jin10_api_url=get("JIN10_API_URL", ""),
        jin10_api_key=get("JIN10_API_KEY", ""),
        wind_mode=get("WIND_MODE", "disabled").lower(),
        wind_csv_path=get("WIND_CSV_PATH", ""),
    )
