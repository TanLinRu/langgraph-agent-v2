"""Planner — 计划辅助函数 (经验管理 + Agent 描述 + History 转换)。

移除旧版本中的 stream() / parse_plan() / _build_prompt()，
计划生成已移至 core.py 的 _supervisor_node_impl()。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.agent.config_manager import get_config_manager

logger = logging.getLogger(__name__)

_EXPERIENCES_FILE = Path("memory/experiences.md")


# ── 经验管理 ────────────────────────────────────────────────────


def load_experiences() -> str:
    """从 memory/experiences.md 加载历史经验。"""
    if not _EXPERIENCES_FILE.exists():
        return ""
    try:
        return _EXPERIENCES_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_experiences(task: str, results: list[dict], review: str) -> None:
    """将任务经验追加到 memory/experiences.md。"""
    _EXPERIENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = (
        f"\n\n## Task: {task}\n"
        f"- Results: {len(results)} agents\n"
        f"- Review: {review[:200]}"
    )
    try:
        with _EXPERIENCES_FILE.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        logger.warning("Failed to save experiences")


# ── Agent 描述构建 ──────────────────────────────────────────────


def build_agent_descriptions() -> str:
    """从 config/agents.json 构建 agent_descriptions 字符串。"""
    cm = get_config_manager()
    agents_config = cm.get_agents()
    lines: list[str] = []
    for agent_id, cfg in agents_config.items():
        if agent_id == "supervisor" or not cfg.get("enabled", True):
            continue
        desc = cfg.get("desc", "")
        if desc:
            lines.append(f"- **{agent_id}**: {desc}")
        else:
            lines.append(f"- **{agent_id}**")
    if not any("direct" in line for line in lines):
        lines.append("- **direct**: Direct reply for simple/single-step tasks")
    return "\n".join(lines)


# ── History 转换 ────────────────────────────────────────────────


def _convert_history(history: list[dict] | None) -> list[dict[str, str]]:
    """将前端格式的对话历史转换为 LLM 接受的格式。"""
    if not history:
        return []
    converted: list[dict[str, str]] = []
    for msg in history:
        role = "user" if msg.get("role") == "human" else "assistant"
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        if not content and not tool_calls:
            continue
        text = content
        if tool_calls:
            calls_text = "; ".join(
                f"{tc['name']}({json.dumps(tc.get('args', {}), ensure_ascii=False)})"
                for tc in tool_calls
            )
            text = (text + "\n") if text else ""
            text += f"\n[Tool calls: {calls_text}]"
        converted.append({"role": role, "content": text})
    return converted
