from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class EvalExpectation(BaseModel):
    must_call_tools: list[str] = []
    must_not_call_tools: list[str] = []
    language: str | None = "chinese"
    min_output_length: int = 0
    max_output_length: int = 0
    must_contain: list[str] = []
    must_not_contain: list[str] = []
    plan_steps: int | None = None
    plan_agents: list[str] = []
    forbid_hallucinated_refs: bool = False
    custom: list[dict] = []


class EvalCase(BaseModel):
    case_id: str
    task: str
    tags: list[str] = []
    expected: EvalExpectation = EvalExpectation()
    source_type: str = "manual"
    source_session_id: str | None = None
    updated_at: str = ""


class EvalResultItem(BaseModel):
    assertion: str
    passed: bool
    detail: str = ""


class EvalRun(BaseModel):
    task_id: str
    case_id: str
    session_id: str | None = None
    thread_id: str | None = None
    passed: bool
    failures: list[EvalResultItem] = []
    metrics_snapshot: dict[str, Any] = {}
    config_snapshot: dict[str, Any] = {}
    triggered_by: str = "manual"
    created_at: str = ""


class EvalSuggestion(BaseModel):
    id: int = 0
    dimension: str
    target: str
    current_value: str = ""
    suggested_value: str = ""
    reasoning: str = ""
    evidence: list[dict] = []
    confidence: float = 0.0
    applied: bool = False
    applied_at: str = ""
    dismissed: bool = False
    created_at: str = ""


class SuggestionDraft(BaseModel):
    """分析器输出的原始建议（未落盘前）"""
    dimension: str
    target: str
    current_value: str
    suggested_value: str
    reasoning: str
    evidence: list[dict]
    confidence: float
