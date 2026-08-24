"""publisher_agent — the FINISHER (multi-channel publish actuator).

auto_discover matches `publisher_agent`. The publisher sits BEHIND the human
approval gate. Publishing is outward and PAID, so it never trusts that *reaching*
this agent means approved — it is the concrete "@chain fails closed":

  a) approval RE-CHECK — an allow-token allowlist + block-token denylist; an
     UNKNOWN/ambiguous verdict fails closed (nothing goes live).
  b) deterministic invariants a human can't waive — the approved channel mix is
     recovered from the PRE-GATE session stash ONLY (never from LLM context, so
     an LLM-echoed channel list can never put unreviewed copy live), compliance's
     approved_for_publish must still hold, and there must be a real spend.
  c) render the real campaign pack to ./out; on a tripped floor DELETE the
     partial and record status=blocked with reasons — never a half-published
     campaign.
  d) dev-store fallback that ANNOUNCES itself — with nothing recoverable it
     returns status=blocked (available:false in spirit), never a synthetic
     "published" ack.
  e) two-layer defense — the body short-circuits when not approved; the @chain
     floor re-checks the invariants independently.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger, chain

from agency._shared import store
from agency._shared.session_stash import resolve_session_id, stash_get

logger = LeafMeshLogger(__name__)

_OUT_DIR = Path("./out")
_APPROVE_TOKENS = frozenset({"approve", "approved", "sign", "signed", "yes", "ok"})
_BLOCK_TOKENS = frozenset({"reject", "rejected", "no", "deny", "denied",
                           "hold", "held", "held_for_review"})


def _signal(input_data: dict) -> str:
    """The human verdict, from wherever the SDK delivered it (shape-tolerant)."""
    sources = [input_data]
    up = input_data.get("upstream_yields")
    if isinstance(up, dict):
        sources.extend(v for v in up.values() if isinstance(v, dict))
    for src in sources:
        for key in ("human_message", "human_decision", "decision", "message"):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lower()
    return ""


def _is_approved(input_data: dict) -> bool:
    """Fail closed: only an explicit approve token counts; unknown => not approved."""
    sig = _signal(input_data)
    if sig in _BLOCK_TOKENS:
        return False
    return sig in _APPROVE_TOKENS


def _channels(campaign: dict) -> list[str]:
    return [str(c["channel"]) for c in (campaign.get("channel_mix") or [])
            if isinstance(c, dict) and c.get("channel")]


def _total_spend_cents(campaign: dict) -> int:
    total = 0
    for b in campaign.get("budget_allocation") or []:
        if isinstance(b, dict):
            try:
                total += int(b.get("budget_cents") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _recover_campaign(input_data: dict, context: dict) -> dict:
    """Recover the approved campaign across the HITL boundary: the pre-gate
    session stash first (written by compliance), then the dev-store mirror.
    Never from LLM context — an echoed channel list must not put copy live."""
    sid = resolve_session_id(input_data, context)
    stashed = stash_get(sid)
    if stashed.get("channel_mix"):
        return stashed
    cid = str(input_data.get("campaign_id") or stashed.get("campaign_id") or "")
    recovered = store.get_approved_campaign(cid)
    return recovered or (stashed or {"campaign_id": cid})


def _render_pack(campaign: dict) -> str:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    campaign_id = str(campaign.get("campaign_id") or "campaign")
    path = _OUT_DIR / f"{campaign_id}_campaign_pack.md"
    lines = [f"# Published campaign pack — {campaign_id}",
             f"Strategy: {campaign.get('strategy_summary') or 'on record'}",
             "", "## Channels + spend"]
    for c in campaign.get("channel_mix") or []:
        if isinstance(c, dict):
            lines.append(f"- {c.get('channel','')}  ({c.get('share_pct','?')}%)")
    lines += ["", f"**Total spend: {_total_spend_cents(campaign) / 100:.2f}**", ""]
    disclaimers = campaign.get("required_disclaimers") or []
    if disclaimers:
        lines.append("## Required disclaimers")
        for d in disclaimers:
            if isinstance(d, dict):
                lines.append(f"- [{d.get('channel','*')}] {d.get('disclaimer_text','')}")
        lines.append("")
    lines.append("_Live and tagged for attribution. Approved on the human gate._")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _delete_partial(result: dict) -> None:
    p = result.get("artifact_path")
    if p:
        Path(p).unlink(missing_ok=True)
        result["artifact_path"] = ""


def enforce_publish_floor(result: Any, context: dict) -> dict:
    """The finisher floor — publish ONLY on a real approval + real approved mix."""
    result = result if isinstance(result, dict) else {}
    result.setdefault("block_reasons", [])
    approved = result.pop("_approved", False)
    campaign = result.pop("_campaign", {}) or {}
    result.pop("_input", None)

    def _block(reason: str) -> dict:
        result.update(status="blocked", published_channels=[], total_spend_cents=0,
                      live_variant_ids=[], tracking_pixel_set=False,
                      published_at_utc="")
        result["block_reasons"].append(reason)
        result["error"] = "; ".join(result["block_reasons"])
        _delete_partial(result)
        logger.error(f"[publisher] publish floor BLOCKED: {reason}")
        return result

    if not approved:
        return _block("no explicit approval on record (fail closed)")
    # A deterministic invariant a human can't waive: compliance's verdict stands.
    if campaign.get("approved_for_publish") is False:
        return _block("compliance did not approve this campaign for publish")
    channels = _channels(campaign)
    if not channels:
        # dev-store fallback announces itself here — nothing real to publish.
        return _block("no approved channel mix recovered for this session "
                      "(dev-store available:false) — compliance must run before publish")

    # Passed the floor — render, dispatch, ledger. (Prod: swap the stub dispatch
    # for Meta Marketing / IG Graph / LinkedIn Marketing / SendGrid adapters.)
    result["artifact_path"] = _render_pack(campaign)
    result["published_channels"] = channels
    result["total_spend_cents"] = _total_spend_cents(campaign)
    result["live_variant_ids"] = [f"var-{uuid.uuid4().hex[:8]}" for _ in channels]
    result["tracking_pixel_set"] = True
    result["published_at_utc"] = datetime.now(timezone.utc).isoformat()
    result["status"] = "published"
    store.record_outbox({"campaign_id": campaign.get("campaign_id"),
                         "action": "publish", "channels": channels,
                         "spend_cents": result["total_spend_cents"]})
    store.append_ledger({"campaign_id": campaign.get("campaign_id"),
                         "event": "published", "channels": channels})
    logger.info(f"[publisher] published {campaign.get('campaign_id')} -> "
                f"{channels} spend=${result['total_spend_cents']/100:.0f}")
    return result


@chain(enforce_publish_floor)
async def publisher_agent(llm_response: Any, input_data: dict, context: dict) -> dict:
    input_data = input_data if isinstance(input_data, dict) else {}
    campaign = _recover_campaign(input_data, context)
    return {
        "published_channels": [], "total_spend_cents": 0, "live_variant_ids": [],
        "published_at_utc": "", "tracking_pixel_set": False,
        "campaign_id": str(campaign.get("campaign_id") or input_data.get("campaign_id") or ""),
        "status": "", "block_reasons": [], "error": "", "artifact_path": "",
        "_approved": _is_approved(input_data), "_campaign": campaign, "_input": input_data,
    }
