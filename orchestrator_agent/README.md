# Orchestrator agent

The orchestrator is now the single owner of RSS scheduling. PostgreSQL—not
`config/rss_feeds.py` and not one asyncio loop per feed—is the source of truth.

## Runtime flow

1. The service claims feeds whose `rsf_next_poll_at` is due.
2. The generic executor ingests and analyzes each claimed feed.
3. Each attempt is recorded in `rss_feed_runs`.
4. When the Qwen cycle is due, it reads new signals, their prior analysis
   summaries, and the complete current RSS schedule from PostgreSQL.
5. Policy-approved Qwen instructions update `rss_feeds` through SQLAlchemy.
6. `run_rss_now` becomes immediately due; normal interval changes, pause and
   resume operations are visible directly in the database.
7. Qwen's `next_run_in_seconds` schedules the next decision cycle.

Targeted items in `follow_up_analysis` are persisted in
`orchestrator_analysis_jobs`. The background service executes them with a
dedicated research prompt that includes the asset's prior analyses and current
price context. The resulting analysis is linked to its input analyses through
`analysis_inputs` and returned to the next orchestrator cycle. Follow-up jobs do
not create trading signals directly.

RSS executions and follow-up analysis jobs have a 10-minute execution limit.
Overdue work is cancelled and recorded as failed with a timeout error; the
executor continues to the next job. Each service pass also marks running
records older than 10 minutes as failed, including abandoned claims from a
previous deployment. Already committed ingestion results are retained.

Signal windows overlap the previous cycle by five minutes. This deliberately
replays signals near a cycle boundary so a transaction committed around the
cutoff cannot be missed. Persistent unresolved follow-ups are a separate state
concern and are not solved by this overlap.

The RSS action contract allows intervals from 300 seconds (5 minutes) through
7,200 seconds (2 hours). Feeds do not accept ticker, query, category, URL or
other arbitrary parameters.

## Database setup

Fresh databases use the definitions and seed rows in `faah_postgres_schema.sql`.
For an existing database, apply:

```bash
psql -v ON_ERROR_STOP=1 -f migrations/20260918_create_rss_scheduler.sql
psql -v ON_ERROR_STOP=1 -f migrations/20260918_create_orchestrator_analysis_jobs.sql
psql -v ON_ERROR_STOP=1 -f migrations/20261006_create_orchestrator_history.sql
```

The migration creates and seeds `rss_feeds` and creates `rss_feed_runs`. It does
not replace existing assets, sources, analyses or signals.

## Swagger inspection

The following endpoints make scheduling and execution state visible:

```text
GET  /api/orchestrator/rss-feeds
GET  /api/orchestrator/rss-feed-runs
GET  /api/orchestrator/analysis-jobs
GET  /api/orchestrator/decisions?page=1&page_size=20
POST /api/orchestrator/test-run
```

The test-run endpoint reads real database signals and uses the same Alibaba/Qwen
client and `FAAH_ALIBABA_ANALYSIS_MODEL` setting as financial analysis. Its
approved RSS instructions are persisted immediately to `rss_feeds`.

Decision history uses the same `count`, `page`, `page_size`, and `items` response
as news. Each item is one cycle, newest first. Page size defaults to 20 and is
capped at 100. PostgreSQL retains the cycles and individual RSS policy/application
outcomes; follow-up jobs link to the requesting cycle. Production and test-run
cycles are distinguished by `source`. Test-run responses also include `cycle_id`.
See [HISTORY_SCHEMA.md](HISTORY_SCHEMA.md) for the exact foreign keys, ER diagram,
status meanings, and legacy import instructions.
Frontend integration instructions and a complete example response are in
[FRONTEND_API.md](FRONTEND_API.md).

## Background service

Set this only after the database migration has been applied:

```text
RUN_ORCHESTRATOR=true
```

FastAPI lifespan then starts one `faah-orchestrator` task. It replaces the old
per-feed RSS task fan-out. Unexpected database, model, validation, and memory
errors are logged with their traceback and retried with exponential backoff from
5 to 60 seconds. Deployment cancellation is propagated immediately.
Multi-process leader election is not yet finalized.

Compact Qwen handoff memory is still stored in
`data/orchestrator_memory.json` (override with `ORCHESTRATOR_MEMORY_PATH`). Feed
configuration, feed scheduling, instruction effects and run history are stored
in PostgreSQL, along with durable decision history. Retained JSON cycles are
imported idempotently before the next decision cycle. JSON retention limits no
longer limit the PostgreSQL history. No historical actions are replayed.
