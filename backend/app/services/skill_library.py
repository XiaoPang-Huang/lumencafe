"""Skill 文件夹库（业界 Agent Skills 开放标准落地）。

设计对标 Anthropic Agent Skills 开放标准：skill = 一个文件夹 + SKILL.md
（YAML frontmatter：`name` / `description` / `source` / `version` + 正文指令）
+ 可选 scripts/ references/ assets/。Claude Code 用 `~/.claude/skills/`，
WorkBuddy 用 `~/.workbuddy/skills/`，本项目统一用项目根 `skills/`。

- 库目录解析优先级：环境变量 `SKILL_LIBRARY_DIR` > `settings.skill_library_dir`
  > 本地开发默认 `<项目根>/skills`（backend/app/services → parents[3]）。
  docker-compose 给 api 注入 `SKILL_LIBRARY_DIR=/app/skills` 并挂载 `./skills`；
- 文件夹是真相源：已安装 skill 的指令正文只从 `skills/<slug>/SKILL.md` 读取，
  DB（user_skills）仅存用户安装关系（索引/开关/顺序）；
- frontmatter 解析为手写轻量实现（零新增 pip 依赖），只取
  name/description/source/version 四键 + 正文分界；
- 手工放入 `skills/` 的合法包（有 SKILL.md、source 非 `skillhub:*`）视为本地 skill，
  自动出现在管理列表（来源=本地，只读）。「扫描注册」（把本地包登记进 DB 以获得
  独立开关）为预留扩展点，本期不实施。

零新增 DB 迁移：以文件夹为真相源，user_skills 表结构不变。
"""
import os
import re
from pathlib import Path
from typing import NamedTuple

from app.config import settings
from app.logging_conf import get_logger

logger = get_logger("skill")

# SKILL.md frontmatter 只解析这四键（其余键忽略，保持向前兼容）
FRONTMATTER_KEYS = ("name", "description", "source", "version")

# SkillHub 安装来源前缀：source: skillhub:<skillhub_id>
SOURCE_SKILLHUB_PREFIX = "skillhub:"

# 本地 skill 的来源前缀（手工放入 skills/ 的包；扫描注册预留）
SOURCE_LOCAL_PREFIX = "local:"

# slug 清洗：小写字母/数字/连字符（与目录名安全字符集一致）
_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_SLUG_DASHES = re.compile(r"-{2,}")


class LibraryEntry(NamedTuple):
    """库中一个 skill 包（skills/<slug>/ 下的合法 SKILL.md）。"""

    slug: str
    name: str
    description: str
    source: str  # skillhub:<id> / local:<slug> / ""（无 source 键按本地处理）
    version: str
    body: str  # 正文指令（frontmatter 之后，strip 后）
    path: Path  # 绝对路径 skills/<slug>/


def sanitize_slug(raw: str) -> str:
    """清洗为合法目录名 slug：小写、非 [a-z0-9-] 折叠为连字符、去首尾连字符。

    用于 provider 包 id → 目录名；清洗结果为空说明入参非法，调用方需 400。
    """
    slug = _SLUG_RE.sub("-", (raw or "").lower())
    slug = _SLUG_DASHES.sub("-", slug).strip("-")
    return slug[:64]


def library_dir() -> Path:
    """解析技能库根目录（每次调用时读环境，便于测试用临时目录覆盖）。"""
    raw = os.environ.get("SKILL_LIBRARY_DIR", "").strip() or settings.skill_library_dir.strip()
    if raw:
        path = Path(raw)
        # 相对路径按当前工作目录解析（本地开发 ./skills = 启动目录下的 skills/）
        return path if path.is_absolute() else (Path.cwd() / path).resolve()
    # 默认：backend/app/services/skill_library.py → parents[3] = 项目根
    return Path(__file__).resolve().parents[3] / "skills"


def ensure_library() -> Path:
    """确保库目录存在（首次安装/扫描时自动创建），返回目录路径。"""
    root = library_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def parse_skill_md(text: str) -> dict[str, str]:
    """手写极简 frontmatter 解析：只取四键 + 正文分界（零新增 pip 依赖）。

    支持 LF/CRLF；frontmatter 必须以 `---` 行起始，以 `---` 行结束；
    键行形如 `name: xxx`（值去除首尾空白与成对引号）；无 frontmatter 时
    四键为空串、正文为全文。
    """
    meta = {key: "" for key in FRONTMATTER_KEYS}
    body = text or ""
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end != -1:
            for line in lines[1:end]:
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip()
                if key in meta:
                    value = value.strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                        value = value[1:-1]
                    meta[key] = value
            body = "\n".join(lines[end + 1 :]).strip()
    return {**meta, "body": body}


def render_skill_md(slug: str, description: str, source: str, version: str, body: str) -> str:
    """按开放标准渲染 SKILL.md 全文（安装时落盘）。"""
    return (
        "---\n"
        f"name: {slug}\n"
        f"description: {description}\n"
        f"source: {source}\n"
        f"version: {version}\n"
        "---\n\n"
        f"{body.strip()}\n"
    )


def _read_entry(skill_dir: Path) -> LibraryEntry | None:
    """读取 skills/<slug>/SKILL.md；缺失/解析无正文视为非法包（跳过）。"""
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return None
    try:
        parsed = parse_skill_md(md.read_text(encoding="utf-8"))
    except OSError:
        return None
    body = parsed["body"]
    if not body:
        return None  # 只有 frontmatter 没有指令正文：非法包，不注册、不报错
    source = parsed["source"].strip()
    if not source:
        source = f"{SOURCE_LOCAL_PREFIX}{skill_dir.name}"  # 无 source 键按本地包处理
    return LibraryEntry(
        slug=skill_dir.name,
        name=parsed["name"].strip() or skill_dir.name,
        description=parsed["description"].strip(),
        source=source,
        version=parsed["version"].strip(),
        body=body,
        path=skill_dir,
    )


def scan_library() -> list[LibraryEntry]:
    """扫描整个库目录，返回全部合法 skill 包（SkillHub 安装包 + 本地包）。"""
    root = library_dir()
    if not root.is_dir():
        return []
    entries: list[LibraryEntry] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            entry = _read_entry(child)
            if entry is not None:
                entries.append(entry)
    return entries


def index_by_source() -> dict[str, LibraryEntry]:
    """source 值 → 库条目 索引（skillhub:<id> / local:<slug>）。"""
    return {entry.source: entry for entry in scan_library()}


def find_by_skillhub_id(skillhub_id: str) -> LibraryEntry | None:
    """按 SkillHub 平台 id 查已落盘的 skill 包。"""
    return index_by_source().get(f"{SOURCE_SKILLHUB_PREFIX}{skillhub_id}")


def install_to_library(slug: str, skill_md: str) -> Path:
    """把 SKILL.md 写入 skills/<slug>/（已存在则 FileExistsError，调用方转 409）。"""
    root = ensure_library()
    skill_dir = root / slug
    if skill_dir.exists():
        raise FileExistsError(slug)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    logger.info("skill library write: %s", skill_dir)
    return skill_dir


def remove_from_library(entry: LibraryEntry) -> None:
    """删除 skills/<slug>/ 整个目录（卸载 SkillHub 安装包时用）。

    安全护栏：只删除解析后仍位于库根目录内的直接子目录，防路径穿越误删。
    本地包不经过此函数（UI 只读，不允许卸载）。
    """
    root = library_dir().resolve()
    target = entry.path.resolve()
    if target.parent != root or not target.is_dir():
        logger.warning("skill library refuse remove: %s", target)
        return
    import shutil

    shutil.rmtree(target, ignore_errors=True)
    logger.info("skill library remove: %s", target)
