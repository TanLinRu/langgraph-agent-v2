"""File service — sandboxed file tree and content reading with basic syntax highlighting."""

import re
from pathlib import Path

from src.agent.config import AgentConfig

# Allowed file extensions for preview
ALLOWED_EXTENSIONS = {
    '.py', '.ts', '.js', '.vue', '.html', '.css', '.json', '.toml', '.yaml', '.yml',
    '.md', '.txt', '.cfg', '.ini', '.env', '.sh', '.bat', '.sql', '.xml', '.csv',
}

# Directories to skip in file tree
SKIP_DIRS = {
    'node_modules', '.git', '__pycache__', '.venv', 'venv', 'dist', 'build',
    '.mypy_cache', '.pytest_cache', '.ruff_cache', '.claude',
}

# System / noisy directories to skip in the **directory picker** tree.
# Picking a project should never land inside these. They appear at C:\ root
# and would otherwise dominate the tree.
PICKER_SKIP_DIRS = {
    '$Recycle.Bin', '$WinREAgent', '$SysReset', 'Config.Msi',
    'Documents and Settings', 'PerfLogs', 'Program Files', 'Program Files (x86)',
    'ProgramData', 'Recovery', 'System Volume Information', 'Windows',
    'OneDriveTemp', 'hiberfil.sys', 'pagefile.sys', 'swapfile.sys',
}


def browse_directories(root: Path, max_depth: int = 2, include_files: bool = False) -> dict:
    """Build a nested directory tree suitable for a project picker.

    Returns a JSON-serializable dict:
        { "path": str, "name": str, "type": "dir", "children": [...] }

    - ``max_depth`` controls recursion depth (0 = single node, no children)
    - Hidden directories and ``PICKER_SKIP_DIRS`` are excluded
    - Symlinks are NOT followed (avoids loops)
    - On ``PermissionError`` or ``OSError`` for a subfolder, that subtree is
      replaced with an empty children list rather than raising
    - ``include_files=True`` adds file entries to the tree (size-only summary)
    """
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    def _build(directory: Path, depth: int) -> dict:
        node: dict = {
            "path": str(directory),
            "name": directory.name or str(directory),
            "type": "dir",
            "children": [],
        }
        if depth >= max_depth:
            return node
        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError):
            return node
        try:
            entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            pass
        for entry in entries:
            name = entry.name
            if name.startswith('.'):
                continue
            if name in PICKER_SKIP_DIRS:
                continue
            try:
                if entry.is_dir() and not entry.is_symlink():
                    node["children"].append(_build(entry, depth + 1))
                elif include_files and entry.is_file():
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = 0
                    node["children"].append({
                        "path": str(entry),
                        "name": name,
                        "type": "file",
                        "size": size,
                    })
            except OSError:
                continue
        return node

    return _build(root, 0)


def _get_root(config: AgentConfig | None = None) -> Path:
    """Get the workspace root directory."""
    return Path('.').resolve()


def build_file_tree(root: Path | None = None, max_depth: int = 4) -> dict[str, list[str]]:
    """Build a nested file tree dictionary.

    Returns a dict where keys are directory paths (relative to root)
    and values are lists of file/dir names in that directory.
    """
    if root is None:
        root = _get_root()

    tree: dict[str, list[str]] = {}

    def _scan(directory: Path, depth: int, rel_path: str) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        items: list[str] = []
        for entry in entries:
            if entry.name.startswith('.') and entry.name not in {'.env.example'}:
                continue
            if entry.name in SKIP_DIRS:
                continue
            if entry.is_dir():
                items.append(entry.name + '/')
            elif entry.suffix.lower() in ALLOWED_EXTENSIONS:
                items.append(entry.name)

        tree[rel_path] = items

        # Recurse into directories
        for entry in entries:
            if entry.is_dir() and entry.name not in SKIP_DIRS and not entry.name.startswith('.'):
                child_rel = f"{rel_path}/{entry.name}" if rel_path else entry.name
                _scan(entry, depth + 1, child_rel)

    _scan(root, 0, '')
    return tree


# Simple syntax highlighting patterns
_PATTERNS = [
    # Keywords
    (re.compile(r'\b(import|from|class|def|return|if|else|for|while|try|except|async|await|with|as|raise|in|not|and|or|is|None|True|False|self|const|let|var|function|export|default|interface|type|enum|extends|implements|new|this|super|throw|catch|finally|switch|case|break|continue|do|yield|typeof|instanceof|void|null|undefined)\b'), 'hl-key'),
    # Strings (single and double quoted)
    (re.compile(r'(["\'])(?:(?!\1).)*?\1'), 'hl-str'),
    # Comments (# for Python, // for JS/TS)
    (re.compile(r'(#.*)$'), 'hl-com'),
    (re.compile(r'(//.*)$'), 'hl-com'),
    # Decorators
    (re.compile(r'(@\w+)'), 'hl-dec'),
    # Class names after 'class '
    (re.compile(r'\bclass\s+(\w+)'), 'hl-cls'),
    # Function calls
    (re.compile(r'\b([a-zA-Z_]\w*)\s*\('), 'hl-fn'),
]

# Language mapping by extension
_LANG_MAP = {
    '.py': 'Python',
    '.ts': 'TypeScript',
    '.js': 'JavaScript',
    '.vue': 'Vue',
    '.html': 'HTML',
    '.css': 'CSS',
    '.json': 'JSON',
    '.toml': 'TOML',
    '.yaml': 'YAML',
    '.yml': 'YAML',
    '.md': 'Markdown',
    '.sh': 'Shell',
    '.sql': 'SQL',
}


def _classify_line(line: str) -> str:
    """Apply simple syntax highlighting to a line of code."""
    result = line
    for pattern, cls in _PATTERNS:
        result = pattern.sub(lambda m: f'<span class="{cls}">{m.group(0)}</span>', result)
    return result


def read_file_content(path: str, root: Path | None = None) -> dict:
    """Read a file and return content with line numbers and syntax highlighting.

    Returns: { path, language, lines: [{ num, text, hl }] }
    """
    if root is None:
        root = _get_root()

    # Resolve and validate path (sandbox check)
    abs_path = (root / path).resolve()
    if not str(abs_path).startswith(str(root)):
        raise ValueError("Path traversal detected")

    if not abs_path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    if not abs_path.is_file():
        raise ValueError(f"Not a file: {path}")

    ext = abs_path.suffix.lower()
    language = _LANG_MAP.get(ext, 'Text')

    try:
        content = abs_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        content = abs_path.read_text(encoding='latin-1')

    lines = []
    for i, line in enumerate(content.split('\n'), 1):
        lines.append({
            'num': i,
            'text': _classify_line(line),
            'hl': '',
        })

    return {
        'path': path,
        'language': language,
        'lines': lines,
    }
