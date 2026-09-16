# Orchestrator agent

This package is the control boundary between an AI decision-maker and FAAH's
workers. The AI creates a `DecisionProposal`; it never calls a worker or edits
configuration directly. `OrchestratorPolicy` either rejects the proposal or
turns it into an approved `Instruction`.

## Memory

The initial implementation stores compact memory in
`data/orchestrator_memory.json` (override with `ORCHESTRATOR_MEMORY_PATH`). It
contains:

- current goals and durable facts;
- the latest 200 approved and rejected decisions;
- aggregate success, failure, duration and throughput metrics per worker.

This is deliberately not a full chat transcript. The model should receive only
the goals, relevant facts, recent decisions and aggregate metrics on each
decision cycle. Worker reports provide the feedback needed to evaluate whether
prior instructions improved performance.

## Example

```python
from config.rss_feeds import RSS_FEEDS
from orchestrator_agent import ActionType, DecisionProposal, Orchestrator
from orchestrator_agent.policy import OrchestratorPolicy

agent = Orchestrator(
    OrchestratorPolicy(allowed_feeds=frozenset(feed.name for feed in RSS_FEEDS))
)

instruction = await agent.submit(
    DecisionProposal(
        action=ActionType.SET_RSS_INTERVAL,
        target="Investing.com",
        parameters={"seconds": 300},
        reason="The last three polls contained time-sensitive market news.",
        confidence=0.84,
    )
)
```

The RSS worker is not wired to this queue yet. Its next integration step is to
wait for either its polling timeout or a message from `queue_for(feed.name)`,
apply an approved instruction, and return a `WorkerReport`.

For multiple processes or containers, retain the same schemas and policy but
replace `InstructionBus` with Redis and `JsonMemoryStore` with PostgreSQL.
