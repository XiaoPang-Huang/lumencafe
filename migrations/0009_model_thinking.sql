-- 思考强度（2026-11-15 拍板：学 WorkBuddy 模型配置——推理模式 + 默认思考强度 + 支持档位）
-- thinking：模型默认思考强度（NULL=推理关闭）；thinking_levels：支持的档位 CSV（对话内可调范围）
-- pi ThinkingLevel 值域：minimal/low/medium/high/xhigh/max

ALTER TABLE models ADD COLUMN thinking TEXT
  CHECK (thinking IN ('minimal','low','medium','high','xhigh','max'));
ALTER TABLE models ADD COLUMN thinking_levels TEXT NOT NULL DEFAULT 'low,medium,high,xhigh,max';
