"""Global tools for the marketing-ops pod.

Two day-0 tool surfaces, each reading the dev store so the pod runs with NO
connector wired, and each **announcing itself**: when there is no real source
and no seed, it returns `available: false` and says why — never a synthetic
success that looks like a real read.

  * intel tools (read_audience_segments / read_competitor_signals /
    read_past_performance) — the Market Intelligence Analyst calls these in-turn
    to PULL its data. To go live, wire the CDP / competitive-intel mcp block in
    config.yaml (each named action becomes its own namespaced tool); these dev
    tools are the fallback contract.
  * claim_audit_batch — the ATOMIC CLAIM tool for the AEO/GEO optimiser's
    parallel instances. Each copy claims a DISJOINT batch of pages so a backlog
    is split, not duplicated (2.4.118 instances pattern).
"""
import os

from leafmesh import global_tool, LeafMeshLogger

try:
    from ._shared import store
except ImportError:  # pragma: no cover — direct-run fallback
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore

logger = LeafMeshLogger(__name__)


def _intel_connector_wired() -> bool:
    """True if a real CDP / competitive-intel connector is configured."""
    return bool(os.getenv("CDP_MCP_URL") or os.getenv("COMPETITIVE_INTEL_MCP_URL"))


@global_tool(category="intel")
def read_audience_segments(target_market: str) -> dict:
    """Read ranked audience segments + persona fit for a target market.

    Returns segments (name, fit_score, size, why), exclusion signals, a
    frequency cap, and an estimated reach. Reads the seed CDP store day-0.
    Announces `available: false` when there is genuinely nothing to read.

    Args:
        target_market: The market to segment (e.g. "Mid-market SaaS engineering teams").
    """
    seg = store.get_segments(str(target_market or "").strip())
    if not seg:
        return {"available": False,
                "reason": f"no seed segments for {target_market!r}; wire CDP_MCP_URL"}
    logger.info(f"read_audience_segments market={target_market!r} available=True")
    return {"available": True, "target_market": target_market, **seg}


@global_tool(category="intel")
def read_competitor_signals(target_market: str) -> dict:
    """Read the competitor landscape (name, recent_move, threat_level) for a market.

    Reads the seed competitive-intel store day-0. Announces `available: false`
    when a connector is wired but the market returns nothing, rather than an
    empty-but-confident "no competitors".

    Args:
        target_market: The market whose competitor signals to read.
    """
    sigs = store.get_competitor_signals(str(target_market or "").strip())
    if not sigs and _intel_connector_wired():
        return {"available": False,
                "reason": "connector wired but returned nothing for this market"}
    logger.info(f"read_competitor_signals market={target_market!r} n={len(sigs)}")
    return {"available": True, "target_market": target_market, "competitors": sigs}


@global_tool(category="intel")
def read_past_performance(target_market: str) -> dict:
    """Read past-campaign performance + channel history for a market (baselines,
    per-channel CAC/ROAS, best-performing channel).

    Args:
        target_market: The market whose performance history to read.
    """
    perf = store.get_performance(str(target_market or "").strip())
    if not perf:
        return {"available": False,
                "reason": f"no seed performance for {target_market!r}; wire GA4/Amplitude"}
    return {"available": True, "target_market": target_market, **perf}


@global_tool(category="audit")
def claim_audit_batch(batch_size: int = 2) -> dict:
    """Atomically claim (pop) a DISJOINT batch of pages from the AEO/GEO audit
    backlog, so parallel instances split the work instead of duplicating it.

    Returns `available: false` with an empty page list when the backlog is
    drained — the caller then reports total_pages 0, never a fabricated score.

    Args:
        batch_size: How many pages this instance should claim (default 2).
    """
    pages = store.claim_audit_pages(batch_size)
    if not pages:
        return {"available": False, "pages": [],
                "reason": "audit backlog drained — no pages left to claim"}
    logger.info(f"claim_audit_batch claimed={len(pages)}")
    return {"available": True, "pages": pages, "claimed": len(pages)}
