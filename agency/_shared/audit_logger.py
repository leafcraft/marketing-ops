"""Hash-chained WORM audit sink for the marketing-ops pod.

`marketing_audit_logger_agent` in the configuration is `agent_type: external`
with `framework: custom`. SDK 2.4+ executes custom external agents via an
*intelligence function* registered on the LeafMesh instance:

    from agency._shared import audit_logger
    leafmesh = LeafMesh.from_store()
    audit_logger.register(leafmesh, "marketing_audit_logger_agent")  # main.py, after from_store, before start

Dev mode writes hash-chained JSON lines to ./logs/marketing_audit.jsonl.
Production swaps `_dispatch_local` for S3 Object Lock / Datadog / Splunk HEC.

Hash-chain invariant: each entry embeds the SHA-256 of the prior entry's body,
so any insertion or deletion is detectable post-hoc. This sink is the TERMINUS
for every outcome that matters — a published campaign, an approval, a triage
outcome, AND every gate a reviewer HELD: a held campaign is recorded, never
silently dropped. (A review nobody answers is not written here on leafmesh
2.4.486: its Inbox card closes, the ticket notes it, and main.py logs the
HUMAN_INPUT_TIMEOUT event.)
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger

logger = LeafMeshLogger(__name__)
_CHAIN_LOCK = threading.Lock()
_LAST_HASH = "GENESIS"

DEFAULT_AUDIT_PATH = "./logs/marketing_audit.jsonl"

_META_KEYS = frozenset({
    "session_id", "sessionId", "payload",
    "human_initiated", "original_webhook_data",
})


def _sha256_hex(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(body).hexdigest()


def _dispatch_local(path_str: str, entry: dict[str, Any]) -> None:
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")


def write_audit_entry(input_data: dict[str, Any],
                      config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append one hash-chained entry. Returns the audit yields."""
    global _LAST_HASH
    input_data = input_data if isinstance(input_data, dict) else {}
    cfg = config or {}
    sink_type = cfg.get("sink_type", "local_file")
    path_str = cfg.get("local_file_path", DEFAULT_AUDIT_PATH)

    payload = input_data.get("payload")
    if not isinstance(payload, dict) or not payload:
        payload = {k: v for k, v in input_data.items() if k not in _META_KEYS}

    with _CHAIN_LOCK:
        prev_hash = _LAST_HASH
        entry = {
            "audit_event_id": f"audit-{uuid.uuid4().hex[:12]}",
            "written_at_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": str(input_data.get("session_id", "")),
            "payload": payload,
            "hash_chain_prev": prev_hash,
        }
        entry["hash_chain_current"] = _sha256_hex(
            {k: v for k, v in entry.items() if k != "hash_chain_current"}
        )
        _LAST_HASH = entry["hash_chain_current"]
        _dispatch_local(path_str, entry)

    logger.info(f"[audit] {entry['audit_event_id']} chain={entry['hash_chain_current'][:8]}…")
    return entry


def register(mesh: Any, agent_name: str = "marketing_audit_logger_agent") -> bool:
    """Register the audit intelligence function on a LeafMesh instance.

    SDK 2.4+: custom external agents execute through
    `mesh.intelligence("<agent_name>")`. Call AFTER `from_store()`, before `start()`.
    """
    if not callable(getattr(mesh, "intelligence", None)):
        logger.warning("[audit] mesh has no .intelligence() — audit sink NOT registered")
        return False

    async def marketing_audit_logger_agent(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Signature-tolerant: the SDK may pass (input_data) or
        # (llm_response, input_data, context) or kwargs.
        input_data: dict[str, Any] = {}
        if isinstance(kwargs.get("input_data"), dict):
            input_data = kwargs["input_data"]
        elif len(args) >= 2 and isinstance(args[1], dict):
            input_data = args[1]
        else:
            input_data = next((a for a in args if isinstance(a, dict)), {})
        return write_audit_entry(input_data)

    mesh.intelligence(agent_name)(marketing_audit_logger_agent)
    logger.info("[audit] hash-chained WORM sink registered via mesh.intelligence()")
    return True
