# 股票量化交易系统

一套面向中国 A 股的量化研究系统：从多源行情适配、四引擎量化诊断、题材短线筛选，到日内五阶段流水线、纸面账户与策略治理，形成可复盘的研究闭环。

> ⚠️ 本系统仅供量化研究与训练，**不构成投资建议，不会自动下单**。账户为纸面训练账户（paper account），所有"盈亏"均为模拟。

## 路演

一键查看项目路演（16 页，键盘 ← → 翻页，F 全屏）：

```bash
open docs/roadshow.html
```

## 子系统

| 子系统 | 职责 |
|--------|------|
| `stock-analyzer/` | 量化主引擎。四引擎框架 + ML 概率集成 + 多源行情适配 + 组合回测 + 策略版本注册表 |
| `Shenzhen intern trail/` | A 股短线题材筛选管道。新闻/热搜 → DeepSeek 题材提取 → 四层规则 → 买点计划 |
| `stock-research-lab/` | 研究生命周期。观察池、买入 thesis、卖出条件、复查日期 |
| `trading-journal/` | 纸面账户与交易日志。唯一组合总表 + 五阶段流水线记录 + 复盘文档 |
| `tools/` | 账本工具链。Excel 工作簿同步、历史回填、组合账本重建 |

## 核心能力

- **多源行情适配**：推送缓存 / Tushare / 腾讯 / 东方财富 / Stooq，复权与缓存健康门禁
- **四引擎框架**：题材轮动 + 量价技术 + 投研证据链 + 回测风控
- **ML 集成**：决策树 / 随机森林 / ExtraTrees / 逻辑回归 / SVM / KNN / MLP，TimeSeriesSplit + gap 防泄漏
- **日内五阶段流水线**：preopen → open → midday → afternoon → close，dry-run 默认，每阶段 JSON 留痕
- **策略治理**：训练/验证/测试三段 + walk-forward 滚动复核 + 晋级门禁，失败桶反馈闭环
- **纸面账户**：成本模型含佣金/印花税/过户/滑点，风控阈值单日亏损 1% / 回撤 5% 预警 / 10% 停止

## 快速开始

```bash
# 数据链路健康检查
python3 stock-analyzer/scripts/analyze.py --health-check

# 单票量化诊断
python3 stock-analyzer/scripts/analyze.py --stock 600519 --days 360

# 组合回测（显式计入交易成本）
python3 stock-analyzer/scripts/backtest.py \
  --stocks 000001,000858,600000,300750,600519 --days 720 \
  --fee-bps 3 --min-commission 5 --tax-bps 5 --slippage-bps 5

# 日内五阶段流水线（dry-run）
python3 stock-analyzer/scripts/daily_pipeline.py --stage preopen \
  --stocks 600519,300750 --days 260 --source premium --record
```

详细参数与工作流见各子系统 README。

## 技术栈

极简依赖，无重型框架：

- **pandas / numpy** — 数据处理与数值计算
- **requests** — 多源行情 HTTP 适配
- **openpyxl** — Excel 审计视图同步
- **stdlib urllib** — DeepSeek / 行情源原生 HTTP（无 LLM SDK）
- **vanilla JS** — 前端无框架无构建

## 项目结构

```
.
├── stock-analyzer/          # 量化主引擎
├── Shenzhen intern trail/   # 短线题材筛选管道
├── stock-research-lab/      # 研究生命周期
├── trading-journal/         # 纸面账户与交易日志
├── tools/                   # 账本工具链
└── docs/                    # 文档与路演
    └── roadshow.html        # 项目路演稿
```

## 风险提示

本系统输出仅供量化研究和辅助决策，不构成投资建议。A 股存在涨跌停、停牌、流动性、政策冲击和数据源稳定性问题。进入实盘前必须补齐全市场回测、交易成本建模、样本外验证、组合级风控、券商接口、撤单逻辑和人工复核。所有自动决策默认 dry-run，`--execute` 才写入纸面账本；即使策略通过晋级门禁，也只能进入纸面交易观察，**不允许自动真实下单**。
