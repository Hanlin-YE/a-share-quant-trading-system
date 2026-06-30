# Shenzhen intern trail 使用说明

这是一个本地运行的 A 股短线题材筛选工具。它会读取新闻/热搜和行情数据，用 DeepSeek 做新闻热点分析，再按四层规则输出研究用候选结果。

结果仅供研究，不构成投资建议，不会自动下单。

## 最简单用法

### macOS

1. 双击 `scripts/setup.command`
2. 双击 `scripts/run_once.command` 跑一次
3. 查看 `runs/latest.html`
4. 如果要持续运行，双击 `scripts/start.command`
5. 关闭终端窗口即可停止持续运行

### Windows

1. 双击 `scripts/setup.bat`
2. 双击 `scripts/run_once.bat` 跑一次
3. 查看 `runs/latest.html`
4. 如果要持续运行，双击 `scripts/start.bat`
5. 关闭命令行窗口即可停止持续运行

## 配置说明

项目根目录的 `.env` 里保存运行配置。当前交付包可以保留 `.env`，里面包含限额 DeepSeek key。请只发给可信任的人，不要公开传播。

如果需要换 key，编辑 `.env`：

```env
DEEPSEEK_API_KEY=你的key
```

## 运行状态

`runs/latest.html` 会显示：

- `PASS`：真实数据扫描完成，并可能有候选
- `NO_SIGNAL`：真实数据扫描完成，但没有符合条件的候选
- `BLOCKED`：关键配置、DeepSeek、新闻源或行情源失败，系统不会输出买入计划

## 自动扫描

`start.command` / `start.bat` 会每 30 分钟扫描一次。

每次扫描会写入：

```text
runs/YYYY-MM-DD/HHMM.json
runs/latest.json
runs/latest.html
```

## 金十和 Wind 配置

金十：

- 有合规 API：设置 `ENABLE_JIN10=true`、`JIN10_MODE=api`、`JIN10_API_URL=...`、可选 `JIN10_API_KEY=...`
- 无 API 但允许公开页降级：设置 `JIN10_MODE=public`，系统会标记为 `degraded`，不能当作授权 API 等价物

Wind：

- 最快可落地：从 Wind 导出新闻/快讯 CSV，设置 `ENABLE_WIND=true`、`WIND_MODE=csv`、`WIND_CSV_PATH=/path/to/wind_news.csv`
- CSV 字段建议包含：`title,summary,published_at`
- 有 Wind 终端/Python 环境：设置 `ENABLE_WIND=true`、`WIND_MODE=windpy`。当前代码会检查 WindPy 是否可用，但具体新闻函数还需按实际 Wind 权限配置。

## 打包

macOS 双击或运行：

```bash
scripts/package.command
```

Windows 双击：

```text
scripts/package.bat
```

打包会保留 `.env`，但排除 `runs/`、缓存和日志。请确认 `.env` 中的 key 是可以分享给对方的限额 key。

## 规则摘要

1. 第一层：新闻/热搜/官媒/Wind/金十信息进入 DeepSeek，提取热点题材和个股池
2. 第二层：主力净流入、换手有效，剔除 ST、停牌、重大风险等
3. 第三层：成交量爆量或量能 4/11/117 多头排列，大单占比高，同时股价 MA5 > MA10 > MA20，连续下跌 4 天自动否决
4. 第四层：同板块已有涨停锚点，优先买龙二；龙二快速封板买不到则切龙三；买点为 A 类突破、B 类突破或 7%-8% 打板挂单

