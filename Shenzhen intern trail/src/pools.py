from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List

from .models import PoolEntry

POOL_LAYERS = ("hot", "screened", "trade")
DEFAULT_TTL_DAYS = 4


class PoolManager:
    """三层股池：hot(热点) / screened(筛选) / trade(交易)。

    每轮扫描更新各层：命中的刷新 last_seen 并清零未命中天数；未命中的累计天数；
    连续未命中满 TTL 天则淘汰。未成交的个股在各级股池满4天删除。"""

    def __init__(self, ttl_days: int = DEFAULT_TTL_DAYS) -> None:
        self.ttl_days = ttl_days
        self.entries: List[PoolEntry] = []

    @classmethod
    def load(cls, path: Path, ttl_days: int = DEFAULT_TTL_DAYS) -> "PoolManager":
        pm = cls(ttl_days)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pm.entries = [PoolEntry(**item) for item in data.get("entries", [])]
            except Exception:
                pm.entries = []
        return pm

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"entries": [e.__dict__ for e in self.entries]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def update(self, hit_by_layer: Dict[str, List[PoolEntry]], today: str) -> None:
        """用当轮命中的条目更新股池。hit_by_layer: {layer: [PoolEntry...]}。"""
        today_norm = today[:10]
        hit_keys = set()
        for layer, entries in hit_by_layer.items():
            for entry in entries:
                key = (layer, entry.code)
                hit_keys.add(key)
                existing = next((e for e in self.entries if e.layer == layer and e.code == entry.code), None)
                if existing:
                    existing.last_seen_at = today_norm
                    existing.days_in_pool = 0
                    existing.themes = entry.themes or existing.themes
                    existing.note = entry.note or existing.note
                else:
                    entry.entered_at = today_norm
                    entry.last_seen_at = today_norm
                    entry.days_in_pool = 0
                    self.entries.append(entry)

        # 未命中的累计天数，满 TTL 淘汰
        survivors: List[PoolEntry] = []
        for entry in self.entries:
            key = (entry.layer, entry.code)
            if key in hit_keys:
                survivors.append(entry)
                continue
            entry.days_in_pool += 1
            if entry.days_in_pool <= self.ttl_days:
                survivors.append(entry)
            # 超过 TTL 的丢弃（未成交个股满4天删除）
        self.entries = survivors

    def get_layer(self, layer: str) -> List[PoolEntry]:
        return [e for e in self.entries if e.layer == layer]

    def has_code(self, layer: str, code: str) -> bool:
        return any(e.layer == layer and e.code == code for e in self.entries)

    def summary(self) -> Dict[str, int]:
        return {layer: len(self.get_layer(layer)) for layer in POOL_LAYERS}
