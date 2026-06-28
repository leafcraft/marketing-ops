"""copywriter_agent — self-reliant copywriter (Python REQUIRED).

WHY THIS MODULE EXISTS (and is not pure YAML):

  @pre_compose load_brand_voice — the copywriter pulls its OWN context: the
      brand voice + tone rules + reading-grade target AND the banned-claim
      lexicon, so it drafts IN-VOICE and steers clear of terms the
      compliance floor would block downstream (dev store day-0; brand-wiki
      connector in prod).

  @chain flag_banned_in_copy — a DETERMINISTIC self-check: scan the drafted
      copy against the banned-claim list and force has_protected_claims=true
      when any slip through, so the creative pair never hands the compliance
      gate copy that silently claims it is clean.

Tone/variant drafting still lives in the YAML prompt.
"""
from __future__ import annotations

import json
import re
from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import store

logger = LeafMeshLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "variants_by_channel": [],
    "tone_used": "",
    "reading_grade": 0,
    "has_protected_claims": False,
    "copy_briefing": "",
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


def _copy_blob(variants_by_channel: Any) -> str:
    out: list[str] = []
    if isinstance(variants_by_channel, list):
        for entry in variants_by_channel:
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict):
                vs = entry.get("variants") or entry.get("copy") or []
                if isinstance(vs, list):
                    for v in vs:
                        out.append(v if isinstance(v, str)
                                   else " ".join(str(x) for x in v.values())
                                   if isinstance(v, dict) else str(v))
                elif isinstance(vs, str):
                    out.append(vs)
    return " ".join(out).lower()


# ── @pre_compose: pull brand voice + the banned-claim lexicon ────────────
def load_brand_voice(data: Any, ctx: dict) -> dict[str, Any]:
    g = store.get_brand_guidelines()
    return {
        "brand_voice": g.get("voice", ""),
        "tone_rules": g.get("tone_rules", []),
        "reading_grade_target": g.get("reading_grade_target", 8),
        "banned_claims": store.banned_claims(),
    }


# ── @chain: deterministic banned-term self-check ─────────────────────────
async def flag_banned_in_copy(result: dict, ctx: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}
    blob = _copy_blob(result.get("variants_by_channel"))
    hits = sorted({t for t in (b.lower() for b in store.banned_claims())
                   if t and t in blob})
    if hits:
        result["has_protected_claims"] = True
        logger.info(f"[copywriter] banned-term self-check flagged: {hits}")
    return result


@pre_compose(context_processor=load_brand_voice)
@chain(flag_banned_in_copy)
async def copywriter_agent(llm_response, input_data: dict, context: dict) -> dict[str, Any]:
    """Surface the drafted copy; the chain self-checks for banned terms."""
    parsed = _parse_json(llm_response)
    out = {**_DEFAULTS}
    for k in _DEFAULTS:
        if k in parsed and parsed[k] not in (None, ""):
            out[k] = parsed[k]
    return out
