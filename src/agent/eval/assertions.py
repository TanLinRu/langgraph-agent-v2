from __future__ import annotations

import re
from typing import Any

from src.agent.eval.models import EvalExpectation, EvalResultItem


def check_tool_called(
    events: list[dict[str, Any]],
    expected_tools: list[str],
) -> EvalResultItem:
    for ev in events:
        if ev.get("type") == "tool_call":
            tcs = ev.get("data", []) or []
            for tc in tcs:
                if isinstance(tc, dict) and tc.get("name") in expected_tools:
                    return EvalResultItem(
                        assertion=f"tool_call({expected_tools})",
                        passed=True,
                        detail=f"Found tool: {tc.get('name')}",
                    )
    return EvalResultItem(
        assertion=f"tool_call({expected_tools})",
        passed=False,
        detail=f"Expected tools {expected_tools} not found in any tool_call event",
    )


def check_tool_not_called(
    events: list[dict[str, Any]],
    forbidden_tools: list[str],
) -> EvalResultItem:
    for ev in events:
        if ev.get("type") == "tool_call":
            tcs = ev.get("data", []) or []
            for tc in tcs:
                if isinstance(tc, dict) and tc.get("name") in forbidden_tools:
                    return EvalResultItem(
                        assertion=f"forbidden_tool({forbidden_tools})",
                        passed=False,
                        detail=f"Unexpected tool call: {tc.get('name')}",
                    )
    return EvalResultItem(
        assertion=f"forbidden_tool({forbidden_tools})",
        passed=True,
        detail="No forbidden tools called",
    )


def check_language(
    events: list[dict[str, Any]],
    expected_lang: str | None,
) -> EvalResultItem:
    if expected_lang is None:
        return EvalResultItem(assertion="language", passed=True, detail="No language constraint")
    combined = _collect_text(events)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", combined))
    total = len(combined.strip())
    if expected_lang == "chinese":
        if total > 0 and chinese_chars / total < 0.05:
            return EvalResultItem(
                assertion="language(chinese)",
                passed=False,
                detail=f"Chinese chars: {chinese_chars}/{total} ({chinese_chars/total:.1%})",
            )
        return EvalResultItem(
            assertion="language(chinese)",
            passed=True,
            detail=(
                f"Chinese chars: {chinese_chars}/{total} "
                f"({chinese_chars/total:.1%})"
            ) if total > 0 else "No text to evaluate",
        )
    return EvalResultItem(
        assertion=f"language({expected_lang})", passed=True, detail="Language check passed",
    )


def check_output_length(
    events: list[dict[str, Any]],
    min_len: int,
    max_len: int,
) -> EvalResultItem:
    combined = _collect_text(events)
    total = len(combined.strip())
    if min_len > 0 and total < min_len:
        return EvalResultItem(
            assertion=f"min_output_length({min_len})",
            passed=False,
            detail=f"Output length {total} < minimum {min_len}",
        )
    if max_len > 0 and total > max_len:
        return EvalResultItem(
            assertion=f"max_output_length({max_len})",
            passed=False,
            detail=f"Output length {total} > maximum {max_len}",
        )
    return EvalResultItem(
        assertion=f"output_length({min_len}-{max_len})",
        passed=True,
        detail=f"Output length: {total}",
    )


def check_content_contains(
    events: list[dict[str, Any]],
    must_contain: list[str],
) -> EvalResultItem:
    if not must_contain:
        return EvalResultItem(assertion="content_contains", passed=True, detail="No content constraints")
    combined = _collect_text(events)
    missing = [kw for kw in must_contain if kw not in combined]
    if missing:
        return EvalResultItem(
            assertion=f"content_contains({must_contain})",
            passed=False,
            detail=f"Missing keywords: {missing}",
        )
    return EvalResultItem(
        assertion=f"content_contains({must_contain})",
        passed=True,
        detail="All keywords found",
    )


def check_content_not_contain(
    events: list[dict[str, Any]],
    must_not_contain: list[str],
) -> EvalResultItem:
    if not must_not_contain:
        return EvalResultItem(assertion="content_not_contain", passed=True, detail="No exclusion constraints")
    combined = _collect_text(events)
    found = [kw for kw in must_not_contain if kw in combined]
    if found:
        return EvalResultItem(
            assertion=f"content_not_contain({must_not_contain})",
            passed=False,
            detail=f"Forbidden content found: {found}",
        )
    return EvalResultItem(
        assertion=f"content_not_contain({must_not_contain})",
        passed=True,
        detail="No forbidden content found",
    )


def check_plan_steps(
    events: list[dict[str, Any]],
    expected_steps: int | None,
) -> EvalResultItem:
    if expected_steps is None:
        return EvalResultItem(assertion="plan_steps", passed=True, detail="No step constraint")
    for ev in events:
        if ev.get("type") == "plan":
            steps = ev.get("steps", [])
            actual = len(steps)
            if actual != expected_steps:
                return EvalResultItem(
                    assertion=f"plan_steps({expected_steps})",
                    passed=False,
                    detail=f"Plan has {actual} steps, expected {expected_steps}",
                )
            return EvalResultItem(
                assertion=f"plan_steps({expected_steps})",
                passed=True,
                detail=f"Plan has {actual} steps",
            )
    return EvalResultItem(
        assertion=f"plan_steps({expected_steps})",
        passed=False,
        detail="No plan event found",
    )


def check_plan_agents(
    events: list[dict[str, Any]],
    expected_agents: list[str],
) -> EvalResultItem:
    if not expected_agents:
        return EvalResultItem(assertion="plan_agents", passed=True, detail="No agent constraint")
    for ev in events:
        if ev.get("type") == "plan":
            steps = ev.get("steps", [])
            actual_agents = {s.get("agent", "") for s in steps}
            missing = [a for a in expected_agents if a not in actual_agents]
            if missing:
                return EvalResultItem(
                    assertion=f"plan_agents({expected_agents})",
                    passed=False,
                    detail=f"Missing agents: {missing}",
                )
            return EvalResultItem(
                assertion=f"plan_agents({expected_agents})",
                passed=True,
                detail=f"Agents found: {actual_agents}",
            )
    return EvalResultItem(
        assertion=f"plan_agents({expected_agents})",
        passed=False,
        detail="No plan event found",
    )


# ── Run all assertions ────────────────────────────────────────────────


def run_assertions(
    events: list[dict[str, Any]],
    expected: EvalExpectation,
) -> list[EvalResultItem]:
    results: list[EvalResultItem] = []

    if expected.must_call_tools:
        results.append(check_tool_called(events, expected.must_call_tools))
    if expected.must_not_call_tools:
        results.append(check_tool_not_called(events, expected.must_not_call_tools))
    if expected.language:
        results.append(check_language(events, expected.language))
    if expected.min_output_length > 0 or expected.max_output_length > 0:
        results.append(check_output_length(events, expected.min_output_length, expected.max_output_length))
    if expected.must_contain:
        results.append(check_content_contains(events, expected.must_contain))
    if expected.must_not_contain:
        results.append(check_content_not_contain(events, expected.must_not_contain))
    if expected.plan_steps is not None:
        results.append(check_plan_steps(events, expected.plan_steps))
    if expected.plan_agents:
        results.append(check_plan_agents(events, expected.plan_agents))

    return results


# ── Helpers ────────────────────────────────────────────────────────────


def _collect_text(events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for ev in events:
        etype = ev.get("type")
        if etype in ("message", "summary", "audit_summary", "plan"):
            data = ev.get("data", "")
            if isinstance(data, str):
                parts.append(data)
    return "\n".join(parts)
