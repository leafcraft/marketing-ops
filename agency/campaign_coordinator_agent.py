"""campaign_coordinator_agent — Campaign Coordinator (the case owner).

auto_discover matches `campaign_coordinator_agent`. The coordinator opens the
case on any brief, keeps live status, and SEQUENCES the human gates so no two
human members are ever wired directly to each other (legal-cleared -> the
coordinator -> the marketing manager). It never plans, drafts, reviews, or
publishes.

Routing must not be hallucinated, so the module owns it:

  @chain derive_action — sets `action` DETERMINISTICALLY. `route_to_manager`
      (the gate-advancing route) is reachable ONLY when a reviewer actually
      approved: the LLM can never emit it to jump a fresh brief past strategy +
      compliance to the approval gate.

  @compose — forwards the raw brief to the strategist on open_case, and recovers
      the reviewed campaign from the pre-gate session stash for the manager gate
      (the SDK resumes a HITL chain with only human-response meta fields).
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain, compose

from agency._shared.session_stash import resolve_session_id, stash_get

logger = LeafMeshLogger(__name__)

_APPROVE_TOKENS = frozenset({"approve", "approved", "sign", "signed", "yes", "ok"})
_VALID_LLM_ACTIONS = frozenset({"open_case", "status"})

_DEFAULTS: dict[str, Any] = {
    "action": "open_case",
    "campaign_id": "",
    "status_summary": "",
    "waiting_on": "",
}


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


def _original_payload(input_data: dict[str, Any]) -> dict[str, Any]:
    """The raw brief to forward to the strategist: an explicit `payload`, else
    the flat trigger fields (minus transport/meta)."""
    if isinstance(input_data.get("payload"), dict) and input_data["payload"]:
        return dict(input_data["payload"])
    meta = {"session_id", "sessionId", "from_agent", "human_message",
            "human_decision", "human_initiated", "original_webhook_data",
            "upstream_yields", "timestamp", "source_agent"}
    return {k: v for k, v in input_data.items() if k not in meta}


def _pick_campaign_id(input_data: dict[str, Any]) -> str:
    if input_data.get("campaign_id"):
        return str(input_data["campaign_id"])
    payload = input_data.get("payload")
    if isinstance(payload, dict) and payload.get("campaign_id"):
        return str(payload["campaign_id"])
    uy = input_data.get("upstream_yields")
    if isinstance(uy, dict):
        if uy.get("campaign_id"):
            return str(uy["campaign_id"])
        for v in uy.values():
            if isinstance(v, dict) and v.get("campaign_id"):
                return str(v["campaign_id"])
    return ""


# ── @chain: deterministic routing floor ──────────────────────────────────
def derive_action(result: Any, context: dict) -> dict[str, Any]:
    result = result if isinstance(result, dict) else {}
    from_agent = str(result.pop("_from_agent", "")).strip()
    human_message = str(result.pop("_human_message", "")).strip().lower()
    session_id = str(result.get("_session_id", ""))

    if from_agent == "legal_reviewer_human" and human_message in _APPROVE_TOKENS:
        # A reviewer actually approved — advance to the marketing manager. This
        # is the ONLY way to reach route_to_manager; the LLM cannot forge it.
        result["action"] = "route_to_manager"
        recovered = stash_get(session_id)
        if recovered.get("campaign_id") and not result.get("campaign_id"):
            result["campaign_id"] = str(recovered["campaign_id"])
        if not result.get("waiting_on"):
            result["waiting_on"] = "marketing_manager_human"
    else:
        a = str(result.get("action") or "").strip()
        result["action"] = a if a in _VALID_LLM_ACTIONS else "open_case"
        if result["action"] == "open_case" and not result.get("waiting_on"):
            result["waiting_on"] = "campaign_strategist_agent"

    logger.info(
        f"[coordinator] action={result['action']} campaign={result.get('campaign_id') or '?'} "
        f"(from={from_agent or 'entry'} msg={human_message or '-'})"
    )
    return result


# ── @compose: each downstream gets the payload IT needs ──────────────────
def _to_strategist(result: dict, ctx: dict) -> dict[str, Any]:
    return {
        "payload": result.get("_payload", {}),
        "campaign_id": result.get("campaign_id", ""),
    }


def _to_manager(result: dict, ctx: dict) -> dict[str, Any]:
    recovered = stash_get(str(result.get("_session_id", "")))
    return {
        "campaign_id": str(result.get("campaign_id") or recovered.get("campaign_id") or ""),
        "strategy_summary": str(recovered.get("strategy_summary") or ""),
        "reviewer_briefing": "Legal cleared the claims — final marketing sign-off required.",
    }


@compose(campaign_strategist_agent=_to_strategist,
         marketing_manager_human=_to_manager)
@chain(derive_action)
async def campaign_coordinator_agent(llm_response: Any, input_data: dict, context: dict) -> dict[str, Any]:
    """Surface the coordinator's status narrative; the floor decides the route."""
    parsed = _parse_json(llm_response)
    input_data = input_data if isinstance(input_data, dict) else {}

    out = {**_DEFAULTS}
    for k in _DEFAULTS:
        if k in parsed and parsed[k] not in (None, ""):
            out[k] = parsed[k]

    if not out["campaign_id"]:
        out["campaign_id"] = _pick_campaign_id(input_data)

    # Carry routing signals + recovery keys to the @chain floor / @compose
    # shapers (popped or ignored in yields; the coordinator does not enforce_yields).
    out["_from_agent"] = str(input_data.get("from_agent") or "")
    out["_human_message"] = str(input_data.get("human_message") or "")
    out["_session_id"] = resolve_session_id(input_data, context)
    out["_payload"] = _original_payload(input_data)
    return out
