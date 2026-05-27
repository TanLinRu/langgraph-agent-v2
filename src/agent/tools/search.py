import fnmatch
from pathlib import Path

from langchain_core.tools import tool


@tool
def search_files(pattern: str, path: str = ".", max_results: int = 20) -> str:
    """Search for files matching a glob pattern."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: Path not found: {path}"
        matches = []
        for item in p.rglob("*"):
            if len(matches) >= max_results:
                break
            if fnmatch.fnmatch(item.name, pattern):
                rel = item.relative_to(p)
                prefix = "\U0001f4c1 " if item.is_dir() else "\U0001f4c4 "
                matches.append(f"{prefix}{rel}")
        if not matches:
            return f"No files matching '{pattern}' found in {path}"
        header = f"Found {len(matches)} matches" + (" (truncated)" if len(matches) >= max_results else "") + ":"
        return header + "\n" + "\n".join(matches)
    except Exception as e:
        return f"Error searching files: {e}"
