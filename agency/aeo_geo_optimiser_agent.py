"""aeo_geo_optimiser_agent — deterministic recombination floor (Python REQUIRED).

WHY THIS MODULE EXISTS (and is not pure YAML): this agent runs as PARALLEL
COPIES (config: `scaling: {copies: {mode: fixed, count: 3, handoff: last}}`). One activation
fans into three copies; each claims a DISJOINT batch of pages via the atomic
`claim_audit_batch` tool and scores them. `copies.handoff: last` then COMBINES
the copies deterministically — lists concatenate, NUMBERS SUM. Summing is right
for `total_pages` and `needs_rewrite_count`, but WRONG for a ratio: three copies
each reporting `average_score: 0.6` would combine to `1.8`, and the three
per-copy `high_priority_rewrites` top-10 lists would concatenate to up to 30.

  @chain reshape_combined — a DETERMINISTIC recombination floor that runs ONCE on
      the combined result (it also receives the per-copy `_instances` pool). It
      recomputes every aggregate from the concatenated `scored_pages` so the
      chain never routes a summed average or an over-long rewrite list:
        * average_score  = MEAN aeo_score across all scored pages (2 dp)
        * total_pages    = count of scored pages
        * needs_rewrite  = pages with aeo_score < 0.5
        * high_priority_rewrites = the 10 lowest-scoring pages needing a rewrite,
                                   worst first (re-trimmed, not concatenated)
        * requires_content_team_review = needs_rewrite_count > 0

The floor is idempotent: on a single-copy run it recomputes the agent's own
numbers unchanged. All scoring narrative lives in the YAML prompt.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain

logger = LeafMeshLogger(__name__)

_REWRITE_THRESHOLD = 0.5
_TOP_N = 10

_DEFAULTS: dict[str, Any] = {
    "scored_pages": [],
    "total_pages": 0,
    "average_score": 0,
    "needs_rewrite_count": 0,
    "high_priority_rewrites": [],
    "requires_content_team_review": False,
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


def _score(page: Any) -> float:
    """A page's aeo_score as a float, clamped 0..1; unreadable => 0.0."""
    if not isinstance(page, dict):
        return 0.0
    try:
        val = float(page.get("aeo_score") or 0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, val))


# ── @chain: deterministic recombination floor (runs once on combined result) ──
async def reshape_combined(result: Any, ctx: Any) -> dict[str, Any]:
    """Recompute every aggregate from the concatenated scored_pages so a summed
    average or an over-concatenated rewrite list never routes downstream."""
    result = result if isinstance(result, dict) else {}
    # Drop the per-copy pool if present — it is detail, not a routed field.
    result.pop("_instances", None)

    scored = [p for p in (result.get("scored_pages") or []) if isinstance(p, dict)]
    total = len(scored)
    avg = round(sum(_score(p) for p in scored) / total, 2) if total else 0

    needs = sorted((p for p in scored if _score(p) < _REWRITE_THRESHOLD),
                   key=_score)  # worst first

    result["scored_pages"] = scored
    result["total_pages"] = total
    result["average_score"] = avg
    result["needs_rewrite_count"] = len(needs)
    result["high_priority_rewrites"] = needs[:_TOP_N]
    result["requires_content_team_review"] = len(needs) > 0
    logger.info(
        f"[aeo_geo] reshape — {total} pages scored, avg={avg}, "
        f"{len(needs)} need rewrite (top {min(len(needs), _TOP_N)} routed)"
    )
    return result


@chain(reshape_combined)
async def aeo_geo_optimiser_agent(llm_response, input_data: dict, context: dict) -> dict[str, Any]:
    """Surface this copy's page scores; the @chain floor recombines the
    parallel copies deterministically (mean, not sum, for the average)."""
    parsed = _parse_json(llm_response)
    out = {**_DEFAULTS}
    for k in _DEFAULTS:
        if k in parsed and parsed[k] not in (None, ""):
            out[k] = parsed[k]
    # Normalise scored_pages to a list of dicts before the floor recomputes.
    out["scored_pages"] = [p for p in (out.get("scored_pages") or [])
                           if isinstance(p, dict)]
    return out
