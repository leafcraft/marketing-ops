"""brand_guardian_agent — crisis-pause floor (Python REQUIRED).

WHY THIS MODULE EXISTS (and is not pure YAML):

  @chain enforce_crisis_floor — a DETERMINISTIC pause/escalation floor the
      LLM cannot waive. In crisis mode (mode empty or "crisis"),
      requires_cmo_action is forced TRUE — a crisis ALWAYS lands on the CMO
      desk no matter how minor the model judged it. The severe-negative-
      spike rule (volume_change_pct > 0.5 AND avg_sentiment_7d < -0.3) is
      recomputed here from the rollups, not trusted to the LLM, and also
      forces requires_cmo_action. crisis_type regulatory|data_breach forces
      "legal" into escalate_to. The LLM may RAISE severity; it can never
      LOWER the route below this floor.

All crisis narrative + holding-statement drafting still lives in the YAML
prompt; the pause/escalation route is enforced here.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain

logger = LeafMeshLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "severity": 0,
    "crisis_type": "",
    "immediate_action": "",
    "holding_statement_draft": "",
    "escalate_to": [],
    "cmo_briefing": "",
    "campaign_id": "",
    "strategy_summary": "",
    "mode": "",
    "mentions_last_7d": 0,
    "mentions_last_30d": 0,
    "avg_sentiment_7d": 0,
    "avg_sentiment_30d": 0,
    "volume_change_pct": 0,
    "top_negative_sources": [],
    "severe_negative_spike": False,
    "requires_cmo_action": False,
    "sentiment_briefing": "",
}

_LEGAL_CRISIS = {"regulatory", "data_breach"}


def _parse_json(text: Any) -> dict[str, Any]:
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return {}
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except (ValueError, TypeError):
            return {}
    return {}


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def is_severe_spike(volume_change_pct: Any, avg_sentiment_7d: Any) -> bool:
    """Pure: the deterministic severe-negative-spike rule."""
    return _num(volume_change_pct) > 0.5 and _num(avg_sentiment_7d) < -0.3


def is_crisis_mode(mode: Any) -> bool:
    m = str(mode or "").strip().lower()
    return m in ("", "crisis")


# ── @chain: deterministic crisis-pause / escalation floor ────────────────
async def enforce_crisis_floor(result: dict, ctx: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}

    mode = str(result.get("mode", "")).strip().lower()

    # Recompute the spike rule from the rollups — never trust the LLM's bool.
    spike = is_severe_spike(result.get("volume_change_pct"),
                            result.get("avg_sentiment_7d"))
    result["severe_negative_spike"] = bool(result.get("severe_negative_spike")) or spike

    # FLOOR — a crisis ALWAYS reaches the CMO; a severe spike does too.
    if is_crisis_mode(mode):
        result["requires_cmo_action"] = True
        if not result.get("immediate_action"):
            result["immediate_action"] = (
                "Pause active campaigns; convene crisis team; "
                "draft holding statement.")
    elif result["severe_negative_spike"]:
        result["requires_cmo_action"] = True
    else:
        result["requires_cmo_action"] = bool(result.get("requires_cmo_action"))

    # Regulatory / data-breach always pulls legal into the escalation set.
    escalate = [str(x).lower() for x in (result.get("escalate_to") or [])]
    if str(result.get("crisis_type", "")).strip().lower() in _LEGAL_CRISIS:
        if "legal" not in escalate:
            escalate.append("legal")
    if result["requires_cmo_action"] and "cmo" not in escalate:
        escalate.append("cmo")
    result["escalate_to"] = escalate

    logger.info(
        f"[brand_guardian] crisis floor — mode={mode or 'crisis'} "
        f"spike={result['severe_negative_spike']} "
        f"cmo_action={result['requires_cmo_action']} escalate={escalate}"
    )
    return result


@chain(enforce_crisis_floor)
async def brand_guardian_agent(llm_response, input_data: dict, context: dict) -> dict[str, Any]:
    """Surface the guardian's judgment; the floor enforces the pause route."""
    parsed = _parse_json(llm_response)
    input_data = input_data if isinstance(input_data, dict) else {}

    out = {**_DEFAULTS}
    for k in _DEFAULTS:
        if k in parsed and parsed[k] not in (None, ""):
            out[k] = parsed[k]

    # Echo the input mode + rollups when the LLM dropped them, so the floor
    # recomputes the spike rule from the real platform numbers.
    if not out["mode"]:
        out["mode"] = str(input_data.get("mode") or "")
    for k in ("volume_change_pct", "avg_sentiment_7d", "avg_sentiment_30d",
              "mentions_last_7d", "mentions_last_30d"):
        if not out.get(k) and input_data.get(k) not in (None, ""):
            out[k] = input_data[k]
    return out
