"""Tests for directory browser (path picker backend)."""
import pytest
from pathlib import Path

from src.agent.file_service import browse_directories, PICKER_SKIP_DIRS


def test_browse_root(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')")
    (tmp_path / "README.md").write_text("hello")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "node_modules").mkdir()
    skip_name = next(iter(PICKER_SKIP_DIRS))
    (tmp_path / skip_name).mkdir()

    tree = browse_directories(tmp_path, max_depth=2, include_files=False)
    assert tree["type"] == "dir"
    assert tree["path"] == str(tmp_path)
    names = [c["name"] for c in tree["children"]]
    assert "src" in names
    assert "node_modules" in names
    # hidden dir excluded
    assert ".hidden" not in names
    # skipped dir excluded
    assert skip_name not in names
    # by default files not included
    assert "README.md" not in names


def test_browse_with_files(tmp_path: Path):
    (tmp_path / "app.py").write_text("x = 1")
    tree = browse_directories(tmp_path, max_depth=1, include_files=True)
    children = tree["children"]
    assert any(c["name"] == "app.py" and c["type"] == "file" for c in children)


def test_browse_depth_zero(tmp_path: Path):
    (tmp_path / "sub").mkdir()
    tree = browse_directories(tmp_path, max_depth=0)
    # depth 0: no children
    assert tree["children"] == []


def test_browse_missing_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        browse_directories(tmp_path / "does-not-exist")


def test_browse_not_a_directory(tmp_path: Path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        browse_directories(f)


def test_browse_permission_error_is_swallowed(tmp_path: Path, monkeypatch):
    """Sub-folders that can't be read should not raise; just return empty children."""
    sub = tmp_path / "locked"
    sub.mkdir()

    def boom(self):
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "iterdir", boom)
    tree = browse_directories(tmp_path, max_depth=1)
    # we may not see "locked" or see it with empty children — either is fine
    # main contract: no exception propagated
    assert tree["path"] == str(tmp_path)
