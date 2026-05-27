"""Skill management — loads skill definitions from skills/ directory."""

from pathlib import Path

_SKILLS_DIR = Path("skills")


class Skill:
    def __init__(self, name: str, description: str, content: str) -> None:
        self.name = name
        self.description = description
        self.content = content


def load_skills() -> list[Skill]:
    """Scan skills/ directory for .md files and load them as skills."""
    if not _SKILLS_DIR.exists():
        return []

    skills = []
    for path in sorted(_SKILLS_DIR.glob("*.md")):
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

        skills.append(Skill(
            name=path.stem,
            description=description,
            content=text,
        ))
    return skills


def get_skills_prompt() -> str:
    """Generate skills section for system prompt injection."""
    skills = load_skills()
    if not skills:
        return ""

    parts = ["[Available Skills]"]
    for skill in skills:
        parts.append(f"\n## {skill.name}\n{skill.content}")
    return "\n".join(parts)


def list_skills() -> list[dict]:
    """Return skill metadata for API responses."""
    return [{"name": s.name, "description": s.description} for s in load_skills()]
