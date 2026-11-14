-- §20 P2 头像：users 表加 avatar 列
-- 存 data URL 字符串（data:image/png;base64,...，前端 canvas 裁剪输出 64×64 PNG），
-- 空串 = 未设置（前端显示首字母）。上传/移除接口见 src/api/auth.mjs。
ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT '';