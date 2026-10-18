# n8n 文献每日抓取工作流

## 导入与接入（5 分钟）

1. n8n 界面 → **Workflows → Import from File** → 选择 `papers-crawl.json`。
2. 「触发抓取」节点的 Header `X-Internal-Token` 值为 `={{$env.LUMEN_INTERNAL_TOKEN}}`：
   - 服务器部署（docker compose 起 n8n）：无需手改，compose 已把 `.env` 的 `LUMEN_INTERNAL_TOKEN` 注入 n8n 容器；
   - 其他方式跑的 n8n：把该环境变量配进 n8n，或直接把值填进节点（建议存 n8n Credentials 而非明文）。
   n8n 与 api 同网段，地址 `http://api:8000` 无需改动。
3. **Save** 并右上角 **Activate**。

## 行为

- 每天 07:00 触发 `POST /internal/jobs/papers-crawl`，返回 `{added: n}`（本轮新入库数）。
- 后端同日幂等：重复触发/重启都只会抓一轮（Q11 双保险）。
- 抓取范围 = 所有用户的订阅关键词（「我的 → 应用设置 → 文献」）并集；
  用户未配置时回落 `.env` 的 `LUMEN_PAPERS_DEFAULT_KEYWORDS`（逗号分隔）。
- 遵守 NCBI 限速（≤3 req/s、efetch 分批 ≤100），中译走模型管理页的默认路由
  （单轮 ≤20 篇、篇间 ≥1s）。

## 手动补抓

当天想再抓一轮（比如刚改了订阅关键词）：重启 api 容器清空进程内日期标记后再调接口；
或直接 `docker compose restart api` 后 curl：

```bash
curl -X POST http://localhost:8000/internal/jobs/papers-crawl \
  -H "X-Internal-Token: <LUMEN_INTERNAL_TOKEN>"
```
