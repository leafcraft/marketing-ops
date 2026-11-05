"""Dev-mode store for the marketing-ops context layer.

Lets the FULL campaign chain (brief → intel → strategy → copy + visual →
compliance → publish → analytics) run end-to-end BEFORE any connector is
wired. Everything here is a stand-in for a real system of record:

  * the inbound brief belongs in your intake form / Asana / email;
  * brand guidelines + the banned-claim / legal-trigger lexicon belong in
    your brand wiki / DAM;
  * audience segments + persona data belong in your CDP / analytics;
  * past-campaign performance belongs in GA4 / Amplitude / Looker;
  * competitor signals belong in your competitive-intel platform.

The mesh's `@pre_compose` processors read THIS module in dev so the LLM
roles plan over real-looking context with zero connectors set. In
production, replace these read calls with connector calls — the SHAPE the
rest of the mesh reads stays identical (that is the contract).

Single-process JSON files under ./data/, seeded on first read. Swap for
Redis/Postgres for a multi-replica deployment — the function signatures
are the contract, not the storage.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DIR = Path("./data")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _path(kind: str) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / f"{kind}.json"


def _load(kind: str) -> dict[str, Any]:
    p = _path(kind)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _save(kind: str, data: dict[str, Any]) -> None:
    p = _path(kind)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


# ═══════════════════════════════════════════════════════════════════════
# SEED DATA — a realistic dev fixture so the chain runs day-0
# ═══════════════════════════════════════════════════════════════════════

# Brand guidelines + the deterministic compliance lexicon. The banned /
# legal-trigger terms here are what the compliance_reviewer @chain floor
# scans copy against — the LLM cannot waive a banned term.
_SEED_BRAND_GUIDELINES: dict[str, Any] = {
    "brand_id": "leafmesh-default",
    "voice": "confident, plain-spoken, evidence-led; never hypey",
    "reading_grade_target": 8,
    "approved_colors": ["#0B6E4F", "#14281D", "#F4F1DE"],
    "tone_rules": [
        "Lead with the customer outcome, not the feature.",
        "Quantify claims or drop them.",
        "No fear-based messaging.",
    ],
    # BANNED CLAIMS — superlatives / absolutes the brand never makes.
    # The compliance @chain scans copy for these and BLOCKS approval.
    "banned_claims": [
        "guaranteed", "guarantee", "100%", "risk-free", "no risk",
        "miracle", "cure", "instantly", "best in the world",
        "number one", "#1", "unlimited", "free money", "get rich",
    ],
    # LEGAL-TRIGGER terms — force a legal review (regulated / comparative /
    # superiority claims). The @chain forces requires_legal_review=true.
    "legal_trigger_terms": [
        "fda", "clinically proven", "doctor recommended", "patented",
        "vs ", "versus", "compared to", "outperforms", "beats ",
        "cheaper than", "better than", "roi", "returns", "investment",
        "hipaa", "gdpr", "compliant", "certified",
    ],
    "regulated_industries": ["finance", "health", "healthcare",
                             "insurance", "pharma", "crypto"],
    "max_unapproved_spend_cents": 5_000_000,   # $50K → CMO escalation floor
}

# A realistic inbound brief Priya drops into the intake form. The
# strategist's @pre_compose pulls this when the payload is thin so the
# demo always has something to plan over.
_SEED_BRIEFS: dict[str, Any] = {
    "camp-2026-demo-001": {
        "campaign_id": "camp-2026-demo-001",
        "brief_source": "form",
        "product_or_topic": "Pro Tier 2.0 launch",
        "target_market": "Mid-market SaaS engineering teams",
        "objectives": ["awareness", "demo_signups"],
        "budget_cents": 6_800_000,
        "received_at_utc": "2026-06-20T14:00:00+00:00",
        "raw_request": ("Pro Tier 2.0 — mid-market SaaS engineering teams, "
                        "$68K, goals: awareness + demo signups. Worth a "
                        "comparative angle vs the incumbent."),
    },
    # Under the $50K ceiling, no comparative or regulated claim — the happy
    # path: strategist → creative → compliance → marketing manager → publish.
    "camp-2026-q4-webinar-002": {
        "campaign_id": "camp-2026-q4-webinar-002",
        "brief_source": "asana",
        "product_or_topic": "Platform engineering webinar series (3 sessions)",
        "target_market": "Mid-market SaaS engineering teams",
        "objectives": ["demo_signups"],
        "budget_cents": 1_800_000,
        "received_at_utc": "2026-10-28T09:30:00+00:00",
        "raw_request": "Q4 webinar series, $18K across email + LinkedIn, goal 300 registrants.",
    },
    # Regulated industry (finance) — compliance forces legal review; under
    # the ceiling, so no CMO sign-off.
    "camp-2026-fin-003": {
        "campaign_id": "camp-2026-fin-003",
        "brief_source": "email",
        "product_or_topic": "Spend analytics add-on for finance teams",
        "target_market": "Fintech finance operations teams",
        "objectives": ["pipeline", "demo_signups"],
        "budget_cents": 4_200_000,
        "received_at_utc": "2026-10-30T16:05:00+00:00",
        "raw_request": "Launch the spend analytics add-on to fintech finance ops; "
                       "$42K; LinkedIn + search. Mention the ROI study.",
    },
    # Missing data — no market, no budget, no objectives: the strategist must
    # not invent them (normalise_brief playbook) and the plan stays empty.
    "camp-2026-partner-004": {
        "campaign_id": "camp-2026-partner-004",
        "brief_source": "form",
        "product_or_topic": "Partner co-marketing with a reseller",
        "target_market": "",
        "objectives": [],
        "budget_cents": 0,
        "received_at_utc": "2026-11-01T11:12:00+00:00",
        "raw_request": "Co-marketing with our reseller — details TBC.",
    },
}

# Audience / segment data — what a CDP would supply.
_SEED_SEGMENTS: dict[str, Any] = {
    "Mid-market SaaS engineering teams": {
        "segments": [
            {"name": "Platform engineering leads", "fit_score": 0.92,
             "size": 48000, "why": "own build-vs-buy + tooling budget"},
            {"name": "Staff/principal engineers", "fit_score": 0.81,
             "size": 120000, "why": "technical evaluators, high influence"},
            {"name": "Eng managers (10-50 reports)", "fit_score": 0.74,
             "size": 65000, "why": "feel the toil, sponsor pilots"},
        ],
        "exclusion_signals": ["students", "job-seekers", "competitor staff"],
        "frequency_cap": 3,
        "estimated_reach": 233000,     # = 48,000 + 120,000 + 65,000
    },
    "Fintech finance operations teams": {
        "segments": [
            {"name": "Finance operations managers", "fit_score": 0.88,
             "size": 21000, "why": "own spend controls and month-end close"},
            {"name": "Controllers (Series B-D fintechs)", "fit_score": 0.79,
             "size": 9500, "why": "sign off tooling budgets"},
        ],
        "exclusion_signals": ["consumers", "students", "competitor staff"],
        "frequency_cap": 2,
        "estimated_reach": 30500,      # = 21,000 + 9,500
    },
}

# Past-campaign performance — what GA4 / Amplitude would supply. Feeds the
# strategist's planning context AND the analytics report-mode baselines.
_SEED_PERFORMANCE: dict[str, Any] = {
    "Mid-market SaaS engineering teams": {
        "baseline_campaigns_count": 6,
        "baseline_open_rate": 0.34,
        "baseline_click_rate": 0.041,
        "baseline_unsubscribe_rate": 0.003,
        "channel_history": [
            {"channel": "linkedin", "avg_cac_cents": 920000, "avg_roas": 2.1},
            {"channel": "email", "avg_cac_cents": 110000, "avg_roas": 4.6},
            {"channel": "meta", "avg_cac_cents": 640000, "avg_roas": 1.4},
            {"channel": "search", "avg_cac_cents": 780000, "avg_roas": 2.8},
        ],
        "best_performing_channel": "email",
    },
    "Fintech finance operations teams": {
        "baseline_campaigns_count": 2,
        "baseline_open_rate": 0.29,
        "baseline_click_rate": 0.033,
        "baseline_unsubscribe_rate": 0.004,
        "channel_history": [
            {"channel": "linkedin", "avg_cac_cents": 1_150_000, "avg_roas": 1.8},
            {"channel": "search", "avg_cac_cents": 860_000, "avg_roas": 2.4},
        ],
        "best_performing_channel": "search",
    },
}

# Competitor signals — what a competitive-intel platform would supply.
_SEED_COMPETITORS: dict[str, Any] = {
    "Mid-market SaaS engineering teams": [
        {"name": "Incumbent Corp", "recent_move": "cut entry price 20%",
         "threat_level": "high"},
        {"name": "Quillstack", "recent_move": "shipped an AI copilot beta",
         "threat_level": "medium"},
        {"name": "LegacySoft", "recent_move": "no notable activity",
         "threat_level": "low"},
    ],
    "Fintech finance operations teams": [
        {"name": "Ledgerline", "recent_move": "launched a free spend-audit tier",
         "threat_level": "medium"},
    ],
}


def _seed_once(kind: str, seed: dict[str, Any]) -> dict[str, Any]:
    """Idempotent seed: write the fixture only if the file is empty."""
    with _LOCK:
        data = _load(kind)
        if not data:
            data = dict(seed)
            _save(kind, data)
        return data


# ── Brand guidelines + compliance lexicon ───────────────────────────────
def get_brand_guidelines(brand_id: str = "leafmesh-default") -> dict[str, Any]:
    data = _seed_once("brand_guidelines",
                      {"leafmesh-default": _SEED_BRAND_GUIDELINES})
    return data.get(brand_id) or data.get("leafmesh-default") or {}


def banned_claims(brand_id: str = "leafmesh-default") -> list[str]:
    return list(get_brand_guidelines(brand_id).get("banned_claims", []))


def legal_trigger_terms(brand_id: str = "leafmesh-default") -> list[str]:
    return list(get_brand_guidelines(brand_id).get("legal_trigger_terms", []))


def regulated_industries(brand_id: str = "leafmesh-default") -> list[str]:
    return list(get_brand_guidelines(brand_id).get("regulated_industries", []))


def max_unapproved_spend_cents(brand_id: str = "leafmesh-default") -> int:
    try:
        return int(get_brand_guidelines(brand_id)
                   .get("max_unapproved_spend_cents", 5_000_000))
    except (TypeError, ValueError):
        return 5_000_000


# ── Briefs ───────────────────────────────────────────────────────────────
def get_brief(campaign_id: str) -> dict[str, Any]:
    data = _seed_once("briefs", _SEED_BRIEFS)
    return dict(data.get(campaign_id) or {})


def any_seed_brief() -> dict[str, Any]:
    data = _seed_once("briefs", _SEED_BRIEFS)
    for v in data.values():
        if isinstance(v, dict):
            return dict(v)
    return {}


def put_brief(brief: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        store = _load("briefs") or dict(_SEED_BRIEFS)
        cid = brief.get("campaign_id") or new_id("camp")
        brief["campaign_id"] = cid
        brief["updated_at"] = _now()
        store[cid] = {**store.get(cid, {}), **brief}
        _save("briefs", store)
        return store[cid]


# ── Audience / segments ──────────────────────────────────────────────────
def _market_key(data: dict[str, Any], target_market: str) -> str:
    """The seeded market a brief's target market refers to: an exact match,
    or the seeded market it starts with ("Mid-market SaaS engineering teams
    (US, UK, DACH)" → "Mid-market SaaS engineering teams")."""
    tm = (target_market or "").strip()
    if not tm or tm in data:
        return tm
    for key in data:
        if tm.lower().startswith(key.lower()):
            return key
    return tm


def get_segments(target_market: str) -> dict[str, Any]:
    data = _seed_once("segments", _SEED_SEGMENTS)
    return dict(data.get(_market_key(data, target_market)) or {})


# ── Competitor signals ───────────────────────────────────────────────────
def get_competitor_signals(target_market: str) -> list[dict[str, Any]]:
    data = _seed_once("competitors", _SEED_COMPETITORS)
    return list(data.get(_market_key(data, target_market)) or [])


# ── Past-campaign performance ────────────────────────────────────────────
def get_performance(target_market: str) -> dict[str, Any]:
    data = _seed_once("performance", _SEED_PERFORMANCE)
    return dict(data.get(_market_key(data, target_market)) or {})


# ═══════════════════════════════════════════════════════════════════════
# FINISHER SUPPORT — publisher outbox + append-only ledger + post-gate
# recovery. Dev stand-ins for the ad platforms / your system of record; the
# function SIGNATURES are the contract you swap real systems into.
# ═══════════════════════════════════════════════════════════════════════
def record_outbox(entry: dict[str, Any]) -> dict[str, Any]:
    """The publisher's outward sends (Meta/IG/LinkedIn/ESP dispatch records)."""
    with _LOCK:
        outbox = _load("outbox")
        rows = outbox.get("rows") if isinstance(outbox.get("rows"), list) else []
        rec = {"recorded_at": _now(), **entry}
        rows.append(rec)
        _save("outbox", {"rows": rows})
    return rec


def append_ledger(entry: dict[str, Any]) -> dict[str, Any]:
    """Append-only publish ledger (dev mirror of the WORM sink for local demo)."""
    with _LOCK:
        ledger = _load("publish_ledger")
        rows = ledger.get("rows") if isinstance(ledger.get("rows"), list) else []
        rec = {"recorded_at": _now(), **entry}
        rows.append(rec)
        _save("publish_ledger", {"rows": rows})
    return rec


def already_published(campaign_id: str) -> bool:
    """True when the publish ledger already records this campaign as live —
    the publisher's double-spend guard."""
    if not campaign_id:
        return False
    rows = _load("publish_ledger").get("rows") or []
    return any(isinstance(r, dict) and r.get("campaign_id") == campaign_id
               and r.get("event") == "published" for r in rows)


def put_approved_campaign(campaign_id: str, pack: dict[str, Any]) -> None:
    """Dev-store recovery mirror — the finisher's last-resort read after the
    HITL gate when the in-process stash is cold (e.g. a restart)."""
    if not campaign_id:
        return
    with _LOCK:
        data = _load("approved_campaigns")
        data[campaign_id] = {"stored_at": _now(), **pack}
        _save("approved_campaigns", data)


def get_approved_campaign(campaign_id: str) -> dict[str, Any]:
    if not campaign_id:
        return {}
    return dict(_load("approved_campaigns").get(campaign_id) or {})


# ═══════════════════════════════════════════════════════════════════════
# AEO/GEO AUDIT BACKLOG — the page queue the parallel copies split via the
# atomic claim tool (claim_audit_batch). Seeded so the weekly sweep runs day-0
# with no CMS/SEO connector wired. In production, claim_audit_batch pops from
# your content pipeline instead.
# ═══════════════════════════════════════════════════════════════════════
_SEED_AUDIT_PAGES: list[dict[str, Any]] = [
    {"url": "/blog/what-is-platform-engineering",
     "content": ("Platform engineering is defined as the practice of building "
                 "internal developer platforms. What is a golden path? How does "
                 "it reduce toil? According to the 2026 Northwind platform survey, "
                 "62% of teams surveyed run a platform team. "
                 "<cite>source: Northwind Research 2026</cite>")},
    {"url": "/product/pro-tier",
     "content": "Pro Tier. Pro Tier. Pro Tier. Pro Tier. Pro Tier. Buy now."},
    {"url": "/guides/build-vs-buy",
     "content": ("Build versus buy: a decision guide. When should you build? "
                 "Why does buying win for undifferentiated work? This guide walks "
                 "through the trade-offs with examples and a scoring rubric that "
                 "many teams adapt for their own context and budget cycles.")},
    {"url": "/pricing",
     "content": "Pricing page with plans and a comparison table."},
    {"url": "/blog/observability-101",
     "content": ("Observability refers to understanding a system from its "
                 "outputs. What are the three pillars? How do traces help? "
                 "According to our tracing guide, spans model units of work. "
                 "[1] Author: A. Rivera. Published 2026-02-01.")},
]


def _seed_audit_queue() -> dict[str, Any]:
    with _LOCK:
        data = _load("audit_queue")
        if not data or not isinstance(data.get("pages"), list):
            data = {"pages": [dict(p) for p in _SEED_AUDIT_PAGES]}
            _save("audit_queue", data)
        return data


def claim_audit_pages(batch_size: int = 2) -> list[dict[str, Any]]:
    """Atomically claim (pop) up to batch_size pages from the audit backlog.

    The atomic claim under a lock is what lets N parallel copies split the
    backlog instead of duplicating it (scaling.copies). Returns [] when
    the queue is drained — the caller then reports total_pages 0, not a guess.
    """
    try:
        n = max(0, int(batch_size))
    except (TypeError, ValueError):
        n = 0
    if n == 0:
        return []
    with _LOCK:
        data = _load("audit_queue")
        if not isinstance(data.get("pages"), list):
            data = {"pages": [dict(p) for p in _SEED_AUDIT_PAGES]}
        pages = data.get("pages") or []
        claimed, rest = pages[:n], pages[n:]
        _save("audit_queue", {"pages": rest})
    return [dict(p) for p in claimed]
