"""Orchestrator 子包。

对外暴露
--------
* :class:`Orchestrator` —— 顶层编排器,外部唯一使用入口
* :class:`Planner` —— 计划阶段,单测时直接可用
* :class:`LocalDispatcher` / :class:`ACPDispatcher` —— 执行阶段,单测可用
* :func:`summarize_stream` —— 综合阶段

历史
----
* 旧版本 ``src/agent/supervisor.py`` 中的 ``CustomSupervisor`` 已删除
* 旧版本 ``src/agent/graph.py`` 中的 ``StateGraph`` 已删除
* 旧版本 ``src/agent/event_bus.py`` 已删除 (由 SSE 直推替代)

参见
----
* :mod:`src.agent.events` —— 事件 schema / 工厂
* ``docs/diff.md`` 第 3 节 —— Orchestrator 完整设计
"""

from src.agent.orchestrator.core import Orchestrator
from src.agent.orchestrator.dispatcher import (
    ACPDispatcher,
    LocalDispatcher,
    make_dispatcher,
)
from src.agent.orchestrator.planner import Planner
from src.agent.orchestrator.summarizer import stream as summarize_stream

__all__ = [
    "Orchestrator",
    "Planner",
    "LocalDispatcher",
    "ACPDispatcher",
    "make_dispatcher",
    "summarize_stream",
]
