# 测试约定（2026-11-14 立）

测试代码全部在本目录（`tests/`），与 `src/` 严格分离；跑法：

```bash
npm test          # = node --test tests/（Node 内置运行器，零新增依赖）
```

## 结构

- `unit/` — 纯函数/单模块测试，不起服务、不连库（或只连本地假端点）
  - `crypto-password`：scrypt 哈希/校验（批 1）
  - `gateway-guards`：requireRole/gateApp 包装语义，只用不触库的 principal（批 2/3）
  - `notify-channels`：推送三态，本地假 webhook，不外网（批 5）
- `integration/` — 起真实服务做全链路验证，每个文件一个服务实例
  - `auth-flow`：登录/登出/改密/限速/停用/引导建号（批 1）
  - `rbac-gates`：网关 403 矩阵、应用开关、缺行拒绝（批 2/3）
  - `admin-users`：管理 CRUD 全流程、管理员保护 409、矩阵读写（批 4）
  - `invite-key`：邀请链接生成/消费/一次性、并存登录（批 5）

## 隔离三件套（helpers.mjs 自动处理）

1. **独立 PG 测试库**：`lumencafe_test_<pid>_<slug>`，用前建、用后删（`DROP ... WITH (FORCE)`），永不碰开发库。
2. **独立端口**：每次 `listen 0` 取空闲端口。
3. **独立 DATA_DIR**：chord 数据落在系统临时目录，测后删除；`PUSH_SCHEDULER=off` 不触发定时推送。

## 写新测试的规矩（后续开发同步带测试）

- 新功能随批交付时同步补 `tests/` 用例，放对应目录；纯逻辑进 `unit/`，端到端进 `integration/`。
- 集成测试需要造数据时优先走 API（真实路径），绕不开再用 helpers 的 `sql()` 直插（如构造保护规则的边角场景）。
- 限速/锁定类用例注意内存态是 per-process 的：每个文件起新服务即干净，别跨文件复用用户名。
- 不起外网请求；推送类用本地假端点（参照 notify-channels）。
- 测试跑完必须自清理：helpers 的 `server.stop()` 已带库删除与临时目录清理，新增的全局资源自己回收。
