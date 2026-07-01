from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .models import Position, SellSignal

MAX_SLOTS = 4
# 卖点参数
LEADER_LIE_PCT = -3.0  # 龙一涨幅<=-3% 视为"躺"
NOT_BOARD_PCT = 5.0  # 次日开盘10分钟内涨幅<5% 视为"不妙板"


class Portfolio:
    """分4仓滚动持仓。卖点：次日不妙板卖、龙一躺全躺止损、破趋势线卖。"""

    def __init__(self) -> None:
        self.positions: List[Position] = []
        self.cash = 0.0

    @classmethod
    def load(cls, path: Path) -> "Portfolio":
        pf = cls()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pf.positions = [Position(**item) for item in data.get("positions", [])]
                pf.cash = float(data.get("cash", 0.0))
            except Exception:
                pf.positions = []
        return pf

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"positions": [p.__dict__ for p in self.positions], "cash": self.cash},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def used_slots(self) -> set[int]:
        return {p.slot for p in self.positions}

    def next_slot(self) -> int | None:
        for slot in range(1, MAX_SLOTS + 1):
            if slot not in self.used_slots():
                return slot
        return None

    def open_position(self, pos: Position) -> bool:
        if len(self.positions) >= MAX_SLOTS:
            return False
        if pos.slot in self.used_slots():
            pos.slot = self.next_slot() or 0
        self.positions.append(pos)
        return True

    def close_position(self, code: str) -> Position | None:
        for i, p in enumerate(self.positions):
            if p.code == code:
                return self.positions.pop(i)
        return None

    def check_sell_signals(self, quotes: Dict[str, Dict]) -> List[SellSignal]:
        """quotes: {code: {pct_change, close, is_limit_up}}。检查所有持仓卖点。"""
        signals: List[SellSignal] = []
        for pos in self.positions:
            q = quotes.get(pos.code, {})
            leader_q = quotes.get(pos.leader_code, {})
            close = float(q.get("close", 0.0))
            pct = float(q.get("pct_change", 0.0))
            leader_pct = float(leader_q.get("pct_change", 0.0))

            # immediate：止损 或 龙一躺全躺
            if close > 0 and close <= pos.stop_loss:
                signals.append(SellSignal(pos.code, pos.name, pos.slot, f"触及止损价 {pos.stop_loss:.2f}", close, "immediate"))
                continue
            if leader_pct <= LEADER_LIE_PCT:
                signals.append(SellSignal(pos.code, pos.name, pos.slot, f"龙一({pos.leader_code})躺板(涨{leader_pct:.1f}%)，全躺止损", close, "immediate"))
                continue
            # normal：破趋势线
            if close > 0 and close < pos.trend_line:
                signals.append(SellSignal(pos.code, pos.name, pos.slot, f"破趋势线 {pos.trend_line:.2f}", close, "normal"))
                continue
            # normal：次日开盘10分钟不妙板
            if pct < NOT_BOARD_PCT:
                signals.append(SellSignal(pos.code, pos.name, pos.slot, f"次日开盘不妙板(涨{pct:.1f}%)，卖出", close, "normal"))
                continue
        return signals

    def summary(self) -> Dict:
        return {
            "used_slots": sorted(self.used_slots()),
            "free_slots": MAX_SLOTS - len(self.positions),
            "positions": [{"code": p.code, "name": p.name, "slot": p.slot, "cost": p.cost, "leader": p.leader_code} for p in self.positions],
        }
