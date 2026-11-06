# PRD — Marketing Ops (campaign & growth)

## Overview / story

A marketing department as a LeafMesh agency. Campaign briefs arrive on
many channels (intake form, email, product-launch trigger, competitor
signal, brand crisis, analytics/social ingests, a weekly cron). The
team normalises the brief, researches audience + competitors, builds
strategy, drafts copy + visuals, gates compliance, takes human
approval, publishes across channels, and reads back performance +
attribution — with every judgment step held by a human and every
terminus written to a tamper-evident audit log.

**Story.** Priya, a product marketing manager, submits a Pro-Tier-2.0
launch brief to the intake form (`new_brief`). The strategist
normalises it, pulls market intelligence (audience segments +
competitor read), builds the strategy and flags a comparative claim,
then fans out to copy + visuals. Compliance scores the creative,
catches the claim, and routes to legal; legal approves, then the
marketing manager approves the spend; only then does the fail-closed
publisher dispatch to Meta/IG/LinkedIn/Email and tag impressions for
attribution; analytics reads KPIs back from her GA4/Amplitude/Looker
stack; the audit recorder seals the cycle. No campaign goes live
without a brand, legal, and budget sign-off.

## Flow diagram

```
 ENTRY POINTS
  new_brief / product_launch / quarterly_planning / manual_action ─┐
  competitor_move ───────────────┐                                 │
  crisis_response ──┐            │                                 │
  brand_mention_*  ─┤            │                                 ▼
  brand_sentiment_*─┤            │              campaign_strategist_agent (LLM)
  email_*_ingest ──┐│            │                  │ normalise + strategise
  email_*_analysis─┤│            │      needs_market_intelligence?
  weekly_perf ────┐││            │            │true            │false
  schedule_social ┐│││           ▼            ▼                 ▼
  triage_social  ─┤│││  market_intelligence_agent ──┐   copywriter_agent
  aeo_audit ─────┐││││         (LLM)                │   visual_briefer_agent
                 │││││  threat_alerts != [] │       │        (fan-out, wait_for both)
                 │││││                      ▼       │            ▼
                 │││││            brand_guardian_agent   compliance_reviewer_agent (LLM)
                 │││││  (LLM)  ┌───┴────────┬──────┐     │ default-deny gate
                 │││││  cmo ◀──┘   legal ◀──┘  mgr ◀┘     │ + pre-gate stash (PY)
                 │││││  (requires_cmo)  (regul/breach) (campaign-tied)
                 │││││                                clean │     │ requires_legal_review
                 │││││                                      ▼     ▼
                 │││││                       marketing_manager_human  legal_reviewer_human
                 │││││                              │approve            │approve → manager
                 │││││                              ▼  │revise → copywriter
                 │││││                       publisher_agent (PY, fail-closed)
                 │││││                              ▼
                 ││││└─▶ aeo_geo_optimiser_agent    marketing_analytics_agent (n8n)
                 ││││    (LLM) → copywriter/audit          │requires_manager_review → mgr
                 ││││                                      ▼
                 │││└──▶ social_media_agent (LLM)   marketing_audit_logger_agent (PY, WORM)
                 │││     schedule → publisher/copywriter          ▲
                 │││     triage   → brand_guardian/audit          │
                 ││└───▶ campaign_orchestrator_agent (n8n) ───────┘
                 ││      weekly MAP sweep → analytics
                 │└────▶ marketing_analytics_agent (n8n) ─────────┘
                 └─────▶ (every terminal branch → audit logger)
```

Back-edges are bounded rework only: a human `revise` returns to
`copywriter_agent` / `campaign_strategist_agent`; the strategist's
`needs_market_intelligence` flag is set false on any intel call-back or
HITL revision, so the strategist ↔ analyst pair cannot ping-pong.

## Actor inventory

Role = the human job title each agent stands in for.

| Agent | Role | Responsibilities | Can perform |
|---|---|---|---|
| `campaign_strategist_agent` | Campaign strategist | Brief normalisation + strategy/KPI/budget/timeline + legal-claim flag | → market_intelligence / copywriter + visual_briefer |
| `market_intelligence_agent` | Market intelligence analyst | Audience + persona + reach + exclusions AND competitor landscape + threats | → campaign_strategist; → brand_guardian on threat |
| `copywriter_agent` | Copywriter | 3 A/B/C variants per channel; tone; reading grade; claim flag | → compliance_reviewer |
| `visual_briefer_agent` | Art director / creative briefer | Per-channel visual briefs + DALL·E prompts; representation check | → compliance_reviewer |
| `compliance_reviewer_agent` | Brand & compliance reviewer | Default-deny review + pre-gate context stash | → manager / legal |
| `publisher_agent` | Publishing / ad-ops operator | Fail-closed multi-channel dispatch; attribution tagging | → marketing_analytics |
| `marketing_analytics_agent` | Marketing analytics lead | KPI status + attribution + email benchmarks from your platform | → manager / audit |
| `campaign_orchestrator_agent` | Campaign operations coordinator | Weekly live-campaign + spend-pacing sweep from your MAP | → marketing_analytics |
| `brand_guardian_agent` | Brand & PR crisis lead | Sentiment-spike judgment + crisis response/holding statement | → cmo / legal / manager |
| `social_media_agent` | Social media manager | Per-platform variants + slot proposals; reply triage | → copywriter / brand_guardian / audit |
| `aeo_geo_optimiser_agent` | AEO/GEO content optimiser | Score pages for AI-answer-engine pickup; rewrite recommendations | → copywriter / audit |
| `marketing_manager_human` | Marketing manager | Final campaign approval, pause / performance decisions; 8h window | → publisher / copywriter / audit |
| `legal_reviewer_human` | Legal counsel | Regulated/comparative-claim review; 24h window | → coordinator (→ manager) / copywriter / audit |
| `cmo_human` | Chief Marketing Officer | Budgets over the $50K ceiling, crises, severe spikes; 8h window | → campaign_strategist / audit |
| `marketing_audit_logger_agent` | Compliance / audit recorder | Hash-chained WORM record at every terminus | (terminus) |

## Data artifacts

- **Dev context store** (`agency/_shared/store.py`) — the day-0 stand-in
  for the org's systems of record: seeded brief, brand guidelines + the
  banned-claim / legal-trigger lexicon + $50K spend ceiling, audience
  segments, past-campaign performance + channel history, competitor
  signals. The `@pre_compose` processors read it; production swaps the
  reads for connector calls (CDP / brand wiki / GA4 / intel platform).
- **`CampaignBrief`** (declared `data_structure`) — `campaign_id`,
  `brief_source`, `product_or_topic`, `target_market`, `objectives`,
  `budget_cents`, `received_at_utc`. The strategist normalises any raw
  inbound payload into this shape.
- **Strategy bundle** — strategist yields (KPIs, channel mix, budget
  allocation, timeline, legal-review flag) carried forward as
  `upstream_yields`.
- **Creative bundle** — copy variants + visual briefs + generation
  prompts.
- **Compliance verdict** — brand-safety score, flagged claims,
  required disclaimers, approval booleans, identity passthrough.
- **Pre-gate session stash** (`agency/_shared/session_stash.py`) —
  campaign_id / channel mix / budgets / variants / disclaimers /
  verdict, keyed by `session_id`; the bridge across the HITL gap.
- **WORM audit line** (`logs/marketing_audit.jsonl`) — SHA-256 chained
  record: record_id, campaign_id, upstream yields, human decision meta,
  prev-hash.

## Per-agent spec (where the work lives)

- **Pure-YAML LLM roles** (rules in the prompt, no module):
  `visual_briefer`, `social_media`, `aeo_geo_optimiser`. Each carries an
  `OUTPUT CONTRACT` listing every yield key, `enforce_yields`, and (where
  it grounds) a `knowledge` group on `mongo_main`.
- **Self-reliant module-backed LLM roles** (`agent_type: llm` + a prompt
  AND a matching `agency/<name>.py` that wraps the LLM with decorators):
  - `campaign_strategist_agent.py` — `@pre_compose load_planning_context`
    pulls the brief + segments + past performance + competitor signals +
    spend ceiling; `@compose` ships each downstream the payload it needs;
    `@chain enforce_spend_floor` forces `requires_cmo_escalation` over the
    $50K ceiling.
  - `market_intelligence_agent.py` — `@pre_compose load_market_data` pulls
    segments + performance + competitor signals; `@chain
    enforce_threat_floor` force-merges high-threat competitors into
    `threat_alerts`.
  - `copywriter_agent.py` — `@pre_compose load_brand_voice` pulls voice +
    banned-claim lexicon; `@chain flag_banned_in_copy` forces
    `has_protected_claims` on a banned-term slip.
  - `brand_guardian_agent.py` — `@chain enforce_crisis_floor` forces CMO
    on every crisis, recomputes the severe-spike rule, forces legal on
    regulatory/data-breach.
- **Pure connector-YAML** (`integration: n8n` + `connector_config`, no
  module): `marketing_analytics_agent` (analytics platform),
  `campaign_orchestrator_agent` (MAP). The n8n workflow returns the
  declared yields shape; lenient enforcement fills missing keys.
- **Python required — floor / actuator / sink:**
  - `compliance_reviewer_agent.py` — `@pre_compose` pulls the brand
    lexicon; `@chain enforce_compliance_floor` scans copy (banned →
    blocked, legal-trigger → legal review) THEN stashes the reviewed
    context pre-gate.
  - `publisher_agent.py` — fail-closed actuator: reads the approved
    channel mix from the stash only; no stash → nothing goes live.
  - `marketing_audit_logger_agent.py` — hash-chained WORM terminus.
- **Dev context store** (`agency/_shared/store.py`) — seeded brief +
  brand guidelines + banned-claim/legal-trigger lexicon + segments +
  past-campaign performance + competitor signals, so the full chain runs
  day-0 with no connectors set. The `@pre_compose` processors read it in
  dev; connector calls replace the reads in prod (same shape).
- **Human roster**: `marketing_manager_human`, `legal_reviewer_human`,
  `cmo_human` — default human interface (the Studio Inbox). Nothing is
  published or approved on silence: on leafmesh 2.4.486 a review nobody
  answers in time closes its card and the case records that no reply
  came; each seat declares `fallback_response: held_for_review` as the
  intended timeout answer.

## Entry points

`new_brief`, `product_launch`, `quarterly_planning`, `manual_action`
→ strategist · `competitor_move` → market_intelligence ·
`crisis_response`, `brand_mention_ingest`, `brand_sentiment_sweep` →
brand_guardian · `email_campaign_ingest`, `email_post_send_analysis`
→ analytics · `weekly_performance` → orchestrator ·
`schedule_social_posts`, `triage_social_replies` → social_media ·
`aeo_geo_content_audit` → aeo_geo_optimiser · plus `direct_call_*`
debug entries to each non-human, non-terminal agent.

## Controls / trust

- **Deterministic compliance floor** — `@chain enforce_compliance_floor`
  scans the actual copy against the brand banned-claim lexicon (hit →
  `approved_for_publish=false`) and legal-trigger / regulated terms (hit
  → `requires_legal_review=true`). Plus default-deny: approve only with
  zero flagged claims, no protected-attribute risk, brand-safety ≥ 0.6.
  The LLM may raise a flag, never lower one below the floor.
- **Deterministic spend floor** — `@chain enforce_spend_floor` sums the
  channel budget and forces `requires_cmo_escalation` over the brand's
  $50K ceiling, routing to the CMO before any creative spend.
- **Deterministic threat floor** — `@chain enforce_threat_floor`
  force-merges high/critical/severe competitors into `threat_alerts` so
  the crisis fast-path fires even if the LLM under-reports.
- **No unreviewed publish** — `publisher_agent` runs only after the
  compliance gate AND a human approval; it reads from the pre-gate
  stash, never LLM context, and fails closed.
- **Silence never publishes** — manager (8h), legal (24h) and CMO (8h):
  a review nobody answers closes its card; nothing is published or
  approved and nobody is chased automatically. `operator_ids`
  left unset → tasks land in the shared Studio inbox (a placeholder
  email would make them invisible).
- **Crisis-pause floor** — `@chain enforce_crisis_floor` forces
  `requires_cmo_action=true` in crisis mode (a crisis always reaches the
  CMO), recomputes the severe-negative-spike rule from the rollups rather
  than trusting the LLM, forces legal into the route on
  regulatory/data-breach; a campaign-tied negative signal below the CMO
  floor routes to the marketing manager so the live campaign can be
  paused.
- **Bounded rework** — `needs_market_intelligence` prevents the
  strategist ↔ analyst ping-pong; human `revise` is the only back-edge.
- **WORM audit** — hash-chained record at every terminus.

## Configuration pointer

Three tiers — see README "Configuration": Tier 1 boot
(`LEAFMESH_LICENSE_KEY`, `LEAFMESH_ENV_TOKEN`, `OPENAI_API_KEY`;
`ANTHROPIC_API_KEY` optional for `social_media_agent` + Summarizer),
Tier 2 host + escalation adapters (Redis, `SLACK_MARKETING_CHANNEL`,
vault connection `escalation_webhook` for the commented webhook target; Slack
credentials go in the vault and need a Slack adapter wired in code), Tier 3
connectors (vault connections `analytics_n8n` and `map_n8n`, already picked by
the two n8n agents' `connector_config`; `cdp_mcp` / `intel_mcp` for the
commented `mcp:` block; social-listening + scheduler are webhook/connector, no
env var).

## Reflection / decisions

- **Two analyst/guardian merges (Rule 2).** `market_intelligence` is
  one role spanning audience + competitor intel; `brand_guardian` is
  one role spanning sentiment-spike tracking + crisis response. Neither
  thin half justified a separate job title.
- **State out of the template.** Sentiment, page-score, and scheduling
  SQLite ledgers were removed — metrics live in the analytics platform,
  sentiment in the social-listening platform, the calendar in the social
  scheduler, reached via connectors / ingest entry points. The remaining
  template storage is a dev stand-in only: the in-process session stash
  (HITL bridge), the WORM audit log (dev stub for S3 Object Lock /
  Splunk), and `agency/_shared/store.py` — the seeded context store the
  `@pre_compose` processors read so the chain runs day-0 before any
  connector is wired (production swaps the reads for connector calls).
- **Self-reliance + deterministic floors, by necessity.** Four LLM roles
  gained modules because the role genuinely needs hands: the strategist,
  analyst, and copywriter pull their OWN planning context
  (`@pre_compose`) and enforce floors the LLM must not waive
  (`@chain`) — spend ceiling, competitor-threat escalation, banned-term
  self-check; the brand guardian enforces the crisis-pause route; the
  compliance reviewer scans the actual copy and stashes pre-gate; the
  publisher is a paid actuator that fails closed; the audit logger is the
  tamper-evident terminus. `visual_briefer`, `social_media`, and
  `aeo_geo_optimiser` stayed pure-YAML — their rules are fully expressible
  in the prompt and need no context-pull or floor.
- **Slack escalation is honest about its gap.** The Slack escalation
  target ships commented: it needs a Slack channel adapter (its
  credentials live in the vault) — flagged in `env` and the README, not
  sold as plug-and-play.
- **Unproven runtime mechanics** flagged for a live smoke test: the
  `@chain` receiving the session transcript across a HITL resume, and
  the n8n connectors' real round-trip shape. A real `start()` proves the
  config loads under the real SDK; it does not prove these.
