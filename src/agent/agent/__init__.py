"""Agent 单 Agent 执行子包。

对外暴露
--------
:class:`Agent` —— 从 ``create_react_agent`` 构建的单 Agent 循环,提供 ``run()`` 异步生成器。

注意
----
* 本包处理**单 Agent** 的 ReAct 循环;多 Agent 编排请使用 ``src.agent.orchestrator``。
* ``Agent.run()`` 产生的事件格式与 :mod:`src.agent.events` 协议兼容。
"""

from src.agent.agent.core import Agent

__all__ = ["Agent"]
