"""Model-backed judgment for one orchestration cycle."""

from __future__ import annotations

import json
import os
from typing import Protocol

from orchestrator_agent.schemas import BrainResult, CycleContext, CycleDecision


DEFAULT_MODEL = "qwen3.8-flash"

SYSTEM_INSTRUCTIONS = """You are FAAH's supervisory market-research orchestrator.
Review every new trading signal and all supplied historical analysis summaries for
the affected assets. Apply a skeptical sniff test: look for stale evidence,
contradictions, missing catalysts, weak confidence, unsupported precision,
one-source dependence, and risks that could invalidate a signal. Request focused
follow-up analysis only where it can materially improve a decision.

The follow_up_jobs field shows research previously requested from the analysis
worker. Do not repeat a question while a matching job is pending or running.
When a job succeeded, use its result_text and result_summary to resolve the
issue and request a new follow-up only if a distinct material uncertainty
remains. Failed jobs may be retried only when the question is still important.

You may propose RSS controls only for feeds in allowed_rss_feeds. Poll faster for
time-sensitive unresolved events, slower when a feed is low value, and do not
create activity merely because you can. A proposal is advisory and will pass a
deterministic policy gate. Never propose or execute a trade. Finish with concise
instructions for the next orchestrator instance, including what it should
re-check. Return JSON only, conforming exactly to the supplied schema."""

RSS_ACTION_CONTRACT = """RSS ACTION CONTRACT
You may use only the following exact forms:

1. Run a configured feed immediately:
   {"action":"run_rss_now","target":"<allowed feed>","parameters":{},
    "reason":"<why>","confidence":0.80}

2. Change a configured feed's polling interval:
   {"action":"set_rss_interval","target":"<allowed feed>",
    "parameters":{"seconds":<integer from 300 through 7200>},
    "reason":"<why>","confidence":0.80}

3. Stop polling a configured feed:
   {"action":"pause_rss","target":"<allowed feed>","parameters":{},
    "reason":"<why>","confidence":0.80}

4. Resume polling a configured feed:
   {"action":"resume_rss","target":"<allowed feed>","parameters":{},
    "reason":"<why>","confidence":0.80}

The minimum interval is 5 minutes (300 seconds) and the maximum interval for an
inactive or low-value feed is 2 hours (7200 seconds). All non-interval actions
must use an empty parameters object. Feeds cannot accept ticker, keyword, query,
category, or URL parameters. Inspect rss_feed_states before proposing anything:
do not repeat a pending run, set an interval that is already in effect, pause an
already-paused feed, or resume an active feed. Never invent an action, feed, or
parameter. Only propose actions with confidence from 0.60 through 1.00. Only
refer to an RSS action in next_instructions if you proposed it in rss_proposals."""

ORCHESTRATOR_SCHEDULE_CONTRACT = """NEXT ORCHESTRATOR RUN
Set next_run_in_seconds to an integer from 300 through 7200. Use a shorter delay
when signals have urgent unresolved evidence and a longer delay when there are no
new signals or no time-sensitive follow-ups. This field is the final scheduling
instruction for when the orchestrator should run again."""


class OrchestrationBrain(Protocol):
    async def decide(self, context: CycleContext) -> BrainResult: ...


def parse_cycle_decision(content: str | None) -> CycleDecision:
    if not content or not content.strip():
        raise ValueError("Orchestration model returned empty output")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json")
        cleaned = cleaned.removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    return CycleDecision.model_validate(json.loads(cleaned, strict=False))


class LLMOrchestrationBrain:
    """Use the same Alibaba/Qwen setup as FAAH's financial analysis."""

    def __init__(self, model: str | None = None) -> None:
        configured = model or os.getenv("FAAH_ALIBABA_ANALYSIS_MODEL", DEFAULT_MODEL)
        self.model = configured.strip() or DEFAULT_MODEL

    async def decide(self, context: CycleContext) -> BrainResult:
        from prompt.llm_client import get_alibaba_client

        model_input = (
            "CYCLE CONTEXT\n"
            f"{context.model_dump_json(indent=2)}\n\n"
            f"{RSS_ACTION_CONTRACT}\n\n"
            f"{ORCHESTRATOR_SCHEDULE_CONTRACT}\n\n"
            "REQUIRED OUTPUT JSON SCHEMA\n"
            f"{json.dumps(CycleDecision.model_json_schema(), indent=2)}"
        )
        response = await get_alibaba_client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": model_input},
            ],
            max_tokens=20_000,
            response_format={"type": "json_object"},
            extra_body={
                "enable_search": True,
                "search_options": {"search_strategy": "turbo"},
                "enable_thinking": False,
            },
        )
        content = response.choices[0].message.content
        return BrainResult(
            decision=parse_cycle_decision(content),
            model=self.model,
            raw_content=content or "",
            provider_response=response.model_dump(mode="json"),
        )
