"""统一事件协议 (Event Protocol)。

模块职责
--------
本模块是后端 SSE 流式输出的**唯一事件来源**,被以下模块依赖:

* ``src/agent/orchestrator/*`` —— 在 plan / dispatch / summarize 各阶段产生事件
* ``server.py`` —— 把事件原样转发给前端

为什么需要统一协议
------------------
旧版本散落着 ``{"type": "thinking_start", "agent_name": ...}`` 这种魔法字符串,
新增事件类型时容易拼写错误。本模块提供:

1. ``EventType`` —— 事件类型常量,所有事件类型的唯一字面值来源
2. ``make_event()`` —— 构造事件的工厂,保证字段名一致
3. 顶层 docstring 列出所有事件 schema —— 给前端 / 后端共同参考

事件 Schema 总览
----------------
每个事件都是 ``dict[str, Any]``,必有字段:

* ``type``: 事件类型 (见 ``EventType``)
* ``agent_name``: 谁产生的 (supervisor / sub-agent 名),``done`` 事件无此字段

按类型列出其它字段:

================  ==========================================================
thinking_start     (无 data, 标识一个推理段开始)
thinking           ``data: str`` (累积的推理文本)
thinking_done      (无 data, 标识推理段结束)
plan               ``data: str`` (Plan 文本,可被前端解析渲染)
message            ``data: str`` (累积的最终输出,一次流可被多次分块)
tool_call          ``data: list[dict]`` (工具调用列表,每项含 ``name`` / ``args``)
task_update        ``data: dict`` (``{agent, task, status, ...}``,status 是
                   ``pending`` / ``running`` / ``completed`` / ``failed``)
metrics            ``data: dict`` (``{elapsed_ms, agent_calls, tokens}``,
                   ``tokens`` 是 ``{agent_name: {input, output, ms}}``)
summary            ``data: str`` (多 agent 协同后的 LLM 综合摘要)
audit_summary      ``data: str`` (审计摘要,包含各 Agent 审计结果)
interrupt          ``data: dict`` (``{thread_id, plan}``,等待用户审核的 plan)
error              ``data: str`` (错误消息,通常是异常文本)
done               (无其它字段,流结束的标志)
================  ==========================================================
"""

from __future__ import annotations

from typing import Any, Final


class EventType:
    """事件类型常量。

    为什么用类而不是 ``Enum``:
        前端 SSE 解析时拿到的是字符串字面值,``Enum`` 反而多一层解引用。
        把事件类型集中为类属性,IDE 可以跳转,重构时一个地方改完全部生效。
    """

    # ── 推理段事件 (3 个) ────────────────────────────────────────
    THINKING_START: Final[str] = "thinking_start"  # 推理开始,无 data
    THINKING: Final[str] = "thinking"  # 推理增量,``data`` 是增量文本
    THINKING_DONE: Final[str] = "thinking_done"  # 推理结束,无 data

    # ── 计划事件 (1 个) ──────────────────────────────────────────
    PLAN: Final[str] = "plan"  # 计划文本,``data`` 是计划原文(可被解析)

    # ── 输出事件 (2 个) ──────────────────────────────────────────
    MESSAGE: Final[str] = "message"  # 消息增量,``data`` 是增量文本
    TOOL_CALL: Final[str] = "tool_call"  # 工具调用,``data`` 是 list

    # ── 任务状态事件 (1 个) ──────────────────────────────────────
    TASK_UPDATE: Final[str] = "task_update"  # 任务状态变更

    # ── 审计 (1 个) ──────────────────────────────────────────────
    AUDIT_SUMMARY: Final[str] = "audit_summary"  # 审计摘要

    # ── 摘要 / 度量 / 错误 (3 个) ────────────────────────────────
    SUMMARY: Final[str] = "summary"  # 监督者综合
    METRICS: Final[str] = "metrics"  # 性能 / 计量数据
    ERROR: Final[str] = "error"  # 错误消息

    # ── 权限请求 (1 个) ────────────────────────────────────────────
    PERMISSION_REQUEST: Final[str] = "permission_request"  # ACP agent 请求用户授权

    # ── 中断事件 (1 个) ───────────────────────────────────────────
    INTERRUPT: Final[str] = "interrupt"  # 等待用户审核,``data`` 是 {thread_id, plan}

    # ── 流结束 (1 个) ────────────────────────────────────────────
    DONE: Final[str] = "done"  # 流终止,后续不会有任何事件

    @classmethod
    def all(cls) -> set[str]:
        """返回所有事件类型集合,用于测试断言或日志过滤。"""
        return {
            cls.THINKING_START, cls.THINKING, cls.THINKING_DONE,
            cls.PLAN, cls.MESSAGE, cls.TOOL_CALL, cls.TASK_UPDATE,
            cls.AUDIT_SUMMARY,
            cls.SUMMARY, cls.METRICS, cls.ERROR,
            cls.PERMISSION_REQUEST,
            cls.INTERRUPT, cls.DONE,
        }


# ── 事件工厂 ────────────────────────────────────────────────────


def make_event(
    event_type: str,
    agent_name: str | None = None,
    data: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """构造一个事件字典。

    参数
    ----
    event_type:
        事件类型,必须是 ``EventType.*`` 之一 (本函数不强制校验,方便测试构造异常事件)。
    agent_name:
        产生该事件的 agent 名;``None`` 表示无主 (例如 ``done``)。
    data:
        事件负载,具体类型取决于 ``event_type`` (见模块顶部 schema 表)。
    **extra:
        其它附加字段 (例如 ``session_id`` 透传),会被原样合并到事件中。

    返回值
    ------
    ``dict[str, Any]``,形如::

        {"type": "...", "agent_name": "...", "data": ..., ...}
    """
    # 先放固定字段,再放 extras —— 防止 extras 误覆盖 type/agent_name
    evt: dict[str, Any] = {"type": event_type}
    if agent_name is not None:
        evt["agent_name"] = agent_name
    if data is not None:
        evt["data"] = data
    evt.update(extra)
    return evt


# ── 便捷工厂 (按事件类型分组,可读性更好) ─────────────────────


def make_thinking_start(agent_name: str) -> dict[str, Any]:
    """构造 ``thinking_start`` 事件,标志一段推理开始。"""
    return make_event(EventType.THINKING_START, agent_name=agent_name)


def make_thinking(agent_name: str, data: str) -> dict[str, Any]:
    """构造 ``thinking`` 事件,``data`` 是推理文本增量。"""
    return make_event(EventType.THINKING, agent_name=agent_name, data=data)


def make_thinking_done(agent_name: str) -> dict[str, Any]:
    """构造 ``thinking_done`` 事件,标志一段推理结束。"""
    return make_event(EventType.THINKING_DONE, agent_name=agent_name)


def make_plan(agent_name: str, plan_text: str, **extra: Any) -> dict[str, Any]:
    """构造 ``plan`` 事件,``data`` 是计划文本 (Markdown 格式的可读展示)。

    ``extra`` 可用于附加结构化字段,例如 ``steps=[{agent, task}]``。
    """
    evt = make_event(EventType.PLAN, agent_name=agent_name, data=plan_text)
    evt.update(extra)
    return evt


def make_message(
    agent_name: str,
    data: str,
    file_refs: list[str] | None = None,
) -> dict[str, Any]:
    """构造 ``message`` 事件,``data`` 是消息文本增量。

    ``file_refs`` 可选,传递给前端用于文件链接高亮。
    """
    return make_event(
        EventType.MESSAGE,
        agent_name=agent_name,
        data=data,
        **(dict(file_refs=file_refs) if file_refs else {}),
    )


def make_tool_call(agent_name: str, tool_calls: list[dict]) -> dict[str, Any]:
    """构造 ``tool_call`` 事件,``data`` 是工具调用列表 ``[{name, args}, ...]``。"""
    return make_event(EventType.TOOL_CALL, agent_name=agent_name, data=tool_calls)


def make_task_update(
    agent_name: str,
    task_agent: str,
    task: str,
    status: str,
    **extra: Any,
) -> dict[str, Any]:
    """构造 ``task_update`` 事件,描述一个子任务的状态变化。

    参数
    ----
    agent_name:
        事件发布者 (通常是 ``supervisor``)。
    task_agent:
        任务归属的子 agent (例如 ``coder`` / ``opencode``)。
    task:
        任务描述 (用户原始 step 文本)。
    status:
        任务状态,可选 ``pending`` / ``running`` / ``completed`` / ``failed``。
    """
    payload: dict[str, Any] = {"agent": task_agent, "task": task, "status": status}
    payload.update(extra)
    return make_event(EventType.TASK_UPDATE, agent_name=agent_name, data=payload)


def make_interrupt(agent_name: str | None = None, data: dict | None = None) -> dict[str, Any]:
    """构造 ``interrupt`` 事件,``data`` 包含 ``{thread_id, plan}``。"""
    return make_event(EventType.INTERRUPT, agent_name=agent_name, data=data)


def make_permission_request(agent_name: str | None = None, data: dict | None = None) -> dict[str, Any]:
    """构造 ``permission_request`` 事件,``data`` 包含 ``{req_id, toolCall, options, agent_id}``。"""
    return make_event(EventType.PERMISSION_REQUEST, agent_name=agent_name, data=data)


def make_audit_summary(agent_name: str, data: str) -> dict[str, Any]:
    """构造 ``audit_summary`` 事件,``data`` 是审计报告文本。"""
    return make_event(EventType.AUDIT_SUMMARY, agent_name=agent_name, data=data)


def make_summary(agent_name: str, summary_text: str) -> dict[str, Any]:
    """构造 ``summary`` 事件,``data`` 是综合摘要文本。"""
    return make_event(EventType.SUMMARY, agent_name=agent_name, data=summary_text)


def make_metrics(agent_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    """构造 ``metrics`` 事件,``data`` 是 ``{elapsed_ms, agent_calls, tokens}``。"""
    return make_event(EventType.METRICS, agent_name=agent_name, data=metrics)


def make_error(agent_name: str | None, error: str) -> dict[str, Any]:
    """构造 ``error`` 事件,``data`` 是错误描述。"""
    return make_event(EventType.ERROR, agent_name=agent_name, data=error)


def make_done() -> dict[str, Any]:
    """构造 ``done`` 事件,标志 SSE 流终止。"""
    return make_event(EventType.DONE)
