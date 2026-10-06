# Frontend: orchestrator decision history

Use this endpoint to build the orchestrator history screen:

```http
GET /api/orchestrator/decisions?page=1&page_size=20
```

Use the existing backend base URL and API request setup. This GET only reads
history; it does not invoke the model or execute any actions. The backend's
history migration must be applied before the endpoint is available.

## Pagination

| Query parameter | Default | Accepted values |
| --- | --- | --- |
| `page` | 1 | Integer >= 1 |
| `page_size` | 20 | Integer from 1 through 100 |

The response uses the same envelope as news: `count`, `page`, `page_size`,
`items`. `count` counts **cycles**, not individual RSS proposals or jobs.
Items sort newest first by `started_at`, then `cycle_id`. One item is one cycle
and contains its RSS decisions and newly created research jobs.

Calculate `totalPages = Math.ceil(count / page_size)`. Disable Previous on page
1 and Next when `page * page_size >= count`. Reset page to 1 when changing page
size. An out-of-range page returns HTTP 200 with empty `items` and the unchanged
`count`; invalid query values return HTTP 422. New cycles can shift page contents,
so replace each fetched page rather than appending it as though it were a cursor.
There are currently no search, date, source, or status filter parameters.

## Example response

Illustrative IDs and content; the field names match the actual response model.

```json
{
  "count": 1,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "cycle_id": 42,
      "source": "background",
      "started_at": "2026-10-06T10:00:00Z",
      "completed_at": "2026-10-06T10:00:08Z",
      "signal_window_start": "2026-10-06T09:00:00Z",
      "prompt_id": 120,
      "model": "qwen3.8-flash",
      "status": "completed",
      "error": null,
      "history_complete": true,
      "signal_ids": [501],
      "situation_summary": "New evidence requires a focused follow-up.",
      "follow_up_analysis": [
        {
          "asset_symbol": "AAPL",
          "question": "Has the new announcement changed the outlook?",
          "reason": "The previous evidence predates the announcement.",
          "priority": 4
        }
      ],
      "next_instructions": "Review the follow-up result when available.",
      "next_run_in_seconds": 600,
      "next_run_at": "2026-10-06T10:10:00Z",
      "rejected_rss_proposals": 0,
      "rss_decisions": [
        {
          "decision_id": 73,
          "feed_id": 3,
          "proposal": {
            "action": "set_rss_interval",
            "target": "Markets",
            "parameters": {"seconds": 600},
            "reason": "Monitor updates while research is unresolved.",
            "confidence": 0.8
          },
          "approved": true,
          "status": "applied",
          "rejection_reason": null,
          "error": null,
          "instruction_id": "11111111-1111-4111-8111-111111111111"
        }
      ],
      "follow_up_jobs": [
        {
          "job_id": 88,
          "asset_id": 10,
          "asset_symbol": "AAPL",
          "question": "Has the new announcement changed the outlook?",
          "reason": "The previous evidence predates the announcement.",
          "priority": 4,
          "status": "pending",
          "result_analysis_id": null,
          "result_summary": null,
          "result_text": null,
          "error": null,
          "requested_at": "2026-10-06T10:00:05Z",
          "started_at": null,
          "completed_at": null
        }
      ]
    }
  ]
}
```

## What to display

Use `cycle_id` as the stable UI key. Display the time, source, status, and
`situation_summary` in each list item; expand it for RSS proposals, requested
research, current job states, next-run time, and `next_instructions`.

- `source` is `background` or `test`. Test cycles come from the Swagger test-run
  endpoint; show that distinction. Both sources are included in pagination.
- Cycle `status` is `applying`, `completed`, `failed`, or `legacy`.
- `completed` means the orchestrator finished handling its decisions. Research
  jobs may still be pending/running, and policy-rejected proposals may be present.
- Display `error` when a cycle failed. Earlier actions may already have succeeded.
- `next_run_at` is the historical planned next time, not the current live scheduler
  deadline. Format ISO timestamps in the viewer's local timezone.
- `signal_ids` identifies the signals considered in this cycle. This endpoint
  does not embed signal details.
- `prompt_id` and `model` can be null for imported history. `completed_at` can be
  null for an applying/interrupted cycle or imported history.

For each `rss_decisions` entry, display `proposal.action`, `proposal.target`,
`proposal.reason`, `proposal.confidence`, parameters, and status. Confidence is
0–1; multiply by 100 to display a percentage. Supported actions:
`set_rss_interval`, `run_rss_now`, `pause_rss`, `resume_rss`. Only
`set_rss_interval` uses `parameters.seconds`; the other actions have `{}`.

| RSS decision status | Meaning for the UI |
| --- | --- |
| `pending` | Proposal has not been evaluated |
| `rejected` | Policy rejected it; display `rejection_reason` |
| `approved` | Passed policy; application is not confirmed |
| `applied` | Schedule change was persisted |
| `failed` | Applying the approved action failed; display `error` |
| `legacy_approved` | Imported approval; actual application result is unknown |

`approved` can be null while evaluation is pending. A true value does not imply
application succeeded. `feed_id` can be null for unknown/rejected or deleted
feeds; the historical target name remains available in `proposal.target`.
`instruction_id` is null for proposals that were never approved.
An `applied` schedule change does not imply the subsequent RSS run succeeded.

`follow_up_analysis` holds all questions requested by the model, with priority
1–5 (5 is highest). `follow_up_jobs` holds only jobs actually created by this
cycle, with their **current** statuses (`pending`, `running`, `succeeded`,
`failed`). The arrays can have different lengths because duplicate/active
requests or unknown assets can prevent a new job from being created.
Use `job_id` as the job key. Link to the existing analysis screen when
`result_analysis_id` is non-null. The paginated history currently returns
`result_summary` and `result_text` as null; obtain analysis content through the
existing analysis API. Timeout failures use the normal `failed` status and an
error such as `Job exceeded the 10-minute execution limit`.

Show a "Partial historical record" indicator when `history_complete` is false.
Old JSON imports may preserve a rejected count without all individual rejection
details. Do not infer applied outcomes from legacy approvals or derive the
rejected count solely from the RSS array; use `rejected_rss_proposals`.

## Loading and errors

Show an initial loading state, an empty-history state when `count` is zero, and
an error state with Retry when the request fails. Keep request failures distinct
from cycles/jobs with status `failed`, which are valid data. Ignore or cancel
older in-flight requests when the page changes. A manual Refresh refetches the
current page and updates the live job states. This API does not stream updates.

## Related endpoints

- `GET /api/orchestrator/analysis-jobs`: job list including result content; uses
  the existing `limit` parameter rather than this pagination envelope.
- `GET /api/orchestrator/rss-feed-runs`: actual RSS execution results.
- `POST /api/orchestrator/test-run`: runs the model and applies approved changes;
  its response now includes `cycle_id`. Do not call it to load or refresh history.

Backend setup and the migration/import commands are documented in
[HISTORY_SCHEMA.md](HISTORY_SCHEMA.md).
