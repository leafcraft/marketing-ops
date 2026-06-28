"""compliance_reviewer_agent — brand/compliance floor + pre-gate stash.

WHY THIS MODULE EXISTS (and is not pure YAML): two jobs the LLM must not
be able to waive, plus the HITL bridge.

  @pre_compose load_brand_rules — pull the brand guidelines + the
      banned-claim / legal-trigger lexicon from the dev store (in prod: a
      connector to the brand wiki / DAM) so the review runs against the
      org's ACTUAL rules, not the model's memory.

  @chain enforce_compliance_floor — a DETERMINISTIC scan the LLM cannot
      override. It reads the actual copy variants (carried forward by the
      agent body), scans them against the banned-claim list (any hit →
      approved_for_publish forced FALSE) and the legal-trigger list /
      regulated industries (any hit → requires_legal_review forced TRUE).
      The LLM may RAISE a flag; it can never LOWER one below this floor.
      THEN it stashes the reviewed campaign context keyed by session so
      the fail-closed publisher (and the audit sink) can recover exactly
      what was approved after the human gate — the SDK resumes that chain
      with only human-response meta fields, not the in-flight payload.

Narrative judgment (briefing wording, score nuance) still lives in the
YAML prompt; the hard gate lives here.
"""
from __future__ import annotations

import json
from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import store
from agency._shared.session_stash import resolve_session_id, stash_put

logger = LeafMeshLogger(__name__)


def _find(input_data: dict[str, Any], key: str) -> Any:
    """Upstream lookup: flat input, then upstream_yields (flat or keyed
    by agent name)."""
    if not isinstance(input_data, dict):
        return None
    if input_data.get(key) not in (None, ""):
        return input_data[key]
    uy = input_data.get("upstream_yields")
    if isinstance(uy, dict):
        if uy.get(key) not in (None, ""):
            return uy[key]
        for v in uy.values():
            if isinstance(v, dict) and v.get(key) not in (None, ""):
                return v[key]
    return None


def _all_copy_text(variants_by_channel: Any) -> str:
    """Flatten every copy variant string into one lowercase blob to scan."""
    out: list[str] = []
    if isinstance(variants_by_channel, list):
        for entry in variants_by_channel:
            if isinstance(entry, str):
                out.append(entry)
                continue
            if not isinstance(entry, dict):
                continue
            vs = entry.get("variants") or entry.get("copy") or []
            if isinstance(vs, list):
                for v in vs:
                    if isinstance(v, str):
                        out.append(v)
                    elif isinstance(v, dict):
                        out.append(" ".join(str(x) for x in v.values()))
            elif isinstance(vs, str):
                out.append(vs)
    return " ".join(out).lower()


def scan_compliance(variants_by_channel: Any, target_market: str,
                    product_or_topic: str,
                    brand_id: str = "leafmesh-default") -> dict[str, Any]:
    """Pure deterministic scan — the testable core of the floor.

    Returns banned-claim hits (block publish) and legal-trigger / regulated
    hits (force legal review). No I/O beyond the seeded brand lexicon.
    """
    banned = [t.lower() for t in store.banned_claims(brand_id)]
    legal_terms = [t.lower() for t in store.legal_trigger_terms(brand_id)]
    regulated = [t.lower() for t in store.regulated_industries(brand_id)]

    copy_blob = _all_copy_text(variants_by_channel)
    haystack = " ".join([copy_blob, str(target_market or "").lower(),
                         str(product_or_topic or "").lower()])

    banned_hits = sorted({t for t in banned if t and t in copy_blob})
    legal_hits = sorted({t for t in legal_terms if t and t in haystack})
    regulated_hits = sorted({t for t in regulated if t and t in haystack})
    return {
        "banned_hits": banned_hits,
        "legal_hits": sorted(set(legal_hits + regulated_hits)),
    }


# ── @pre_compose: pull the org's brand rules into review context ─────────
def load_brand_rules(data: Any, ctx: dict) -> dict[str, Any]:
    g = store.get_brand_guidelines()
    return {
        "banned_claims": store.banned_claims(),
        "legal_trigger_terms": store.legal_trigger_terms(),
        "regulated_industries": store.regulated_industries(),
        "brand_voice": g.get("voice", ""),
        "tone_rules": g.get("tone_rules", []),
        "reading_grade_target": g.get("reading_grade_target", 8),
    }


# ── @chain: the deterministic compliance floor + pre-gate stash ──────────
async def enforce_compliance_floor(result: dict, ctx: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}

    # The agent body carries the campaign payload forward under a private
    # key so the floor reads it deterministically (proven pattern: the
    # chain reads `result`, not an unguaranteed ctx shape).
    carried = result.pop("_compliance_ctx", {}) or {}
    variants = carried.get("variants_by_channel")

    scan = scan_compliance(variants, carried.get("target_market", ""),
                           carried.get("product_or_topic", ""))
    banned_hits, legal_hits = scan["banned_hits"], scan["legal_hits"]

    # FLOOR 1 — banned claims block publish, no matter what the LLM said.
    if banned_hits:
        result["approved_for_publish"] = False
        existing = list(result.get("flagged_claims") or [])
        for term in banned_hits:
            existing.append({"claim": term, "channel": "*",
                             "risk_level": "critical",
                             "reason": "banned brand claim"})
        result["flagged_claims"] = existing

    # FLOOR 2 — legal-trigger terms / regulated industry force legal review.
    if legal_hits:
        result["requires_legal_review"] = True

    # FLOOR 3 — default-deny is an AND of every gate. The LLM cannot set
    # approved_for_publish true while any blocker stands.
    try:
        score = float(result.get("brand_safety_score"))
    except (TypeError, ValueError):
        score = 0.0
    if (result.get("flagged_claims") or result.get("protected_attribute_risk")
            or score < 0.6):
        result["approved_for_publish"] = False

    # Stash the reviewed campaign context keyed by session — the bridge
    # across the human gate for the fail-closed publisher + audit sink.
    session_id = (carried.get("session_id")
                  or resolve_session_id(ctx if isinstance(ctx, dict) else {}, {}))
    stash_put(session_id, {
        "campaign_id": str(result.get("campaign_id")
                           or carried.get("campaign_id") or ""),
        "strategy_summary": str(result.get("strategy_summary")
                                or carried.get("strategy_summary") or ""),
        "channel_mix": list(carried.get("channel_mix") or []),
        "budget_allocation": list(carried.get("budget_allocation") or []),
        "variants_by_channel": list(variants or []),
        "flagged_claims": list(result.get("flagged_claims") or []),
        "required_disclaimers": list(result.get("required_disclaimers") or []),
        "approved_for_publish": bool(result.get("approved_for_publish")),
    })
    logger.info(
        f"[compliance] floor — banned={banned_hits} legal={legal_hits} "
        f"approved={result.get('approved_for_publish')} "
        f"legal_review={result.get('requires_legal_review')} "
        f"(session={session_id or '?'})"
    )
    return result


@pre_compose(context_processor=load_brand_rules)
@chain(enforce_compliance_floor)
async def compliance_reviewer_agent(
    llm_response: dict[str, Any] | str | None,
    input_data: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """Surface the LLM verdict; carry the campaign payload forward for the
    floor; enforce_compliance_floor enforces the deterministic gate +
    stashes the reviewed context."""
    if isinstance(llm_response, str):
        try:
            llm_response = json.loads(llm_response)
        except (ValueError, TypeError):
            llm_response = {}
    if not isinstance(llm_response, dict):
        llm_response = {}
    input_data = input_data if isinstance(input_data, dict) else {}
    context = context if isinstance(context, dict) else {}

    # Carry the campaign payload to the @chain floor (popped there before
    # yields are emitted — never a declared yield key).
    llm_response["_compliance_ctx"] = {
        "variants_by_channel": _find(input_data, "variants_by_channel"),
        "channel_mix": _find(input_data, "channel_mix"),
        "budget_allocation": _find(input_data, "budget_allocation"),
        "target_market": _find(input_data, "target_market"),
        "product_or_topic": _find(input_data, "product_or_topic"),
        "campaign_id": _find(input_data, "campaign_id"),
        "strategy_summary": _find(input_data, "strategy_summary"),
        "session_id": resolve_session_id(input_data, context),
    }
    return llm_response
