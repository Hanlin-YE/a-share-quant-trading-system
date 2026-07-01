"""工程化热点提取（纯 Python，零 LLM）。

提取管线：
1. 新闻关键词频次统计（财经词库 + N-gram）
2. 涨停板块聚类统计（资金面热点）
3. 交叉验证：新闻高频词 ∩ 涨停板块 = 强热点
4. 输出 hot_terms + 每个词的来源与置信度

LLM 可作为可选增强（见 cli.py），但不再是第一选择。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

# A股常见板块/概念关键词库（用于新闻命中判定，子串匹配）
SECTOR_KEYWORDS = [
    # 科技
    "半导体", "芯片", "光刻", "封测", "存储", "算力", "光模块", "AI", "人工智能", "大模型",
    "机器人", "人形机器人", "工业母机", "数控", "减速器", "传感器", "物联网", "车联网",
    "消费电子", "折叠屏", "MR", "VR", "AR", "智能穿戴", "PCB", "被动元件",
    # 新能源
    "光伏", "储能", "锂电", "电池", "钠电", "固态电池", "充电桩", "新能源车", "氢能",
    "风电", "核电", "特高压", "电网", "绿电", "稀土", "磁材",
    # 医药
    "创新药", "CXO", "医疗器械", "中药", "疫苗", "生物制品", "医保", "医美",
    # 军工航天
    "军工", "航天", "航空", "低空经济", "eVTOL", "卫星", "商业航天", "无人机",
    # 金融基建
    "券商", "银行", "保险", "地产", "基建", "一带一路", "央国企改革", "西部大开发",
    # 周期
    "有色", "铜", "铝", "黄金", "钢铁", "煤炭", "化工", "新材料", "钛白粉", "磷化工",
    # 消费
    "白酒", "食品", "旅游", "酒店", "零售", "跨境电商", "免税", "纺织服装",
    # 数字经济
    "数据要素", "数据", "数字经济", "工业互联网", "工业互联", "信创", "国产软件", "国产替代",
    "数字货币", "区块链", "AIGC", "Sora", "多模态",
    # 农业
    "种业", "转基因", "生猪", "化肥", "农业",
    # 其他
    "液冷", "算力租赁", "HBM", "先进封装", "碳纤维", "复合材料", "3D打印", "核聚变",
]

# 停用词（避免噪声）
STOPWORDS = {"中国", "公司", "股份", "集团", "有限公司", "今日", "昨日", "记者", "报道", "表示", "相关", "市场", "行情", "投资", "板块", "概念", "个股", "标的"}


def extract_news_keywords(news_items: list[dict[str, Any]], top_n: int = 30) -> list[tuple[str, int, list[str]]]:
    """从新闻标题/摘要统计财经关键词频次。

    返回 [(keyword, count, source_titles), ...] 按频次降序。
    """
    counter: Counter = Counter()
    sources: dict[str, list[str]] = defaultdict(list)
    for item in news_items:
        title = str(item.get("title", ""))
        summary = str(item.get("summary", ""))
        text = f"{title} {summary}"
        for kw in SECTOR_KEYWORDS:
            if kw in text:
                counter[kw] += 1
                if title and title not in sources[kw]:
                    sources[kw].append(title)
    # N-gram 补充：2-4字高频词组（捕获词库未覆盖的新词）
    ngram_counter: Counter = Counter()
    for item in news_items:
        text = str(item.get("title", "")) + str(item.get("summary", ""))
        # 只保留中文片段
        for segment in re.findall(r"[\u4e00-\u9fa5]{2,8}", text):
            for n in (2, 3, 4):
                for i in range(len(segment) - n + 1):
                    gram = segment[i : i + n]
                    if gram in STOPWORDS or len(gram) < 2:
                        continue
                    if gram in SECTOR_KEYWORDS:
                        continue  # 已计入
                    ngram_counter[gram] += 1
    # N-gram 只保留高频且不在词库里的（避免噪声）
    for gram, cnt in ngram_counter.most_common(50):
        if cnt >= 3 and gram not in counter:
            counter[gram] = cnt
            # 找一条含该gram的标题
            for item in news_items:
                if gram in str(item.get("title", "")):
                    sources[gram].append(str(item.get("title", "")))
                    break

    ranked = counter.most_common(top_n)
    return [(kw, cnt, sources.get(kw, [])) for kw, cnt in ranked]


def extract_limit_up_themes(rows: list[dict[str, Any]], limit_up_checker) -> list[tuple[str, int, list[str]]]:
    """从涨停股的板块标签统计资金面热点。

    返回 [(theme, limit_up_count, [stock_codes]), ...] 按涨停数降序。
    """
    from .adapters.eastmoney import row_themes

    theme_stocks: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if not limit_up_checker(row):
            continue
        code = str(row.get("f12", ""))
        for theme in row_themes(row):
            if code not in theme_stocks[theme]:
                theme_stocks[theme].append(code)
    ranked = sorted(theme_stocks.items(), key=lambda kv: len(kv[1]), reverse=True)
    return [(theme, len(codes), codes) for theme, codes in ranked[:25]]


def cross_validate_hotspots(
    news_keywords: list[tuple[str, int, list[str]]],
    limit_up_themes: list[tuple[str, int, list[str]]],
    news_threshold: int = 2,
    limit_up_threshold: int = 3,
) -> list[dict[str, Any]]:
    """交叉验证热点：新闻×涨停=强热点；单边=弱热点。

    返回 [{term, type, confidence, news_count, limit_up_count, sources}, ...]
    type: strong(双命中) / news_only(新闻面) / fund_only(资金面)
    confidence: 0-1
    """
    news_map = {kw: cnt for kw, cnt, _ in news_keywords}
    news_sources = {kw: titles for kw, _, titles in news_keywords}
    fund_map = {theme: cnt for theme, cnt, _ in limit_up_themes}
    fund_codes = {theme: codes for theme, _, codes in limit_up_themes}

    all_terms = set(news_map.keys()) | set(fund_map.keys())
    hotspots: list[dict[str, Any]] = []
    for term in all_terms:
        n_cnt = news_map.get(term, 0)
        f_cnt = fund_map.get(term, 0)
        # 子串归并：新闻词与涨停板块名互为子串时合并计数
        if n_cnt == 0:
            # term 只在涨停里，去新闻里找包含 term 或被 term 包含的词
            for nt in news_map:
                if term in nt or nt in term:
                    n_cnt = news_map.get(nt, 0)
                    break
        if f_cnt == 0:
            # term 只在新闻里，去涨停里找包含 term 或被 term 包含的板块
            for ft in fund_map:
                if term in ft or ft in term:
                    f_cnt = fund_map.get(ft, 0)
                    break

        if n_cnt >= news_threshold and f_cnt >= limit_up_threshold:
            htype = "strong"
            confidence = min(1.0, 0.5 + n_cnt * 0.1 + f_cnt * 0.03)
        elif n_cnt >= news_threshold:
            htype = "news_only"
            confidence = min(0.6, n_cnt * 0.15)
        elif f_cnt >= limit_up_threshold:
            htype = "fund_only"
            confidence = min(0.7, 0.3 + f_cnt * 0.04)
        else:
            continue
        hotspots.append({
            "term": term,
            "type": htype,
            "confidence": round(confidence, 2),
            "news_count": n_cnt,
            "limit_up_count": f_cnt,
            "news_sources": news_sources.get(term, [])[:3],
            "limit_up_stocks": fund_codes.get(term, [])[:5],
        })
    # 排序：strong 优先，再按 confidence
    type_order = {"strong": 0, "fund_only": 1, "news_only": 2}
    hotspots.sort(key=lambda h: (type_order[h["type"]], -h["confidence"]))
    return hotspots


def extract_hotspots(
    news_items: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    limit_up_checker,
    top_n: int = 20,
) -> tuple[list[str], list[dict[str, Any]]]:
    """工程化热点提取主入口（纯 Python）。

    返回 (hot_terms, hotspot_details)。
    hot_terms: 用于行情筛选的热点词列表（已归并子串）。
    hotspot_details: 每个热点的来源/置信度详情，写入 scan 报告。
    """
    news_kw = extract_news_keywords(news_items, top_n=30)
    limit_up_themes = extract_limit_up_themes(rows, limit_up_checker)
    hotspots = cross_validate_hotspots(news_kw, limit_up_themes)

    # hot_terms：strong 全要 + fund_only 取前10 + news_only 取前5
    terms: list[str] = []
    for h in hotspots:
        if h["type"] == "strong":
            terms.append(h["term"])
    for h in hotspots:
        if h["type"] == "fund_only" and len(terms) < 15:
            terms.append(h["term"])
    for h in hotspots:
        if h["type"] == "news_only" and len(terms) < 20:
            terms.append(h["term"])
    # 去重保序
    seen = set()
    deduped = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped[:top_n], hotspots[:top_n]
