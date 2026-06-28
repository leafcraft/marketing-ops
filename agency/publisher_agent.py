"""publisher_agent — multi-channel publish actuator (Python REQUIRED).

WHY THIS MODULE EXISTS (and is not YAML): publishing is an outward,
PAID action sitting behind a human approval gate. When the human
approves in the inbox, the SDK resumes the chain with ONLY the
human-response meta fields — the approved campaign payload is NOT
re-delivered. This actuator therefore reads the approved campaign
context EXCLUSIVELY from the pre-gate session stash written by
compliance_reviewer_agent — never from LLM context, because an
LLM-echoed channel list could put unreviewed copy live — and it
FAILS CLOSED: when no approved channel mix is recoverable for the
session, nothing goes live.

Production: swap the stub dispatch for Meta Marketing API, IG Graph
API, LinkedIn Marketing API, and SendGrid adapters.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from leafmesh import LeafMeshLogger

from agency._shared.session_stash import resolve_session_id, stash_get

logger = LeafMeshLogger(__name__)


async def publisher_agent(
    llm_response: dict[str, Any] | str | None,
    input_data: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    # The approved campaign payload comes from the pre-gate stash ONLY.
    session_id = resolve_session_id(input_data, context)
    stashed = stash_get(session_id)
    campaign_id = str(stashed.get("campaign_id") or "")
    channel_mix = stashed.get("channel_mix") or []
    budgets = stashed.get("budget_allocation") or []

    channels = [
        str(c["channel"]) for c in channel_mix
        if isinstance(c, dict) and c.get("channel")
    ]

    if not channels:
        # FAIL-CLOSED: publishing is outward and spends budget. With no
        # approved channel mix stashed for this session we refuse —
        # going live on a default channel set would be an unreviewed
        # publish, not a fallback.
        logger.error(
            f"[publisher] REFUSING to publish — no approved channel mix "
            f"stashed (session={session_id or '?'}, "
            f"campaign={campaign_id or '?'})."
        )
        return {
            "published_channels": [],
            "total_spend_cents": 0,
            "live_variant_ids": [],
            "published_at_utc": "",
            "tracking_pixel_set": False,
            "campaign_id": campaign_id,
            "error": "no approved campaign channel mix stashed for this "
                     "session — compliance_reviewer must run before publish",
        }

    total_spend = 0
    for b in budgets:
        if isinstance(b, dict):
            try:
                total_spend += int(b.get("budget_cents") or 0)
            except (TypeError, ValueError):
                pass

    variant_ids = [f"var-{uuid.uuid4().hex[:8]}" for _ in channels]

    logger.info(
        f"[publisher] channels={channels} spend=${total_spend / 100:.0f} "
        f"variants={len(variant_ids)}"
    )
    return {
        "published_channels": channels,
        "total_spend_cents": total_spend,
        "live_variant_ids": variant_ids,
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
        "tracking_pixel_set": True,
        "campaign_id": campaign_id,
        "error": "",
    }
