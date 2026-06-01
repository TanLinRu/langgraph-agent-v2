from pathlib import Path

from src.agent.tools.execute_code import _contains_dangerous_patterns, execute_code
from src.agent.tools.file_ops import list_directory, read_file, write_file
from src.agent.tools.search import search_files


def test_execute_code_hello():
    result = execute_code.invoke({"code": "print('hello')"})
    assert "hello" in result


def test_execute_code_timeout():
    result = execute_code.invoke({"code": "import time; time.sleep(60)"})
    assert "timed out" in result.lower() or "error" in result.lower()


def test_dangerous_pattern_subshell():
    assert _contains_dangerous_patterns("echo $(whoami)") is True


def test_dangerous_pattern_backtick():
    assert _contains_dangerous_patterns("echo `whoami`") is True


def test_dangerous_pattern_redirect():
    assert _contains_dangerous_patterns("echo test > /etc/passwd") is True


def test_dangerous_pattern_newline():
    assert _contains_dangerous_patterns("echo a\nrm -rf /") is True


def test_dangerous_pattern_safe():
    assert _contains_dangerous_patterns("print('hello world')") is False


def test_dangerous_pattern_math():
    assert _contains_dangerous_patterns("x = $(echo 1)") is True


def test_write_and_read_file(tmp_path):
    fpath = str(tmp_path / "test.txt")
    write_result = write_file.invoke({"file_path": fpath, "content": "hello world"})
    assert "written" in write_result.lower() or "success" in write_result.lower() or fpath in write_result

    read_result = read_file.invoke({"file_path": fpath})
    assert "hello world" in read_result


def test_read_file_offset_limit(tmp_path):
    fpath = str(tmp_path / "test.txt")
    Path(fpath).write_text("\n".join(f"line {i}" for i in range(100)))
    result = read_file.invoke({"file_path": fpath, "offset": 10, "limit": 5})
    assert "line 10" in result


def test_list_directory(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    result = list_directory.invoke({"path": str(tmp_path)})
    assert "a.txt" in result
    assert "b.txt" in result


def test_search_files(tmp_path):
    (tmp_path / "foo.py").write_text("x = 1")
    (tmp_path / "bar.py").write_text("y = 2")
    (tmp_path / "baz.txt").write_text("z = 3")
    result = search_files.invoke({"pattern": "*.py", "path": str(tmp_path)})
    assert "foo.py" in result
    assert "bar.py" in result
    assert "baz.txt" not in result
