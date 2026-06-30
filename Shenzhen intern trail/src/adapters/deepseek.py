from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import Settings


class DeepSeekError(RuntimeError):
    pass


def check_deepseek(settings: Settings) -> tuple[bool, str]:
    if not settings.deepseek_api_key:
        return False, "DEEPSEEK_API_KEY missing"
    try:
        payload = {
            "model": settings.deepseek_model,
            "messages": [{"role": "user", "content": "Return OK only."}],
            "max_tokens": 8,
            "temperature": 0,
        }
        request = urllib.request.Request(
            settings.deepseek_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.deepseek_api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=settings.deepseek_timeout_seconds) as response:
            return 200 <= response.status < 300, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def analyze_news_with_deepseek(settings: Settings, news_items: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.deepseek_api_key:
        raise DeepSeekError("DEEPSEEK_API_KEY missing")
    compact_items = [
        {
            "source": item.get("source", ""),
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "published_at": item.get("published_at", ""),
        }
        for item in news_items[:80]
    ]
    prompt = (
        "你是A股短线题材分析助手。请从新闻/热搜中提取可交易热点题材和可能相关个股。"
        "只输出JSON，不要解释。schema: {hot_themes:[{theme,confidence,reason,source_refs}],"
        "mentioned_stocks:[{code,name,theme,confidence,reason,source_refs}],summary:string}."
        "如果没有足够证据，返回空数组。\n新闻数据:\n" + json.dumps(compact_items, ensure_ascii=False)
    )
    payload = {
        "model": settings.deepseek_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 1800,
    }
    request = urllib.request.Request(
        settings.deepseek_base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.deepseek_api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.deepseek_timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise DeepSeekError(f"DeepSeek request failed: {type(exc).__name__}: {exc}") from exc
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
    if content.startswith("```json"):
        content = content[7:].strip()
    if content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise DeepSeekError(f"DeepSeek returned non-JSON content: {content[:200]}") from exc
    parsed["raw_model"] = settings.deepseek_model
    return parsed
