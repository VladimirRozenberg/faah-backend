"""Keep model context bounded while retaining the original database records."""

from collections import defaultdict

from orchestrator_agent.schemas import CycleContext

MAX_CONTEXT_BYTES = 120_000
MAX_SIGNALS = 200
MAX_HISTORY = 150
MAX_HISTORY_PER_ASSET = 3
MAX_FOLLOW_UPS = 30


def bounded_context(context: CycleContext) -> CycleContext:
    """Prefer recent evidence and active research, and disclose omissions."""
    result = context.model_copy(deep=True)
    original_counts = {
        key: len(getattr(result, key)) + result.context_limits.get(f"{key}_omitted", 0)
        for key in ("signals", "analysis_history", "follow_up_jobs")
    }
    clipped = 0

    def clip(value: str | None, limit: int) -> str | None:
        nonlocal clipped
        if value is not None and len(value) > limit:
            clipped += 1
            marker = " [truncated]"
            return value[:limit - len(marker)] + marker
        return value

    result.previous_instructions = clip(result.previous_instructions, 4_000)
    result.signals = sorted(
        result.signals, key=lambda item: (item.created_at, item.signal_id), reverse=True
    )[:MAX_SIGNALS]
    for signal in result.signals:
        signal.generating_analysis_summary = clip(signal.generating_analysis_summary, 800)

    # The same multi-asset analysis can occur many times in the history query.
    # Keep one summary and disclose every asset link in a separate small mapping.
    links = defaultdict(set)
    for analysis_id, asset_ids in result.analysis_asset_ids.items():
        links[analysis_id].update(asset_ids)
    for item in result.analysis_history:
        links[item.analysis_id].add(item.asset_id)
    source_ids = {signal.analysis_id for signal in result.signals}
    history = sorted(
        result.analysis_history,
        key=lambda item: (item.analysis_id in source_ids, item.created_at, item.analysis_id),
        reverse=True,
    )
    seen = set()
    per_asset = defaultdict(int)
    result.analysis_history = []
    for item in history:
        if item.analysis_id in seen or per_asset[item.asset_id] >= MAX_HISTORY_PER_ASSET:
            continue
        item.summary = clip(item.summary, 800)
        result.analysis_history.append(item)
        seen.add(item.analysis_id)
        per_asset[item.asset_id] += 1
        if len(result.analysis_history) >= MAX_HISTORY:
            break

    result.follow_up_jobs = sorted(
        result.follow_up_jobs,
        key=lambda item: (item.status in ("pending", "running"), item.requested_at, item.job_id),
        reverse=True,
    )[:MAX_FOLLOW_UPS]
    for job in result.follow_up_jobs:
        job.question = clip(job.question, 600)
        job.reason = clip(job.reason, 600)
        job.result_summary = clip(job.result_summary, 1_000)
        if job.result_text:
            clipped += 1
            job.result_text = None
        job.error = clip(job.error, 400)

    def update_limits():
        result.analysis_asset_ids = {
            item.analysis_id: sorted(links[item.analysis_id])
            for item in result.analysis_history
        }
        result.context_limits.update({
            f"{key}_omitted": original_counts[key] - len(getattr(result, key))
            for key in original_counts
        })
        result.context_limits["text_fields_truncated"] = (
            context.context_limits.get("text_fields_truncated", 0) + clipped
        )

    update_limits()
    while len(result.model_dump_json().encode("utf-8")) > MAX_CONTEXT_BYTES:
        # Preserve signal summaries before supplementary history and completed jobs.
        if result.analysis_history:
            result.analysis_history.pop()
        elif result.follow_up_jobs and result.follow_up_jobs[-1].status not in ("pending", "running"):
            result.follow_up_jobs.pop()
        elif len(result.signals) > 1:
            result.signals.pop()
        elif result.follow_up_jobs:
            result.follow_up_jobs.pop()
        else:
            raise ValueError("RSS schedule and required context exceed the model context budget")
        update_limits()
    return result
