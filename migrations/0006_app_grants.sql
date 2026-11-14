-- 批 3 权限矩阵：应用级授权开关（chat / money / papers / admin 各自可设哪些角色可用）
-- 缺行 = 默认拒绝（gateway.mjs 注释约定）；未来新增应用必须在此种子行
CREATE TABLE app_grants (
  app     TEXT NOT NULL CHECK (app IN ('chat','money','papers','admin')),
  role    TEXT NOT NULL CHECK (role IN ('admin','member')),
  allowed BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (app, role)
);

-- 默认种子：admin 全可用；member 可用 chat / money / papers，不可用 admin
INSERT INTO app_grants (app, role, allowed) VALUES
  ('chat','admin',TRUE),('chat','member',TRUE),
  ('money','admin',TRUE),('money','member',TRUE),
  ('papers','admin',TRUE),('papers','member',TRUE),
  ('admin','admin',TRUE),('admin','member',FALSE);
