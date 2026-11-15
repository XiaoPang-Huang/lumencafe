-- 0010：模型排序（第一位=默认模型，学 WorkBuddy）+ 图片输入能力标记
BEGIN;
ALTER TABLE models ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 0;
ALTER TABLE models ADD COLUMN IF NOT EXISTS supports_images BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS models_order_idx ON models (display_order, id);
COMMIT;
