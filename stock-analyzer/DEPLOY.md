# A股量化投研咨询工作台上线说明

这个网站不是纯静态页面，前端会调用 `/api/analyze` 生成股票研究报告。因此上线时需要部署为 Python Web Service，而不是只上传 HTML。

## Render 部署

1. 将 `stock-analyzer` 目录推送到 GitHub 仓库。
2. 在 Render 新建 Web Service，Root Directory 选择 `stock-analyzer`。
3. Build Command 使用：

```bash
pip install -r requirements.txt
```

4. Start Command 使用：

```bash
python web_app.py --host 0.0.0.0
```

5. Health Check Path 填：

```text
/healthz
```

Render 会自动提供 `PORT` 环境变量，应用会读取该端口。

## Docker 部署

在 `stock-analyzer` 目录执行：

```bash
docker build -t stock-quant-research .
docker run --rm -p 8765:8765 -e PORT=8765 stock-quant-research
```

打开：

```text
http://127.0.0.1:8765/
```

## 上线注意

- 线上服务需要能访问外部行情源，否则分析接口会返回数据源错误。
- 若要启用高质量日频数据源，在部署平台环境变量中配置 `TUSHARE_TOKEN` 或 `TUSHARE_PRO_TOKEN`。配置后网页的“专业优先”模式会先走 Tushare Pro，再回退腾讯财经 / 东方财富。
- 若数据供应商支持主动推送，在部署平台配置 `DATA_WEBHOOK_SECRET`，然后把推送地址提供给供应商：

```text
https://你的域名/api/webhooks/market-data
```

推送请求需带 Header：

```text
X-Data-Secret: 你的 DATA_WEBHOOK_SECRET
```

推送 JSON 示例：

```json
{
  "provider": "VendorPush",
  "stock_code": "600519",
  "stock_name": "贵州茅台",
  "bars": [
    {
      "trade_date": "20260605",
      "open": 1270.0,
      "high": 1280.0,
      "low": 1260.0,
      "close": 1272.86,
      "vol": 1234567
    }
  ]
}
```

- 若数据源不支持 webhook 推送，可以配置 `REFRESH_SECRET`，用平台 Cron 每天收盘后触发自动刷新：

```bash
curl -X POST "https://你的域名/api/refresh?secret=你的 REFRESH_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"stocks":["600519","000001","300750"],"days":720,"source":"pull"}'
```

- 未配置推送密钥时，网页会明确显示“推送未配置”；未配置专业数据 token 时，会明确显示“Tushare 未配置”，不会把免费兜底源包装成专业源。
- 本系统用于量化研究、商业咨询展示和辅助决策，不构成投资建议或自动交易指令。
- 如果未来要商用，建议增加访问控制、请求限流、日志脱敏、缓存策略和更正式的免责声明弹窗。
