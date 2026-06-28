# marketing-ops — example scenarios

Four realistic scenarios that exercise the major paths through this mesh.

## How to run

```bash
python examples/run_examples.py                 # all scenarios
python examples/run_examples.py 01_             # one scenario (substring match)
```

## Scenario map

- **01_new_campaign_brief** — `new_brief` — Marketing manager files brief for spring product launch — full chain through strategist (brief normalised) → market intelligence → strategy → copy + visual → compliance → approval → publish.
- **02_product_launch_kickoff** — `product_launch` — Product team triggers cross-functional launch — campaign_strategist anchors, market_intelligence (audience + competitor) feeds in.
- **03_brand_crisis** — `crisis_response` — PR signal — bad press cycle starts. brand_guardian drafts holding statement, escalates to CMO + legal.
- **04_competitor_pricing_move** — `competitor_move` — Competitor cut prices 20% — market_intelligence scans the move, recommends defensive/offensive posture.

## Audit trail

Every scenario appends one hash-chained entry to the template's
`logs/<audit>.jsonl` file. Tail it during a run to see the
ledger build up across scenarios.
