"""market_intelligence_agent — self-reliant analyst (Python REQUIRED).

WHY THIS MODULE EXISTS (and is not pure YAML):

  @pre_compose load_market_data — the analyst pulls its OWN context: the
      audience/segment data from the CDP, past-campaign performance, and
      competitor signals from the competitive-intel platform (all from the
      dev store day-0; connectors in prod). The LLM analyses real seed data
      instead of inventing it.

  @chain enforce_threat_floor — a DETERMINISTIC escalation floor: any
      competitor signal seeded/declared at threat_level high|critical|severe
      is force-merged into threat_alerts so the crisis fast-path to
      brand_guardian fires even if the LLM under-reports. The LLM may add
      threats; it can never DROP a high-threat competitor below the floor.

All segmentation/competitor narrative still lives in the YAML prompt.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "primary_segments": [],
    "persona_scores": [],
    "estimated_reach": 0,
    "exclusion_signals": [],
    "frequency_cap_recommendation": 0,
    "competitor_summary": [],
    "market_share_signals": "",
    "whitespace_opportunities": [],
    "threat_alerts": [],
    "intel_briefing": "",
}

_HIGH_THREAT = {"high", "critical", "severe"}


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
    uy = input_data.get("upstream_yields")
    if isinstance(uy, dict):
        if uy.get(key) not in (None, ""):
            return uy[key]
        for v in uy.values():
            if isinstance(v, dict) and v.get(key) not in (None, ""):
                return v[key]
    return default


# ── @pre_compose: the analyst pulls its OWN market data ──────────────────
def load_market_data(data: Any, ctx: dict) -> dict[str, Any]:
    input_data = data if isinstance(data, dict) else {}
    market = str(_pick(input_data, "target_market", "") or "")
    return {
        "target_market": market,
        "segment_data": store.get_segments(market),
        "performance": store.get_performance(market),
        "competitor_signals": store.get_competitor_signals(market),
    }


def high_threat_competitors(competitor_signals: Any) -> list[dict[str, Any]]:
    """Pure: competitors at high/critical/severe threat — the floor set."""
    out: list[dict[str, Any]] = []
    if isinstance(competitor_signals, list):
        for c in competitor_signals:
            if (isinstance(c, dict)
                    and str(c.get("threat_level", "")).lower() in _HIGH_THREAT):
                out.append(c)
    return out


# ── @chain: deterministic threat-escalation floor ────────────────────────
async def enforce_threat_floor(result: dict, ctx: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}
    seeds = result.pop("_competitor_signals", []) or []
    floor = high_threat_competitors(seeds)

    alerts = list(result.get("threat_alerts") or [])
    known = {json.dumps(a, sort_keys=True, default=str) for a in alerts
             if isinstance(a, (dict, str))}
    for c in floor:
        name = c.get("name", "")
        alert = {"competitor": name, "threat_level": c.get("threat_level", ""),
                 "signal": c.get("recent_move", "")}
        if json.dumps(alert, sort_keys=True) not in known:
            alerts.append(alert)
    result["threat_alerts"] = alerts
    logger.info(
        f"[market_intel] threat floor — {len(floor)} high-threat seeded, "
        f"{len(alerts)} total alerts"
    )
    return result


@pre_compose(context_processor=load_market_data)
@chain(enforce_threat_floor)
async def market_intelligence_agent(llm_response, input_data: dict, context: dict) -> dict[str, Any]:
    """Surface the analyst's read; carry competitor seeds to the floor."""
    parsed = _parse_json(llm_response)
    input_data = input_data if isinstance(input_data, dict) else {}

    out = {**_DEFAULTS}
    for k in _DEFAULTS:
        if k in parsed and parsed[k] not in (None, ""):
            out[k] = parsed[k]

    # Carry the seeded competitor signals to the @chain threat floor.
    market = str(_pick(input_data, "target_market", "") or "")
    out["_competitor_signals"] = store.get_competitor_signals(market)
    return out
