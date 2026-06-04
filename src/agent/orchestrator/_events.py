"""Orchestrator 事件工具包。

模块职责
--------
为 orchestrator 子包提供事件构造的本地别名,使 ``orchestrator/*`` 内部
引用事件类型时不必每次写 ``from src.agent.events import ...`` 长路径。

为什么不直接 ``from src.agent.events import *``:
    在子包内做精确 import,既能享受 IDE 跳转,又便于在 orchestrator 层面
    添加针对该子包的辅助函数 (例如 ``make_supervisor_thinking()``)。
"""

from __future__ import annotations

from src.agent.events import (  # noqa: F401  (re-export)
    EventType,
    make_audit_summary,
    make_done,
    make_error,
    make_event,
    make_message,
    make_metrics,
    make_plan,
    make_summary,
    make_task_update,
    make_thinking,
    make_thinking_done,
    make_thinking_start,
    make_tool_call,
)
