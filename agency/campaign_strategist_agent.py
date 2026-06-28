"""campaign_strategist_agent — self-reliant strategist (Python REQUIRED).

WHY THIS MODULE EXISTS (and is not pure YAML): the strategist is the
self-reliant hub of the operation — it pulls its own planning context and
enforces the spend/approval floor.

  @pre_compose load_planning_context — pull the strategist's OWN context
      from the dev store (in prod: connectors): the inbound brief, audience
      segments, past-campaign performance + channel history, competitor
      signals, and the brand's max-unapproved-spend ceiling. The LLM plans
      over real strategy, not a spoon-fed blob.

  @compose per-peer payloads — market_intelligence_agent needs the
      target_market + competitor seed; the creative pair (copywriter,
      visual_briefer) need the strategy bundle + channel mix; brand_guardian
      needs the brief identity. Each downstream gets the payload IT needs.

  @chain enforce_spend_floor — a DETERMINISTIC threshold the LLM cannot
      waive: when total planned budget exceeds the brand's
      max_unapproved_spend ceiling, force requires_cmo_escalation=true. The
      LLM proposes; the floor decides whether the CMO must see it.

Brief normalisation + strategy narrative still live in the YAML prompt;
the context-pull, payload-shaping, and spend floor live here.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from leafmesh import LeafMeshLogger, chain, compose, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "campaign_id": "",
    "strategy_summary": "",
    "kpis": [],
    "channel_mix": [],
    "budget_allocation": [],
    "timeline_weeks": 0,
    "requires_legal_review": False,
    "brief_source": "",
    "product_or_topic": "",
    "target_market": "",
    "objectives": [],
    "budget_cents": 0,
    "received_at_utc": "",
    "needs_market_intelligence": False,
    "requires_cmo_escalation": False,
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


def _pick(input_data: dict[str, Any], key: str, default: Any = None) -> Any:
    if not isinstance(input_data, dict):
        return default
    if input_data.get(key) not in (None, ""):
        return input_data[key]
    payload = input_data.get("payload")
    if isinstance(payload, dict) and payload.get(key) not in (None, ""):
        return payload[key]
    uy = input_data.get("upstream_yields")
    if isinstance(uy, dict):
        if uy.get(key) not in (None, ""):
            return uy[key]
        for v in uy.values():
            if isinstance(v, dict) and v.get(key) not in (None, ""):
                return v[key]
    return default


def _has_market_intel(input_data: dict[str, Any]) -> bool:
    """True when market-intelligence yields are already upstream."""
    for key in ("primary_segments", "persona_scores",
                "competitor_summary", "intel_briefing"):
        if _pick(input_data, key, None) not in (None, "", []):
            return True
    return False


# ── @pre_compose: the strategist pulls its OWN planning context ──────────
def load_planning_context(data: Any, ctx: dict) -> dict[str, Any]:
    input_data = data if isinstance(data, dict) else {}
    campaign_id = _pick(input_data, "campaign_id", "")

    # The brief: payload first; else the seeded dev brief so the demo runs.
    brief = {
        "campaign_id": campaign_id,
        "brief_source": _pick(input_data, "brief_source", ""),
        "product_or_topic": _pick(input_data, "product_or_topic", ""),
        "target_market": _pick(input_data, "target_market", ""),
        "objectives": _pick(input_data, "objectives", []),
        "budget_cents": _pick(input_data, "budget_cents", 0),
        "received_at_utc": _pick(input_data, "received_at_utc", ""),
        "raw_request": _pick(input_data, "raw_request", ""),
    }
    thin = not (brief["product_or_topic"] or brief["target_market"]
                or brief["objectives"])
    if thin:
        seed = store.get_brief(campaign_id) if campaign_id else {}
        if not seed:
            seed = store.any_seed_brief()
        if seed:
            for k, v in seed.items():
                if not brief.get(k):
                    brief[k] = v

    market = str(brief.get("target_market") or "")
    return {
        "brief": brief,
        "segments": store.get_segments(market),
        "performance": store.get_performance(market),
        "competitor_signals": store.get_competitor_signals(market),
        "brand_voice": store.get_brand_guidelines().get("voice", ""),
        "max_unapproved_spend_cents": store.max_unapproved_spend_cents(),
        "has_market_intel": _has_market_intel(input_data),
        "human_message": str(input_data.get("human_message") or ""),
    }


# ── @chain: the deterministic spend / approval floor ─────────────────────
def total_budget_cents(budget_allocation: Any, fallback_cents: int = 0) -> int:
    """Pure: sum channel budgets; fall back to the brief budget."""
    total = 0
    if isinstance(budget_allocation, list):
        for b in budget_allocation:
            if isinstance(b, dict):
                try:
                    total += int(b.get("budget_cents") or 0)
                except (TypeError, ValueError):
                    pass
    if total == 0:
        try:
            total = int(fallback_cents or 0)
        except (TypeError, ValueError):
            total = 0
    return total


async def enforce_spend_floor(result: dict, ctx: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}
    ceiling = int(result.pop("_max_unapproved_spend_cents", 0)
                  or store.max_unapproved_spend_cents())
    total = total_budget_cents(result.get("budget_allocation"),
                               result.get("budget_cents", 0))
    result["requires_cmo_escalation"] = total > ceiling
    logger.info(
        f"[strategist] spend floor — total=${total/100:.0f} "
        f"ceiling=${ceiling/100:.0f} cmo_escalation={result['requires_cmo_escalation']}"
    )
    return result


# ── @compose: each downstream gets the payload IT needs ──────────────────
def _to_market_intelligence(result: dict, ctx: dict) -> dict[str, Any]:
    return {
        "campaign_id": result.get("campaign_id", ""),
        "target_market": result.get("target_market", ""),
        "product_or_topic": result.get("product_or_topic", ""),
        "objectives": result.get("objectives", []),
    }


def _to_creative(result: dict, ctx: dict) -> dict[str, Any]:
    return {
        "campaign_id": result.get("campaign_id", ""),
        "strategy_summary": result.get("strategy_summary", ""),
        "channel_mix": result.get("channel_mix", []),
        "target_market": result.get("target_market", ""),
        "product_or_topic": result.get("product_or_topic", ""),
        "requires_legal_review": result.get("requires_legal_review", False),
    }


@pre_compose(context_processor=load_planning_context)
@compose(
    market_intelligence_agent=_to_market_intelligence,
    copywriter_agent=_to_creative,
    visual_briefer_agent=_to_creative,
)
@chain(enforce_spend_floor)
async def campaign_strategist_agent(llm_response, input_data: dict, context: dict) -> dict[str, Any]:
    """Surface the LLM strategy; carry the spend ceiling to the floor."""
    parsed = _parse_json(llm_response)
    input_data = input_data if isinstance(input_data, dict) else {}

    out = {**_DEFAULTS}
    for k in _DEFAULTS:
        if k in parsed and parsed[k] not in (None, ""):
            out[k] = parsed[k]

    if not out["campaign_id"]:
        out["campaign_id"] = (_pick(input_data, "campaign_id", "")
                              or f"camp-{uuid.uuid4().hex[:10]}")

    # Carry the brand spend ceiling forward to the @chain floor.
    out["_max_unapproved_spend_cents"] = store.max_unapproved_spend_cents()

    logger.info(
        f"[strategist] campaign={out['campaign_id']} "
        f"needs_intel={out['needs_market_intelligence']} "
        f"legal_review={out['requires_legal_review']}"
    )
    return out
