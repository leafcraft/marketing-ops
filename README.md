# marketing-ops — Marketing Ops (campaign & growth)

A LeafMesh deployment that runs marketing operations end-to-end:
brief → audience + competitor intel → strategy → copy + visuals →
compliance → human approval → publish → performance + attribution. A
peer-to-peer team of governed agents (Rule 1) — the Manager hovers
above and intervenes only when narration / escalation / contract
violations trigger.

## Story — one brief, end to end

**Priya**, a product marketing manager, drops a launch brief into the
intake form: *"Pro Tier 2.0 — mid-market SaaS engineering teams,
$68K, goals: awareness + demo signups."* The form posts to the
`new_brief` entry point.

`campaign_strategist_agent` picks it up, **normalises** the raw form
into a canonical `CampaignBrief` (mints `campaign_id`, fills defaults),
and — seeing no market-intelligence yet — routes to
`market_intelligence_agent`. The analyst returns ranked audience
segments, persona fit scores, an addressable-reach estimate, exclusion
signals for safety, and a competitor snapshot; no imminent threat, so
it hands back to the strategist, who now builds the strategy: KPIs,
channel mix, budget allocation, a 4-week timeline, and flags the
campaign for legal review because it makes a comparative claim.

The strategist fans out to `copywriter_agent` (three A/B/C variants
per channel) and `visual_briefer_agent` (per-channel creative briefs +
DALL·E prompts) in parallel. Both feed `compliance_reviewer_agent`,
which scores brand safety, catches the comparative claim, sets
`requires_legal_review = true`, and — because the verdict is about to
cross a **human gate** — its Python micro-module stashes the reviewed
campaign context keyed by session. The flow routes to
`legal_reviewer_human`. Legal confirms the claim is defensible and
approves; routing passes to `marketing_manager_human`, who approves
the spend.

Only now does `publisher_agent` run. It reads the approved channel mix
and budgets **from the pre-gate stash only** (never from LLM context),
dispatches to Meta / IG / LinkedIn / Email, tags every impression for
attribution, and hands off to `marketing_analytics_agent`, whose n8n
connector reads KPI status and multi-touch attribution from Priya's
analytics platform (GA4 / Amplitude / Looker). Every terminus lands in
`marketing_audit_logger_agent`, a hash-chained WORM record. Priya
never touched a spreadsheet, and nothing went live without a brand,
legal, and budget sign-off.

## Why it works in an organization

Marketing is a serial bottleneck: a brief waits on an analyst, the
analyst on a strategist, copy on review, review on legal, legal on the
CMO — each handoff an email and a delay. This mesh collapses the
**routine** path (normalise, segment, strategise, draft, score) into
one governed pass that runs in minutes, while keeping a human on every
**judgment** step that matters: regulated-claim review, campaign
approval, budget escalation, crisis response.

The ROI is twofold. **Throughput**: junior analyst, copywriter, and
coordination time is automated, so the team ships more campaigns
without more headcount. **Risk avoidance**: no campaign goes live
without a compliance gate and a human approval; regulated/comparative
claims force legal; crises always land on the CMO desk; budgets over
$50K escalate; and every decision is in a tamper-evident audit log —
which is exactly what brand and legal teams need to sign off on
delegating any of this to automation in the first place. The
enterprise state of record (metrics, attribution, the posting
calendar, sentiment history) stays in the systems the org already
owns — the mesh orchestrates, it does not become a second database.

## Configuration

Three tiers, grounded in `env` + `configs/config.yaml`.

### Tier 1 — Boot (required to start at all)

| Var | Required | What it does |
|---|---|---|
| `LEAFMESH_LICENSE_KEY` | **required** | Starts the SDK; `start()` aborts without it |
| `LEAFMESH_ENV_TOKEN` | **required** | Per-environment telemetry token (dev/staging/prod) |
| `OPENAI_API_KEY` | **required** | Primary LLM provider — every `gpt-4o-mini` agent |
| `ANTHROPIC_API_KEY` | optional | `claude-sonnet-4-6` powers `social_media_agent`; also the BuiltIn Summarizer narration |

### Tier 2 — Host prerequisites & escalation adapters

| Var | Required | What it does |
|---|---|---|
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | optional | Session/auto-storage; defaults to `localhost:6379` no-auth (run `docker compose up redis -d`) |
| `PAGER_WEBHOOK` | optional | PagerDuty-style webhook escalation target (manager escalation block) |
| `SLACK_MARKETING_CHANNEL` | optional | Slack channel id for the manager's escalation `channel` target |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` | optional | **Not plug-and-play** — read only by a Slack adapter you must wire in code/connector; the escalation `channel: slack` target needs that adapter to actually post |

### Tier 3 — Connectors (wire to your systems; all optional)

| Var | Required | What it does |
|---|---|---|
| `N8N_MARKETING_ANALYTICS_WEBHOOK_URL` | optional | n8n workflow fronting GA4 / Amplitude / Looker — `marketing_analytics_agent` |
| `N8N_CAMPAIGN_ORCHESTRATOR_WEBHOOK_URL` | optional | n8n workflow fronting Marketo / HubSpot — `campaign_orchestrator_agent` weekly sweep |
| (social-listening) | optional | No env var — Brandwatch / Sprout / Talkwalker push rollups into the `brand_mention_ingest` / `brand_sentiment_sweep` entry points |
| (social scheduler) | optional | No env var — `social_media_agent` drafts variants + proposes slots; Hootsuite / Buffer / Sprout Social owns the calendar |

Until a Tier-3 connector is wired, its agent returns the declared
yields shape with type defaults (lenient yields enforcement), so
downstream conditions always see a known shape — the mesh runs, that
path just produces empty results.

## YAML-first — read the department in one file

`configs/config.yaml` IS the marketing department. Narrative judgment
(strategy, segmentation, copy tone, briefings) lives in the agent
prompts. The **deterministic floors and self-reliant context-pulls live
in Python** — and only there, because the LLM must not be able to waive
them. Enterprise state lives in YOUR systems, not template SQLite.

**Self-reliant agents — `@pre_compose` pulls their own context:**

- `campaign_strategist_agent.py` — `@pre_compose` pulls the brief +
  audience segments + past-campaign performance + competitor signals +
  the brand spend ceiling; `@compose` ships market_intelligence /
  copywriter / visual_briefer each the payload it needs; `@chain
  enforce_spend_floor` forces `requires_cmo_escalation` when total
  budget exceeds the brand's $50K ceiling.
- `market_intelligence_agent.py` — `@pre_compose` pulls segments +
  performance + competitor signals; `@chain enforce_threat_floor`
  force-merges any high/critical/severe competitor into `threat_alerts`
  so the crisis fast-path fires even if the LLM under-reports.
- `copywriter_agent.py` — `@pre_compose` pulls brand voice + tone rules
  + the banned-claim lexicon so it drafts in-voice; `@chain
  flag_banned_in_copy` forces `has_protected_claims` on any banned-term
  slip.

**Deterministic floors the LLM can't waive (`@chain`):**

- `compliance_reviewer_agent.py` — `@pre_compose` pulls the
  banned-claim / legal-trigger lexicon; `@chain enforce_compliance_floor`
  scans the actual copy: a banned-claim hit forces
  `approved_for_publish=false`, a legal-trigger / regulated-industry hit
  forces `requires_legal_review=true` — THEN stashes the reviewed
  campaign payload keyed by session before the human gate.
- `brand_guardian_agent.py` — `@chain enforce_crisis_floor`: crisis mode
  forces `requires_cmo_action=true` (a crisis ALWAYS reaches the CMO);
  the severe-negative-spike rule is recomputed from the rollups, not
  trusted to the LLM; regulatory/data-breach forces legal into the route.

**Actuators / sinks (Python required):**

- `publisher_agent.py` — outward, paid actuator behind the human gate.
  FAILS CLOSED: reads the approved campaign payload from the pre-gate
  session stash only, never from LLM context.
- `marketing_audit_logger_agent.py` — hash-chained WORM audit terminus.

**Dev context store** (`agency/_shared/store.py`) — seeded with a
realistic brief, brand guidelines + the banned-claim / legal-trigger
lexicon, audience segments, past-campaign performance, and competitor
signals, so the FULL chain runs end-to-end with **no connectors set**.
In production, swap the store read calls for connector calls — the shape
the mesh reads is the contract.

```
  entry points (brief, launch, competitor signal, crisis, ingest, cron)
                          │
                          ▼
          campaign_strategist_agent (LLM + @pre_compose context-pull
                 │  + @compose + @chain spend floor)
                 │  budget > $50K → cmo_human (spend escalation)
                 │  needs_market_intelligence?
                 ▼
          market_intelligence_agent (LLM + @pre_compose + threat floor)
                 │            │ threat_alerts != []
                 │            ▼
                 │      brand_guardian_agent ──▶ cmo / legal / manager
                 ▼
       copywriter_agent + visual_briefer_agent (fan-out)
                 │ (wait_for both)
                 ▼
          compliance_reviewer_agent (LLM gate + pre-gate stash)
             │ clean                  │ requires_legal_review
             ▼                        ▼
     marketing_manager_human    legal_reviewer_human
             │ approve                │ approve → manager
             ▼
        publisher_agent (fail-closed actuator)
             │
             ▼
     marketing_analytics_agent (n8n → GA4/Amplitude/Looker)
             │
             ▼
     marketing_audit_logger_agent (WORM terminus)
```

Parallel citizens: `campaign_orchestrator_agent` (weekly MAP sweep —
cron commented until the connector is wired), `social_media_agent`
(schedule + triage modes), `aeo_geo_optimiser_agent` (AI-answer-engine
content audit).

## The team

Role = the human job title each agent stands in for.

| Agent | Role | Responsibilities | Can perform |
|---|---|---|---|
| `campaign_strategist_agent` | Campaign strategist | `@pre_compose` pulls brief + segments + past performance + competitor signals; normalises into `CampaignBrief`; builds strategy/KPIs/channel mix/budget/timeline; `@chain` spend floor forces CMO escalation over $50K | → cmo (budget > $50K), → market_intelligence (fresh brief), → copywriter + visual_briefer (intel ready) |
| `market_intelligence_agent` | Market intelligence analyst | `@pre_compose` pulls segments + performance + competitor signals; audience + persona + reach + exclusions AND competitor landscape; `@chain` threat floor force-merges high-threat competitors into `threat_alerts` | → campaign_strategist; → brand_guardian when `threat_alerts` non-empty |
| `copywriter_agent` | Copywriter | `@pre_compose` pulls brand voice + banned-claim lexicon; drafts 3 A/B/C variants per channel; `@chain` banned-term self-check forces `has_protected_claims` | → compliance_reviewer |
| `visual_briefer_agent` | Art director / creative briefer | Builds per-channel visual briefs + DALL·E prompts; runs an audience-representation check when people imagery is involved | → compliance_reviewer |
| `compliance_reviewer_agent` | Brand & compliance reviewer | `@pre_compose` pulls the banned-claim/legal-trigger lexicon; `@chain` scans copy — banned claim blocks publish, legal-trigger forces legal review (LLM can't waive) — then stashes the reviewed context pre-gate | → marketing_manager (clean), → legal_reviewer (`requires_legal_review`) |
| `publisher_agent` | Publishing / ad-ops operator | Fail-closed multi-channel dispatch (Meta/IG/LinkedIn/Email); spends budget only from the approved pre-gate stash; tags impressions for attribution | → marketing_analytics |
| `marketing_analytics_agent` | Marketing analytics lead | Reads KPI status, multi-touch attribution, email-engagement benchmarks from your analytics platform via n8n | → marketing_manager (`requires_manager_review`), → audit |
| `campaign_orchestrator_agent` | Campaign operations coordinator | Weekly sweep of live campaigns + spend pacing from your MAP via n8n; flags campaigns needing review | → marketing_analytics |
| `brand_guardian_agent` | Brand & PR crisis lead | Judges brand-sentiment rollups + drafts crisis response + holding statement; `@chain` crisis floor forces CMO on every crisis, recomputes the severe-spike rule, forces legal on regulatory/data-breach | → cmo (`requires_cmo_action`), → legal (regulatory/data-breach), → marketing_manager (campaign-tied signal below CMO floor) |
| `social_media_agent` | Social media manager | Drafts per-platform native variants + proposes posting slots (schedule mode); classifies + triages replies (triage mode) | → publisher (fits), → copywriter (rewrite needed), → brand_guardian (crisis-grade replies), → audit |
| `aeo_geo_optimiser_agent` | AEO/GEO content optimiser | Scores pages for AI-answer-engine pickup against a full rubric; recommends issue-specific rewrites | → copywriter (rewrites needed), → audit |
| `marketing_manager_human` | Marketing manager | Campaign approval, scale/pause, calendar ownership; escalates >$50K to CMO | → publisher (approve), → copywriter (revise), → cmo (escalate), → audit (hold) |
| `legal_reviewer_human` | Legal counsel | Reviews regulated claims, comparative copy, disclaimers; default-deny on 4h timeout | → marketing_manager (approve), → copywriter (revise), → audit (hold) |
| `cmo_human` | Chief Marketing Officer | High-stakes campaigns, brand crises, budget escalations; default-deny on 8h timeout | → publisher (approve), → campaign_strategist (revise), → audit (hold/crisis) |
| `marketing_audit_logger_agent` | Compliance / audit recorder | Writes the hash-chained WORM record at every flow terminus | (terminus) |

## Quick start

```bash
cp env .env       # fill in keys
pip install -r requirements.txt
docker run -d -p 6379:6379 redis:7-alpine
python main.py
```

Trigger a synthetic brief:

```bash
curl -X POST http://127.0.0.1:18820/api/mesh/request \
  -H "Content-Type: application/json" \
  -d '{
    "entry_point": "new_brief",
    "data": {
      "payload": {
        "campaign_id": "camp-2026-demo-001",
        "brief_source": "form",
        "product_or_topic": "Pro Tier 2.0 launch",
        "target_market": "Mid-market SaaS engineering teams",
        "objectives": ["awareness", "demo_signups"],
        "budget_cents": 6800000
      }
    }
  }'
```

## Entry points (Rule 1)

| Entry point | Source | Target |
|---|---|---|
| `new_brief` | Form / email / Asana brief | campaign_strategist |
| `product_launch` | Product-team launch trigger | campaign_strategist |
| `competitor_move` | Competitor pricing/launch signal | market_intelligence |
| `quarterly_planning` | Planning cadence | campaign_strategist |
| `crisis_response` | Brand / PR crisis signal | brand_guardian |
| `email_campaign_ingest` / `email_post_send_analysis` | Your analytics platform (mode=ingest / report) | marketing_analytics |
| `brand_mention_ingest` / `brand_sentiment_sweep` | Your social-listening platform rollups | brand_guardian |
| `weekly_performance` | Weekly sweep (MAP connector) | campaign_orchestrator |
| `schedule_social_posts` / `triage_social_replies` | Social campaign / engagement | social_media |
| `aeo_geo_content_audit` | Content feed (pages) | aeo_geo_optimiser |
| `manual_action` + `direct_call_*` | Team-initiated / ad-hoc | various |

## Wiring the connectors

1. **Analytics** — build an n8n workflow fronting GA4 / Amplitude /
   Looker that returns JSON in `marketing_analytics_agent`'s declared
   yields shape; set `N8N_MARKETING_ANALYTICS_WEBHOOK_URL`.
2. **MAP sweep** — build an n8n workflow fronting Marketo / HubSpot
   that returns `campaign_orchestrator_agent`'s yields shape; set
   `N8N_CAMPAIGN_ORCHESTRATOR_WEBHOOK_URL`, then uncomment its
   `wake_up: "0 9 * * 1"` cron in `configs/config.yaml`.
3. **Social listening** — point Brandwatch / Sprout / Talkwalker
   webhooks at the `brand_mention_ingest` / `brand_sentiment_sweep`
   entry points with the rollup fields in the payload.
4. **Slack escalation** — wire a Slack adapter that reads
   `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` so the manager's
   escalation `channel: slack` target (`SLACK_MARKETING_CHANNEL`)
   actually posts; until then that target is declared but inert.

Missing yields are no problem: lenient yields enforcement fills any
absent key with its type default, so downstream conditions always see
a known shape.

## Trust mechanisms

- **No unreviewed publish, ever** — every campaign passes the
  compliance gate and a human approval before `publisher_agent` runs
- **Fail-closed publishing** — the publisher reads the approved
  payload from the pre-gate stash only; no stash → nothing goes live
- **Deterministic compliance floor** — `@chain` scans the actual copy
  against the brand's banned-claim lexicon (any hit blocks publish) and
  the legal-trigger / regulated-industry terms (any hit forces legal
  review); the LLM may raise a flag but can never lower one below this
  floor
- **Deterministic spend floor** — `@chain` recomputes total budget from
  the channel allocation; over the brand's $50K ceiling it forces CMO
  escalation before any creative spend (the LLM can't waive it)
- **Default-deny review** — compliance approves only with zero flagged
  claims, no protected-attribute risk, and brand-safety score ≥ 0.6;
  any high/critical/severe claim forces legal review
- **Default-deny HITL timeouts** — legal (4h) and CMO (8h) timeouts
  hold the campaign, never auto-approve
- **Crisis always lands on the CMO desk** — `requires_cmo_action` is
  forced true in crisis mode; regulatory / data-breach also routes to
  legal; a campaign-tied signal below the CMO floor routes to the
  marketing manager so the live campaign can be paused
- **Hash-chained WORM audit** — every flow terminus writes a SHA-256
  chained record to `logs/marketing_audit.jsonl`
- **Narration over hidden code** — soft routing ("angry replies →
  crisis path") is declared on the agents as `narration:` blocks the
  Summarizer reads — visible in YAML, not buried in Python

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
python validate_config.py
```

Test coverage:
- Config-shape invariants (multi-entry, conditional wires, connector
  agents are integration+connector_config with no module, pure-YAML vs
  module-backed LLM roles, prompts carry every yields key, HITL
  fallbacks default-deny)
- Agent-logic floors (the depth-bar gates): compliance banned-claim →
  publish blocked + legal-trigger → legal review; strategist spend floor
  → CMO escalation over $50K; market-intel threat floor; brand-guardian
  crisis-pause floor (crisis → CMO, regulatory → legal, spike recompute);
  copywriter banned-term self-check; publisher fail-closed + stash bridge
</content>
</invoke>
