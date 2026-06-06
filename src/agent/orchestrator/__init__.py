"""Orchestrator 子包 — StateGraph 6 节点版本 (perceive→plan→wait→dispatch→synthesize→reflect)。

对外暴露:
* :class:`Orchestrator` —— 顶层编排器
* :mod:`src.agent.orchestrator.core` —— StateGraph 核心
"""

from src.agent.orchestrator.core import Orchestrator

__all__ = [
    "Orchestrator",
]
