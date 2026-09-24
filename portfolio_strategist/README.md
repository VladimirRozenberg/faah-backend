# Opportunity service and portfolio strategists

This first demo separates cheap market detection from portfolio-specific LLM
judgment.

## Runtime flow

Every minute the service:

1. Ensures every active portfolio has one strategist and every held asset is live-tracked.
2. Compares each tracked asset's latest Redis quote with the previous sample.
3. At a configurable movement threshold (2% by default), persists one market event.
4. Researches that price event once with Qwen web search.
5. Queues targeted checks for strategists whose portfolios hold the affected asset.
6. Finds new buy, sell and hold signals. Held-asset signals always queue a targeted
   check; an unowned buy signal may queue when it shares a niche with a holding and
   its analysis risk fits the portfolio.
7. Queues a full portfolio-and-ideas review every two hours.
8. Executes focused research requested by prior strategist reviews.
9. Executes bounded strategist reviews and stores each result as a portfolio analysis.

Price events in the same direction have a 15-minute cooldown. Signal and event
review rows are unique per strategist, so repeated service passes do not duplicate
work. The demo is advisory-only and never creates a transaction.

## Database and configuration

Apply the migration before enabling the runtime:

```bash
psql -v ON_ERROR_STOP=1 -f migrations/20260924_create_portfolio_strategists.sql
```

Then configure:

```text
RUN_STRATEGISTS=true
OPPORTUNITY_PRICE_MOVE_PCT=2.0
```

`RUN_STRATEGISTS` defaults to false. The threshold must be positive and defaults to
2%. A first quote establishes the baseline and does not create an event.

## Inspection and demo controls

```text
GET  /api/strategists
GET  /api/strategists/events
GET  /api/strategists/runs
POST /api/strategists/portfolios/{portfolio_id}/full-review
```

The POST endpoint queues a full review. The background strategist service performs
it on its next pass, provided `RUN_STRATEGISTS=true`.

## Review modes

- `targeted_signal`: short check using the signal's existing analysis.
- `targeted_price`: short check after shared web research explains a price event.
- `full`: two-hour assessment of every holding and recent strategist ideas, with web
  search enabled and permission to request focused follow-up research.

Full responses must cover every current holding. Targeted responses must provide
an explicit `no_action`, `watch`, `opportunity`, `warning`, or `follow_up`
conclusion. Python rejects unknown assets, duplicate holding assessments and
invented signal references before saving a result.
