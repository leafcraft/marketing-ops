"""marketing-ops — Marketing Ops (campaign & growth).

YAML-FIRST mesh: the marketing department lives in configs/config.yaml.
Campaign briefs land via many channels; the team plans strategy,
drafts copy + visuals, gates compliance, publishes after human
approval, and reads performance from YOUR analytics platform / MAP
via n8n connectors. A peer-to-peer TEAM of agents (Rule 1) — the
Manager hovers above and intervenes only on narration / escalation /
contract violations.

Python is kept ONLY where it must be: the fail-closed publisher
actuator, the compliance pre-gate stash write, and the hash-chained
audit sink (see agency/).

For full architecture: see README.md.
"""
import asyncio
import signal
import sys

from dotenv import load_dotenv
from leafmesh import EventType, LeafMesh, LeafMeshLogger


load_dotenv()
logger = LeafMeshLogger(__name__)

leafmesh = LeafMesh.from_yaml("configs/config.yaml")


# ── Event-bus subscribers — marketing audit + ops surface ─────────
async def _on_agent_error(event):
    logger.warning(
        f"[mkt-audit] AGENT_ERROR session={event.session_id} "
        f"data={(event.data or {})!r}"
    )

async def _on_manager_intervention(event):
    logger.warning(
        f"[mkt-ops] MANAGER_INTERVENTION session={event.session_id} "
        f"data={(event.data or {})!r}"
    )

async def _on_intervention_needed(event):
    logger.error(
        f"[mkt-ops] INTERVENTION_NEEDED session={event.session_id} "
        f"data={(event.data or {})!r}"
    )

async def _on_human_input_timeout(event):
    logger.warning(
        f"[mkt-audit] HITL TIMEOUT session={event.session_id} "
        f"data={(event.data or {})!r}"
    )


async def main():
    await leafmesh.start()

    leafmesh.event_bus.subscribe(EventType.AGENT_ERROR,           _on_agent_error)
    leafmesh.event_bus.subscribe(EventType.MANAGER_INTERVENTION,  _on_manager_intervention)
    leafmesh.event_bus.subscribe(EventType.INTERVENTION_NEEDED,   _on_intervention_needed)
    leafmesh.event_bus.subscribe(EventType.HUMAN_INPUT_TIMEOUT,   _on_human_input_timeout)

    try:
        await leafmesh.enable_self_healing()
        logger.info("Self-healing enabled (6 graduated recovery actions)")
    except AttributeError:
        pass

    agents = (
        leafmesh.registry.list_agents()
        if hasattr(leafmesh, "registry") and leafmesh.registry
        else []
    )
    if agents:
        summary = ", ".join(f"{a.name} ({a.agent_type})" for a in agents)
        logger.info(f"Registered agents: {summary}")

    logger.info("marketing-ops — Marketing Ops mesh running")
    logger.info("API docs (synthetic testing): http://127.0.0.1:18820/docs")

    # ── Synthetic trigger — new campaign brief ─────────────────────
    # result = await leafmesh.mesh_call(
    #     "new_brief",
    #     input_data={
    #         "payload": {
    #             "campaign_id": "camp-2026-demo-001",
    #             "brief_source": "form",
    #             "product_or_topic": "Pro Tier 2.0 launch",
    #             "target_market": "Mid-market SaaS engineering teams",
    #             "objectives": ["awareness", "demo_signups"],
    #             "budget_cents": 6_800_000,
    #         },
    #     },
    # )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
        await stop_event.wait()
    else:
        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            pass

    logger.info("Shutting down (draining in-flight campaign workflows)...")
    await leafmesh.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
