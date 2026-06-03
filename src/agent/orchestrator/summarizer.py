"""Summarizer —— 综合阶段 (Orchestrator 的"收尾层")。

模块职责
--------
当 Planner 解析出**多个**步骤并由多个 sub-agent 完成后,需要把分散
的 ``(agent, task, result)`` 综合成一段面向用户的最终摘要。

为什么需要:
    * 单 agent 时:直接透传 sub-agent 的输出即可,无需再花 token 综合
    * 多 agent 时:用户只看到一段话,而不是 N 段拼接;否则既冗长又割裂

约束:
    * 只在 ``len(results) > 1`` 时调用 (避免浪费 token)
    * LLM 同步 ``astream`` 即可 (非流式),前端不在乎这一段是否分块
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.language_models import BaseChatModel

from src.agent.orchestrator._events import make_summary

logger = logging.getLogger(__name__)

# 监督者 system prompt —— 极简,只要求"简洁综合"
_SUMMARY_SYSTEM_PROMPT = (
    "You are a supervisor. Summarize the results from your team concisely."
)

# 综合 prompt 模板 —— 把所有 (agent, task, result) 拼成一段用户可读的上下文
_SUMMARY_USER_TEMPLATE = (
    "Task: {task}\n\n"
    "Results:\n{results_text}\n\n"
    "Provide a concise summary."
)


def _format_results(results: list[dict[str, str]]) -> str:
    """把 ``[{"agent", "task", "result"}]`` 拼成多行文本。"""
    return "\n\n".join(
        f"**{r['agent']}** ({r['task']}):\n{r['result']}" for r in results
    )


async def stream(
    model: BaseChatModel,
    task: str,
    results: list[dict[str, str]],
) -> AsyncIterator[dict[str, Any]]:
    """流式生成 supervisor 综合事件。

    参数
    ----
    model: supervisor 用的 LLM (与 Planner 共用同一个 model)
    task: 用户原始任务文本
    results: 所有 sub-agent 累积的结果,``[{"agent", "task", "result"}]``

    产出
    ----
    单个 ``summary`` 事件,``data`` 是 LLM 生成的综合文本。
    """
    results_text = _format_results(results)
    prompt = [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": _SUMMARY_USER_TEMPLATE.format(
            task=task, results_text=results_text
        )},
    ]
    summary_text = ""
    async for chunk in model.astream(prompt):
        if chunk.content:
            summary_text += chunk.content
    yield make_summary("supervisor", summary_text)
