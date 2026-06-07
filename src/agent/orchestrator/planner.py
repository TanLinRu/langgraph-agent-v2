"""Planner — Pydantic models + plan helpers for the v2 StateGraph.

Contains:
- Pydantic models: Step, Plan, AgentResult, AntiPattern, GraphState
- Legacy helpers: build_agent_descriptions, _convert_history, load_experiences, save_experiences
- New helpers: load_constraints, save_anti_pattern, get_constraints
"""

from __future__ import annotations

import json
import logging
import operator
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

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
    direct_reply: str = ""


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
    direct_reply: str = ""
    results: Annotated[dict[str, AgentResult], operator.or_] = {}
    errors: Annotated[list[str], operator.add] = []
    review_decision: Annotated[str, lambda x, y: y if y else x] = ""
    review_feedback: str = ""
    anti_patterns: Annotated[list[AntiPattern], operator.add] = []
    constraints: list[str] = []
    step_count: int = 0
    max_steps: int = 20
    max_revisions: int = 3
    session_id: str = ""
    task_id: str = ""
    current_step_idx: str = ""
    executed_indices: Annotated[list[str], operator.add] = []

    model_config = ConfigDict(arbitrary_types_allowed=True)


class SubGraphState(BaseModel):
    """State schema for workflow subgraphs — uses sub_ prefix to avoid key collisions with parent GraphState."""

    sub_task: str
    sub_history: list[dict] = []
    sub_history_summary: str = ""
    sub_plan: Plan | None = None
    sub_direct_reply: str = ""
    sub_results: dict[str, AgentResult] = {}
    sub_errors: list[str] = []
    sub_review_decision: str = ""
    sub_review_feedback: str = ""
    sub_anti_patterns: list[AntiPattern] = []
    sub_constraints: list[str] = []
    sub_step_count: int = 0
    sub_max_steps: int = 20
    sub_max_revisions: int = 3
    sub_session_id: str = ""
    sub_task_id: str = ""
    sub_current_step_idx: str = ""
    sub_executed_indices: list[str] = []

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
# ── DAG 上下文构建 ─────────────────────────────────────────────


def build_step_context(
    step: Step,
    step_index_map: dict[str, Step],
    results: dict[str, AgentResult],
    history_summary: str,
) -> str:
    """根据 depends_on 构建上游结果上下文。"""
    dep_parts: list[str] = []
    for dep_idx in step.depends_on:
        dep_step = step_index_map.get(dep_idx)
        if not dep_step:
            continue
        dep_name = dep_step.agent
        dep_result = results.get(dep_name)
        if dep_result and dep_result.result:
            snippet = (dep_result.result[:2000] + "...") if len(dep_result.result) > 2000 else dep_result.result
            dep_parts.append(
                f"[Upstream: {dep_name}]\n"
                f"Task: {dep_result.task}\n"
                f"Output:\n{snippet}"
            )
    dep_section = "\n\n".join(dep_parts)
    if dep_section and history_summary:
        return f"{history_summary}\n\n--- Dependency Results ---\n{dep_section}"
    if dep_section:
        return f"Dependency Results:\n{dep_section}"
    return history_summary


# ── Reflect 消息加载 ────────────────────────────────────────────


def load_messages_for_reflect(
    session_id: str,
    task_id: str | None = None,
    end_time: str | None = None,
    max_messages: int = 100,
) -> str:
    """加载 session 消息，按 task_id 或 end_time 过滤，格式化为对话文本供 reflect 分析。

    两种查询模式:
      1. (session_id, task_id) — 精确获取某次 orchestrate run 的所有消息
      2. (session_id, end_time) — 获取截止到某个时间点的最近消息（覆盖本轮及最近几轮）

    返回格式:
      [role] name: content
      ...
    """
    from src.agent.db.connection import _get_conn

    conn = _get_conn()
    if task_id:
        rows = conn.execute(
            "SELECT role, content, name, created_at FROM messages "
            "WHERE session_id = ? AND task_id = ? AND compacted = 0 "
            "ORDER BY id LIMIT ?",
            (session_id, task_id, max_messages),
        ).fetchall()
    elif end_time:
        rows = conn.execute(
            "SELECT role, content, name, created_at FROM messages "
            "WHERE session_id = ? AND created_at <= ? AND compacted = 0 "
            "ORDER BY id DESC LIMIT ?",
            (session_id, end_time, max_messages),
        ).fetchall()
        rows.reverse()
    else:
        rows = conn.execute(
            "SELECT role, content, name, created_at FROM messages "
            "WHERE session_id = ? AND compacted = 0 "
            "ORDER BY id DESC LIMIT ?",
            (session_id, max_messages),
        ).fetchall()
        rows.reverse()
    conn.close()

    lines: list[str] = []
    for r in rows:
        role = r[0]
        content = (r[1] or "")[:500]
        name = r[2] or ""
        label = f"[{role}] {name}: " if name else f"[{role}] "
        lines.append(f"{label}{content}")
    return "\n".join(lines)


try:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    JsonPlusSerializer.register_type(Plan, "src.agent.orchestrator.planner", "Plan")
except Exception:
    pass
