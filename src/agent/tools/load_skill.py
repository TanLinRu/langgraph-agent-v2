"""load_skill tool — loads full skill content on demand via ConfigManager."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def load_skill(skill_name: str) -> str:
    """Load a skill's content by name.

    Uses ConfigManager to read from skills/<name>.md.
    Returns the full skill content or an error message.
    """
    from pathlib import Path

    from src.agent.config_manager import get_config_manager

    cm = get_config_manager()
    skills_config = cm.get_skills()
    cfg = skills_config.get(skill_name)

    if cfg:
        md_file = cfg.get("file", f"skills/{skill_name}.md")
        md_path = Path(md_file)
    else:
        md_path = Path("skills") / f"{skill_name}.md"

    if md_path.exists():
        try:
            return md_path.read_text(encoding="utf-8").strip()
        except OSError as e:
            return f"Error loading skill '{skill_name}': {e}"

    return f"Skill '{skill_name}' not found."
