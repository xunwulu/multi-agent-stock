"""
Skill Loader - Skill 文件加载器

从 skills/ 目录读取 Markdown 格式的 Skill 文件，提取内容作为系统提示词。

Skill 文件格式:
    ---
    name: technical-analyst
    description: ...
    tools: [get_kline, calc_technical]
    ---

    (Markdown 正文，作为系统提示词)

参考: learn-claude-code s05_skill_loading.py
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# skills/ 目录的默认路径（项目根目录下）
SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"


def load_skill(skill_name: str, skills_dir: str | Path | None = None) -> str:
    """
    加载一个 Skill 文件

    Args:
        skill_name: Skill 名称（不含路径和扩展名）
            例如 "technical-analyst" -> 读取 skills/technical-analyst.md
        skills_dir: Skill 文件目录（默认为项目根目录下的 skills/）

    Returns:
        Skill 文件的正文内容（去掉 YAML 前置元数据后的部分）

    Raises:
        FileNotFoundError: Skill 文件不存在
    """
    skills_path = Path(skills_dir) if skills_dir else SKILLS_DIR
    skill_file = skills_path / f"{skill_name}.md"

    if not skill_file.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_file}")

    content = skill_file.read_text(encoding="utf-8")

    # 去掉 YAML 前置元数据（--- ... --- 之间的部分）
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
            logger.info(f"[SkillLoader] Loaded skill: {skill_name} ({len(body)} chars)")
            return body

    logger.info(f"[SkillLoader] Loaded skill: {skill_name} ({len(content)} chars)")
    return content.strip()


def load_skill_meta(skill_name: str, skills_dir: str | Path | None = None) -> dict:
    """
    加载 Skill 文件的 YAML 前置元数据

    Args:
        skill_name: Skill 名称
        skills_dir: Skill 文件目录

    Returns:
        元数据字典（简单解析，不用 PyYAML）
    """
    skills_path = Path(skills_dir) if skills_dir else SKILLS_DIR
    skill_file = skills_path / f"{skill_name}.md"

    if not skill_file.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_file}")

    content = skill_file.read_text(encoding="utf-8")

    meta = {}
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 2:
            # 简单解析 YAML（不引入额外依赖）
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    # 去掉引号
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    meta[key] = value

    return meta


def list_skills(skills_dir: str | Path | None = None) -> list[str]:
    """
    列出所有可用的 Skill

    Returns:
        Skill 名称列表（不含 .md 扩展名）
    """
    skills_path = Path(skills_dir) if skills_dir else SKILLS_DIR

    if not skills_path.exists():
        return []

    return [
        f.stem for f in skills_path.glob("*.md") if not f.name.startswith("_")
    ]
