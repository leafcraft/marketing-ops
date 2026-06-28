"""marketing_audit_logger_agent — hash-chained WORM audit terminus.

Writes one immutable record per campaign-cycle terminus to
./logs/marketing_audit.jsonl. Each record carries campaign_id +
upstream yields + any human decision meta and is SHA-256 chained to
the prior line, so post-hoc audit can detect any insertion/deletion
and replay any campaign deterministically. Self-contained (programmatic
agent with its own top-level module) — it does not depend on the
legacy agency/_shared/audit_logger.py sink.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger

from agency._shared.session_stash import resolve_session_id, stash_get

logger = LeafMeshLogger(__name__)

AUDIT_PATH = Path("./logs/marketing_audit.jsonl")


def _up(input_data: dict[str, Any], context: dict[str, Any],
        key: str, default: Any = None) -> Any:
    """Shape-tolerant upstream read: flat input_data → upstream_yields
    (flat or keyed by agent name) → context['upstream']."""
    if key in input_data and input_data[key] not in (None, ""):
        return input_data[key]
    uy = input_data.get("upstream_yields")
    if isinstance(uy, dict):
        if key in uy and uy[key] not in (None, ""):
            return uy[key]
        for v in uy.values():
            if isinstance(v, dict) and v.get(key) not in (None, ""):
                return v[key]
    for container_key in ("upstream_results",):
        ur = input_data.get(container_key)
        if isinstance(ur, dict):
            for v in ur.values():
                if isinstance(v, dict) and v.get(key) not in (None, ""):
                    return v[key]
    cu = context.get("upstream") if isinstance(context, dict) else None
    if isinstance(cu, dict) and cu.get(key) not in (None, ""):
        return cu[key]
    return default


def _last_hash(path: Path) -> str:
    """Hash of last written line — the chain link."""
    if not path.exists() or path.stat().st_size == 0:
        return "GENESIS"
    last = b""
    with path.open("rb") as fp:
        for line in fp:
            if line.strip():
                last = line
    if not last:
        return "GENESIS"
    return hashlib.sha256(last).hexdigest()


async def marketing_audit_logger_agent(
    llm_response: dict[str, Any] | str | None,
    input_data: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

    record_id = f"aud-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    upstream = input_data.get("upstream_yields") or {}
    # Post-HITL ('hold') resumes deliver only the human meta fields —
    # recover the campaign identity from the session stash so the
    # audit line still says WHICH campaign got held. FAIL-SOFT: the
    # record is written either way.
    session_id = resolve_session_id(input_data, context)
    campaign_id = str(_up(input_data, context, "campaign_id", "")
                      or stash_get(session_id).get("campaign_id") or "")

    record = {
        "record_id": record_id,
        "campaign_id": campaign_id,
        "written_at_utc": now,
        "previous_hash": _last_hash(AUDIT_PATH),
        "upstream": upstream,
        # Human decision meta — present when a HITL gate routed here
        "human_decision": str(input_data.get("human_decision") or ""),
        "human_message": str(input_data.get("human_message") or ""),
    }
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    record_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()

    with AUDIT_PATH.open("ab") as fp:
        fp.write(line.encode("utf-8") + b"\n")

    logger.info(
        f"[audit] wrote {record_id} hash={record_hash[:12]} "
        f"prev={record['previous_hash'][:12]}"
    )
    return {
        "audit_record_id": record_id,
        "audit_hash": record_hash,
        "written_at_utc": now,
    }
