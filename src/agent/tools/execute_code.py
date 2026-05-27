import re
import subprocess
import sys
import tempfile
from pathlib import Path

from langchain_core.tools import tool

DANGEROUS_SHELL_PATTERNS = (
    "$(",  # Command substitution
    "`",  # Backtick command substitution
    "$'",  # ANSI-C quoting
    "\n",  # Newline (command injection)
    "\r",  # Carriage return
    "\t",  # Tab
    "<(",  # Process substitution (input)
    ">(",  # Process substitution (output)
    "<<<",  # Here-string
    "<<",  # Here-doc
    ">>",  # Append redirect
    ">",  # Output redirect
    "<",  # Input redirect
    "${",  # Variable expansion with braces
)


def _contains_dangerous_patterns(code: str) -> bool:
    if any(pattern in code for pattern in DANGEROUS_SHELL_PATTERNS):
        return True
    if re.search(r"\$[A-Za-z_]", code):
        return True
    return bool(re.search(r"(?<![&])&(?![&])", code))


@tool
def execute_code(code: str, language: str = "python") -> str:
    """Execute code and return the output. Supports Python."""
    if language != "python":
        return f"Unsupported language: {language}"

    if _contains_dangerous_patterns(code):
        return "Error: Code contains potentially dangerous shell patterns and was rejected"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (30s limit)"
    except Exception as e:
        return f"Error: {e}"
    finally:
        Path(tmp_path).unlink(missing_ok=True)
