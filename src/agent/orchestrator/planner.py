"""Planner — Pydantic models + plan helpers for the v2 StateGraph.

Contains:
- Pydantic models: Step, Plan, AgentResult, AntiPattern, GraphState
- Legacy helpers: build_agent_descriptions, _convert_history, load_experiences, save_experiences
- New helpers: load_constraints, save_anti_pattern, get_constraints
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.agent.config_manager import get_config_manager

logger = logging.getLogger(__name__)

_EXPERIENCES_FILE = Path("memory/experiences.md")


# ── Pydantic Models (v2 Graph) ──────────────────────────────────


class Step(BaseModel):
    agent: str
    task: str
    depends_on: list[str] = []
    context: str = ""


class Plan(BaseModel):
    steps: list[Step]
    reasoning: str = ""
    auto_approve: bool = False


class AgentResult(BaseModel):
    agent: str
    task: str
    result: str
    error: str = ""
    elapsed_ms: int = 0


class AntiPattern(BaseModel):
    label: str
    task: str
    agent: str
    what_happened: str
    suggestion: str
    severity: str = "medium"


class GraphState(BaseModel):
    task: str
    history: list[dict] = []
    history_summary: str = ""
    plan: Plan | None = None
    results: dict[str, AgentResult] = {}
    errors: list[str] = []
    review_decision: str = ""
    review_feedback: str = ""
    anti_patterns: list[AntiPattern] = []
    constraints: list[str] = []
    step_count: int = 0
    max_steps: int = 20
    max_revisions: int = 3

    model_config = ConfigDict(arbitrary_types_allowed=True)


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


# ── 反模式系统 ──────────────────────────────────────────────────


def save_anti_pattern(ap: AntiPattern) -> None:
    """追加或更新反模式条目到 experiences.md。"""
    _EXPERIENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 如果已有相同 label+task，只更新时间戳（去重）
    if _EXPERIENCES_FILE.exists():
        content = _EXPERIENCES_FILE.read_text(encoding="utf-8")
        marker = f"## Anti-Pattern: {ap.label}"
        if marker in content and ap.task in content:
            # 已存在相同条目 — 跳过（简单去重）
            logger.info("[AntiPattern] duplicate skipped: %s / %s", ap.label, ap.task)
            return
    entry = (
        f"\n## Anti-Pattern: {ap.label}\n"
        f"- Task: {ap.task}\n"
        f"- Agent: {ap.agent}\n"
        f"- What happened: {ap.what_happened}\n"
        f"- Suggestion: {ap.suggestion}\n"
        f"- Severity: {ap.severity}\n"
        f"- Date: {date_str}\n"
    )
    try:
        with _EXPERIENCES_FILE.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        logger.warning("Failed to save anti-pattern")


def load_constraints() -> list[str]:
    """从 experiences.md 提炼最近 N 条约束。"""
    if not _EXPERIENCES_FILE.exists():
        return []
    try:
        content = _EXPERIENCES_FILE.read_text(encoding="utf-8")
    except OSError:
        return []
    constraints: list[str] = []
    for line in content.split("\n"):
        if line.startswith("- Suggestion:"):
            suggestion = line[len("- Suggestion:"):].strip()
            if suggestion:
                constraints.append(suggestion)
    return constraints[-10:]  # 最多取最近 10 条


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


# Register Plan with LangGraph checkpoint serializer
try:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    JsonPlusSerializer.register_type(Plan, "src.agent.orchestrator.planner", "Plan")
except Exception:
    pass
