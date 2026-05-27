"""Tool result truncation — prevents large tool outputs from blowing up context."""

_LIMITS = {
    "execute_code": 2000,
    "read_file": 4000,
    "write_file": 500,
    "list_directory": 2000,
    "search_files": 2000,
}

_DEFAULT_LIMIT = 2000


def truncate_result(tool_name: str, result: str) -> str:
    """Truncate a tool result if it exceeds the limit for that tool type."""
    limit = _LIMITS.get(tool_name, _DEFAULT_LIMIT)
    if len(result) <= limit:
        return result

    if tool_name == "read_file":
        head = result[:limit - 200]
        return f"{head}\n\n... [truncated, {len(result)} chars total]"

    if tool_name == "execute_code":
        lines = result.split("\n")
        truncated = []
        total = 0
        for line in lines:
            if total + len(line) + 1 > limit - 100:
                truncated.append(f"... [truncated, {len(result)} chars total]")
                break
            truncated.append(line)
            total += len(line) + 1
        return "\n".join(truncated)

    head = result[:limit - 100]
    return f"{head}\n\n... [truncated, {len(result)} chars total]"
