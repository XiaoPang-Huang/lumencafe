# 流光咖啡馆（LumenCafe）

自部署的两人 AI 应用工作台。打磨成熟后计划 MIT 开源。

> **协作硬性规定**：所有界面设计必须先搜索并参考业界成功案例（火山方舟控制台、LobeChat、Supabase、midday 等），禁止凭感觉自行设计。详见 [AGENTS.md](AGENTS.md)。

## 当前状态：架构重构中

项目正从旧栈（Python：FastAPI + PostgreSQL + Hatchet + pi-runner）重构为新栈（Node：pi / chord）。

- **旧栈代码已于 2026-11-11 删除**（备份在 `E:/backups/`，git 历史亦可恢复）。
- 新栈的产品契约见 **[docs/白皮书-v3.md](docs/白皮书-v3.md)**，架构推演过程见 [docs/pi-workbench-architecture.html](docs/pi-workbench-architecture.html)。
- 新栈代码尚未落地，将按白皮书 §13 的打磨顺序逐步实现。

## 新架构一句话

一台 2C4G 服务器，装一个 Node 主程序，里面跑三个应用（对话、记账、论文），共用一套登录（chord），大模型全部调云端（pi-ai）。框架状态存 SQLite，业务数据和向量存 PostgreSQL + pgvector。详见白皮书。

## 目录结构

```
AGENTS.md    设计强制规则 + 工程约定（最高优先级）
docs/        白皮书 v3（新架构契约）、架构讨论稿、团队协作规范、项目地图、论文数据源目录
prototype/   前端交互原型（纯 HTML/CSS/JS，v2 见 prototype/v2/，本地起任意静态服务即可预览）
skills/      Skill 文件夹库（运行期数据，Agent Skills 开放标准）
```

> 新栈的服务端代码目录尚未创建，落地时以白皮书为准。

## 本地预览原型

```bash
cd prototype
python -m http.server 4311
# 浏览器打开 http://localhost:4311/v2/
```

找不到要改的文件？先看 [docs/项目地图-v1.md](docs/项目地图-v1.md)（或浏览器打开 `docs/项目地图.html`，可搜索、点选复制路径）。
