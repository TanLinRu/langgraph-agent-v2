"""Skill management — loads skill definitions from config/skills.json + skills/*.md files."""

from pathlib import Path

_SKILLS_DIR = Path("skills")


class Skill:
    def __init__(self, name: str, description: str, content: str, agents: list[str] = None, enabled: bool = True) -> None:
        self.name = name
        self.description = description
        self.content = content
        self.agents = agents or []
        self.enabled = enabled


def load_skills() -> list[Skill]:
    """Load skills from config/skills.json metadata + skills/*.md content."""
    from src.agent.config_manager import get_config_manager

    cm = get_config_manager()
    skills_config = cm.get_skills()

    skills = []
    for name, cfg in skills_config.items():
        if not cfg.get("enabled", True):
            continue

        md_file = cfg.get("file", f"skills/{name}.md")
        md_path = Path(md_file)
        if not md_path.exists():
            md_path = _SKILLS_DIR / f"{name}.md"

        content = ""
        if md_path.exists():
            try:
                content = md_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass

        description = cfg.get("desc", "")
        if not description and content:
            lines = content.split("\n")
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped
                    break
                if stripped.startswith("# "):
                    description = stripped[2:]
                    break

        skills.append(Skill(
            name=name,
            description=description,
            content=content,
            agents=cfg.get("agents", []),
            enabled=True,
        ))

    if _SKILLS_DIR.exists():
        existing_names = {s.name for s in skills}
        for path in sorted(_SKILLS_DIR.glob("*.md")):
            if path.stem in existing_names:
                continue
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            lines = text.split("\n")
            description = ""
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped
                    break
                if stripped.startswith("# "):
                    description = stripped[2:]
                    break
            skills.append(Skill(name=path.stem, description=description, content=text))

    return skills


def get_skills_prompt(agent_id: str = None) -> str:
    """Generate skills section for system prompt injection.

    Returns a [Available Skills] summary list (not full content).
    The LLM can use the load_skill tool to load full content on demand.
    """
    skills = load_skills()
    if not skills:
        return ""

    if agent_id:
        skills = [s for s in skills if not s.agents or agent_id in s.agents]

    if not skills:
        return ""

    parts = ["[Available Skills]"]
    for skill in skills:
        parts.append(f"- {skill.name}: {skill.description}")
    parts.append("\nUse the `load_skill` tool to load full skill content when needed.")
    return "\n".join(parts)


def list_skills() -> list[dict]:
    """Return skill metadata for API responses."""
    return [
        {
            "name": s.name,
            "description": s.description,
            "agents": s.agents,
            "enabled": s.enabled,
        }
        for s in load_skills()
    ]
