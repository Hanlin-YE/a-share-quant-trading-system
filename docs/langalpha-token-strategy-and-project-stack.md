# 调研报告：LangAlpha token 节省策略 & 当前项目开源构成

> 调研日期：2026-06-30
> 仓库：https://github.com/ginlix-ai/LangAlpha

---

## 一、LangAlpha：金融数据在 Python 工程化以节省 token 的代码实现

### 核心结论

LangAlpha 用 **PTC (Programmatic Tool Calling) 模式**实现"数据在 Python 端工程化、不喂给 LLM"。`CLAUDE.md` 原文明确写到：

> "The core differentiator: the LLM doesn't call MCP tools directly. Instead, it writes Python code via `execute_code` that imports generated wrapper modules and calls MCP-backed functions in the Daytona sandbox. This enables data manipulation, charting, and multi-step analysis in a single code execution."

即：LLM 只负责写代码和分析逻辑，原始金融数据从不进入 LLM 上下文，只有处理后的精简结果回传。

### 关键实现组件

| 组件 | 位置 | 作用 |
|------|------|------|
| `execute_code` 工具 | `src/ptc_agent/` | LLM 写 Python，在 Daytona 沙箱执行，每次 fresh `code_run` interpreter |
| `ToolFunctionGenerator` / `generate_mcp_client_code()` | `src/ptc_agent/` | 把 MCP 工具生成为 Python wrapper 模块上传到沙箱，沙箱内直接 import 调用 |
| `data_client/` | `src/data_client/{fmp,ginlix_data}` | 金融数据协议抽象层：FMPClient（~70 方法）、GinlixDataClient，在 Python 端做 `normalize_symbol`、字段对齐、`_format_sector_change_pct`、UTC 时间归一 |
| provenance 中间件 | `src/server/` | `SNIPPET_MAX_CHARS` 截断传给 LLM 的片段；`provenance_result_bodies` 表存完整结果体（≤64KiB inline，更大 spill 到对象存储），**不经过 SSE 流** |
| `downsampleBars` | `web/` + `src/` | K 线降采样 + bar cap，避免传原始 OHLCV |
| `ChartSelectionContext` | `src/` | 用户选区传结构化 region/price bounds + 类型化 bars，而非原始图表数据 |
| memo store | `src/ptc_agent/agent/memo/` | 预计算结果缓存，agent 可存处理后数据，后续直接引用 |
| compaction / DeltaChannel | `src/config/` | 每线程准入门控、`/compact` `/offload`、LangGraph channel delta 写入（O(1)/step），压缩上下文 |
| `conversation_usages` | `src/server/` | 持久化 token 计量，作为 `langalpha.llm.tokens` 指标权威来源 |

### 数据流

```
LLM 写 Python 代码
   → execute_code → Daytona 沙箱
       → import 生成的 MCP wrapper
       → 调 FMP/GinlixData/SEC/market data
       → pandas/numpy: normalize / aggregate / feature eng
       → downsampleBars / SNIPPET_MAX_CHARS 截断
       → memo/cache 复用预计算结果
   ← 只回传精简结果 + 图表（少量 token）
```

关键设计原话：**"The body is written live from the middleware, so the SSE stream stays lean."** —— 完整数据体不入 SSE（传 LLM 的通道），保持精简。

### 可借鉴到本项目的点

本项目当前是把新闻数据直接拼进 prompt 喂给 DeepSeek（`analyze_news_with_deepseek` 里 `compact_items` 取前 80 条 + JSON 序列化进 prompt，`max_tokens=1800`）。可参考 LangAlpha 思路：
1. 在 Python 端先用 pandas 做去重/聚类/关键词提取，只把摘要喂 LLM
2. 对行情数据先降采样/聚合再决定是否进 prompt
3. 把可复用的中间结果落盘缓存，避免重复处理

---

## 二、当前项目的开源构成

盘点结论：**本项目不建立在任何大型开源框架之上**，是一组自包含 Python 脚本 + 科学计算栈 + 原生 HTTP。与 LangAlpha 的重型框架栈（LangGraph / deepagents / FastAPI / React / psycopg3 / Redis / Supabase）截然不同。

### 子项目清单

| 子项目 | 性质 | 主要依赖 |
|--------|------|----------|
| `stock-analyzer/` | 量化分析主引擎 | pandas, numpy, requests, openpyxl |
| `Shenzhen intern trail/` | A股短线题材扫描管道 | 纯 stdlib（urllib 调东方财富/新闻/DeepSeek） |
| `stock-research-lab/` | 研究状态管理 | 纯 stdlib |
| `trading-journal/` | 交易日志/账本（CSV/JSON/Excel） | 数据文件为主 |
| `tools/` | 账本/工作簿工具 | Python(openpyxl) + 1 个 Node 脚本 |

### 实际使用的第三方开源库（Python）

| 库 | 用途 | 出现位置 |
|----|------|----------|
| `pandas` | 数据处理（DataFrame） | analyze.py, backtest.py, theme_scan.py, 多处 tests |
| `numpy` | 数值计算 | analyze.py, tests |
| `requests` | HTTP 请求 | analyze.py |
| `openpyxl` | Excel 读写 | tools/sync_portfolio_workbook.py, extract_existing_workbook_history.py, tests |

### 声明但未实际 import 的库（requirements.txt）

`pandas-datareader`、`scikit-learn`、`scipy` —— 在 requirements.txt 中声明，但代码中未发现直接 import，可能未使用或仅动态使用。

### LLM 集成方式

- DeepSeek API：`Shenzhen intern trail/src/adapters/deepseek.py` 用 **stdlib `urllib`** 原生 HTTP 调用，未使用 openai SDK 或任何 LLM 框架。
- 这与 LangAlpha 用 `deepagents` + LangGraph 中间件栈形成鲜明对比。

### 前端

- `stock-analyzer/web/`：**纯 vanilla JS**（app.js 用 `document.querySelector`），无框架、无构建工具、无 package.json、无 node_modules。

### Node 工具

- `tools/inspect_portfolio_workbook.mjs`：引用 `@oai/artifact-tool`（宿主环境提供的内部工具，非公开开源包，项目内无 package.json/node_modules）。

### 总结对比

| 维度 | 本项目 | LangAlpha |
|------|--------|-----------|
| 框架 | 无 | LangGraph + deepagents + FastAPI |
| 前端 | vanilla JS | React 19 + Vite + Tailwind + shadcn/ui |
| LLM 调用 | urllib 原生 HTTP | LLM wrapper + token 计量 + 模型 manifest |
| 数据处理 | pandas/numpy 脚本 | 沙箱 Python + MCP 数据工具链 |
| 存储 | CSV/JSON/Excel 文件 | Postgres + Redis + 对象存储 |
| 依赖体积 | 极小（4 个核心第三方库） | 重型 |
