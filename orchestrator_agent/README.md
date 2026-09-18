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
```

The migration creates and seeds `rss_feeds` and creates `rss_feed_runs`. It does
not replace existing assets, sources, analyses or signals.

## Swagger inspection

The following endpoints make scheduling and execution state visible:

```text
GET  /api/orchestrator/rss-feeds
GET  /api/orchestrator/rss-feed-runs
GET  /api/orchestrator/analysis-jobs
POST /api/orchestrator/test-run
```

The test-run endpoint reads real database signals and uses the same Alibaba/Qwen
client and `FAAH_ALIBABA_ANALYSIS_MODEL` setting as financial analysis. Its
approved RSS instructions are persisted immediately to `rss_feeds`.

## Background service

Set this only after the database migration has been applied:

```text
RUN_ORCHESTRATOR=true
```

FastAPI lifespan then starts one `faah-orchestrator` task. It replaces the old
per-feed RSS task fan-out. Keep this disabled until the fault-handling policy is
agreed: failures are currently recorded, but retry/backoff, stale-claim recovery,
and multi-process leader election are intentionally not finalized.

Compact Qwen handoff memory is still stored in
`data/orchestrator_memory.json` (override with `ORCHESTRATOR_MEMORY_PATH`). Feed
configuration, feed scheduling, instruction effects and run history are stored
in PostgreSQL.
