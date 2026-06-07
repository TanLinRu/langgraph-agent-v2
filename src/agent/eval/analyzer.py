from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict

from src.agent.eval.models import SuggestionDraft
from src.agent.eval.storage import (
    get_runs_in_range,
    list_suggestions,
    save_suggestion,
)

logger = logging.getLogger(__name__)

_SAMPLE_THRESHOLD = 3


async def run_full_analysis(days: int = 7) -> list[SuggestionDraft]:
    drafts: list[SuggestionDraft] = []

    drafts.extend(_analyze_prompt(days))
    drafts.extend(_analyze_agent(days))
    drafts.extend(_analyze_workflow(days))
    drafts.extend(_analyze_context(days))
    drafts.extend(_analyze_skill(days))

    for d in drafts:
        existing = list_suggestions(dimension=d.dimension, only_active=True)
        if any(e.target == d.target for e in existing):
            continue
        sid = save_suggestion(d)
        logger.info("[ANALYZER] suggestion id=%s dimension=%s target=%s confidence=%.2f",
                     sid, d.dimension, d.target, d.confidence)

    return drafts


# ── Prompt dimension ─────────────────────────────────────────────────


def _analyze_prompt(days: int) -> list[SuggestionDraft]:
    drafts: list[SuggestionDraft] = []
    runs = get_runs_in_range(days)

    verifier_failures = 0
    verifier_total = 0
    for r in runs:
        if not r.failures:
            continue
        for f in r.failures:
            if "hallucinat" in f.detail.lower() or "verifier" in f.assertion.lower():
                verifier_failures += 1
            verifier_total += 1

    if verifier_total >= _SAMPLE_THRESHOLD and verifier_failures / verifier_total > 0.15:
        rate_str = f"{verifier_failures/verifier_total:.0%}"
        drafts.append(SuggestionDraft(
            dimension="prompt",
            target="system_prompt.verifier",
            current_value="Only verify claims present in upstream results",
            suggested_value=(
                "Append: 'If upstream results are empty or absent, "
                "report no claims found without guessing'"
            ),
            reasoning=(
                f"Verifier hallucination rate {verifier_failures}/"
                f"{verifier_total} ({rate_str}) exceeds 15% threshold"
            ),
            evidence=[{
                "type": "audit_summary",
                "failures": verifier_failures,
                "total": verifier_total,
            }],
            confidence=min(0.95, verifier_failures / verifier_total),
        ))

    return drafts


# ── Agent dimension ──────────────────────────────────────────────────


def _analyze_agent(days: int) -> list[SuggestionDraft]:
    drafts: list[SuggestionDraft] = []
    runs = get_runs_in_range(days)

    agent_failures: dict[str, list[dict]] = defaultdict(list)
    agent_metrics: dict[str, list[dict]] = defaultdict(list)

    for r in runs:
        for f in r.failures:
            agent = _extract_agent_from_failure(f.assertion, f.detail)
            if agent:
                agent_failures[agent].append({
                    "assertion": f.assertion,
                    "detail": f.detail,
                })

        if r.metrics_snapshot:
            tokens = r.metrics_snapshot.get("tokens", {}) or {}
            for agent, tok in tokens.items():
                agent_metrics[agent].append(tok)

    for agent, fails in agent_failures.items():
        if len(fails) >= _SAMPLE_THRESHOLD:
            confidence = min(0.9, len(fails) / (len(fails) + 5))
            drafts.append(SuggestionDraft(
                dimension="agent",
                target=f"agent.{agent}.temperature",
                current_value="0.7",
                suggested_value="0.3",
                reasoning=(
                    f"Agent '{agent}' has {len(fails)} failures "
                    "in recent evals. Lower temperature may reduce "
                    "output variance."
                ),
                evidence=[{
                    "agent": agent,
                    "failures": len(fails),
                    "samples": [f["detail"] for f in fails[:3]],
                }],
                confidence=confidence,
            ))

    for agent, metrics_list in agent_metrics.items():
        if len(metrics_list) >= _SAMPLE_THRESHOLD:
            _tokens = []
            for m in metrics_list:
                if isinstance(m, dict):
                    _tokens.append(m.get("output", m.get("total", 0)) or 0)
                elif isinstance(m, (int, float)):
                    _tokens.append(m)
            if not _tokens:
                continue
            avg_tokens = sum(_tokens) / len(_tokens)
            if avg_tokens > 2000:
                capped = int(avg_tokens * 1.2)
                drafts.append(SuggestionDraft(
                    dimension="agent",
                    target=f"agent.{agent}.max_tokens",
                    current_value="default",
                    suggested_value=str(capped),
                    reasoning=(
                        f"Agent '{agent}' averages {avg_tokens:.0f} "
                        f"output tokens. Capping at {capped} may reduce "
                        "cost with minimal quality impact."
                    ),
                    evidence=[{
                        "agent": agent,
                        "avg_output_tokens": avg_tokens,
                        "samples": len(metrics_list),
                    }],
                    confidence=min(0.8, len(metrics_list) / 10),
                ))

    return drafts


# ── Workflow dimension ───────────────────────────────────────────────


def _analyze_workflow(days: int) -> list[SuggestionDraft]:
    drafts: list[SuggestionDraft] = []
    runs = get_runs_in_range(days)

    step_counts: list[int] = []
    agent_combos: Counter = Counter()

    for r in runs:
        if r.session_id:
            try:
                from src.agent.db.connection import _get_conn
                conn = _get_conn()
                row = conn.execute(
                    "SELECT plan FROM sessions WHERE session_id = ?",
                    (r.session_id,),
                ).fetchone()
                conn.close()
                if row and row[0]:
                    plan = json.loads(row[0])
                    steps = plan.get("steps", []) or []
                    step_counts.append(len(steps))
                    agents = tuple(
                        sorted(s.get("agent", "") for s in steps if s.get("agent"))
                    )
                    if agents:
                        agent_combos[agents] += 1
            except Exception:
                pass

    for combo, count in agent_combos.most_common(3):
        if count >= 3:
            combo_str = "+".join(combo)
            drafts.append(SuggestionDraft(
                dimension="workflow",
                target="orchestrator._route_from_plan",
                current_value="Dynamic per LLM plan",
                suggested_value=(
                    f"Consider pre-defined template for combo: {combo_str}"
                ),
                reasoning=(
                    f"Agent combo {combo_str} appeared {count} times "
                    "in recent evals. A pre-defined workflow template "
                    "may improve consistency."
                ),
                evidence=[{"combo": combo_str, "count": count}],
                confidence=min(0.7, count / 10),
            ))

    return drafts


# ── Context dimension ────────────────────────────────────────────────


def _analyze_context(days: int) -> list[SuggestionDraft]:
    drafts: list[SuggestionDraft] = []
    runs = get_runs_in_range(days)

    msg_counts: list[int] = []
    for r in runs:
        if r.session_id:
            try:
                from src.agent.db.connection import _get_conn
                conn = _get_conn()
                row = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ?",
                    (r.session_id,),
                ).fetchone()
                conn.close()
                if row:
                    msg_counts.append(row[0])
            except Exception:
                pass

    if msg_counts and len(msg_counts) >= _SAMPLE_THRESHOLD:
        avg_msgs = sum(msg_counts) / len(msg_counts)
        max_msgs = max(msg_counts)
        if max_msgs > 20:
            drafts.append(SuggestionDraft(
                dimension="context",
                target="AGENT_COMPRESSION_THRESHOLD",
                current_value="0.7",
                suggested_value="0.5",
                reasoning=(
                    f"Max messages per session: {max_msgs}, "
                    f"avg: {avg_msgs:.0f}. Lowering compression "
                    "threshold may reduce context usage."
                ),
                evidence=[{
                    "avg_messages": avg_msgs,
                    "max_messages": max_msgs,
                    "samples": len(msg_counts),
                }],
                confidence=min(0.6, len(msg_counts) / 15),
            ))

    return drafts


# ── Skill dimension ──────────────────────────────────────────────────


def _analyze_skill(days: int) -> list[SuggestionDraft]:
    drafts: list[SuggestionDraft] = []
    runs = get_runs_in_range(days)

    tool_call_counter: Counter = Counter()
    for r in runs:
        if r.session_id:
            try:
                from src.agent.db.connection import _get_conn
                conn = _get_conn()
                rows = conn.execute(
                    "SELECT tool_calls FROM messages "
                    "WHERE session_id = ? AND tool_calls "
                    "IS NOT NULL AND tool_calls != ''",
                    (r.session_id,),
                ).fetchall()
                conn.close()
                for row in rows:
                    try:
                        tcs = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        for tc in tcs:
                            if isinstance(tc, dict):
                                tn = tc.get("name", tc.get("tool_name", ""))
                                if tn:
                                    tool_call_counter[tn] += 1
                    except (json.JSONDecodeError, TypeError):
                        pass
            except Exception:
                pass

    if tool_call_counter:
        try:
            from src.agent.config_manager import get_config_manager
            cm = get_config_manager()
            tools_config = cm.get_tools()
            total_calls = sum(tool_call_counter.values())
            for tool_id in tools_config:
                if tool_call_counter.get(tool_id, 0) == 0:
                    drafts.append(SuggestionDraft(
                        dimension="skill",
                        target=f"config.tools.{tool_id}",
                        current_value="enabled",
                        suggested_value="review or disable",
                        reasoning=(
                            f"Tool '{tool_id}' was never called in "
                            f"{days}-day eval history "
                            f"({total_calls} total tool calls)."
                        ),
                        evidence=[{
                            "tool_id": tool_id,
                            "total_tool_calls": total_calls,
                        }],
                        confidence=0.85,
                    ))
        except Exception:
            pass

    return drafts


# ── Helpers ────────────────────────────────────────────────────────────


def _extract_agent_from_failure(assertion: str, detail: str) -> str | None:
    for keyword in ["coder", "researcher", "analyst", "verifier", "direct"]:
        if keyword in assertion.lower() or keyword in detail.lower():
            return keyword
    return None
