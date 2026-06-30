from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_html_report(path: Path, result: dict[str, Any]) -> None:
    status = result.get("strict_status", "UNKNOWN")
    buy_plans = result.get("buy_plans", [])
    rows = []
    for plan in buy_plans:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(plan.get('code', '')))}</td>"
            f"<td>{html.escape(str(plan.get('name', '')))}</td>"
            f"<td>{html.escape(str(plan.get('trigger', '')))}</td>"
            f"<td>{html.escape(str(plan.get('leader_rank', '')))}</td>"
            f"<td>{html.escape(str(plan.get('limit_price', '')))}</td>"
            f"<td>{html.escape(str(plan.get('reason', '')))}</td>"
            "</tr>"
        )
    source_items = "".join(f"<li>{html.escape(json.dumps(item, ensure_ascii=False))}</li>" for item in result.get("source_statuses", []))
    content = f"""<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><title>Shenzhen intern trail</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:24px;line-height:1.5}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px}}.status{{font-weight:700}}</style></head>
<body><h1>Shenzhen intern trail</h1><p class=\"status\">状态：{html.escape(str(status))}</p>
<p>时间：{html.escape(str(result.get('run_timestamp','')))}</p>
<h2>数据源状态</h2><ul>{source_items}</ul>
<h2>最终买入计划</h2><table><thead><tr><th>代码</th><th>名称</th><th>触发</th><th>梯队</th><th>挂单价</th><th>理由</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan=\"6\">无</td></tr>'}</tbody></table>
<h2>风险提示</h2><p>研究用途，不构成投资建议；不自动下单。</p></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
