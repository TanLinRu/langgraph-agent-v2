from pathlib import Path

from langchain_core.tools import tool


@tool
def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read the contents of a file."""
    try:
        p = Path(file_path)
        if not p.exists():
            return f"Error: File not found: {file_path}"
        content = p.read_text(encoding="utf-8")
        lines = content.splitlines()
        selected = lines[offset : offset + limit]
        return "\n".join(selected)
    except Exception as e:
        return f"Error reading file: {e}"


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed."""
    try:
        p = Path(file_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def list_directory(path: str = ".") -> str:
    """List files and directories at the given path."""
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: Directory not found: {path}"
        if not p.is_dir():
            return f"Error: Not a directory: {path}"
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        lines = []
        for entry in entries:
            prefix = "\U0001f4c1 " if entry.is_dir() else "\U0001f4c4 "
            lines.append(f"{prefix}{entry.name}")
        return "\n".join(lines) or "(empty directory)"
    except Exception as e:
        return f"Error listing directory: {e}"
