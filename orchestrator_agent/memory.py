"""Simple durable memory for a single application instance."""

import json
import os
from pathlib import Path

from orchestrator_agent.schemas import (
    DecisionRecord,
    MemoryState,
    WorkerMetrics,
    WorkerReport,
    utc_now,
)


class JsonMemoryStore:
    """Persist compact state atomically; suitable for the first local version."""

    def __init__(self, path: str | Path | None = None, max_decisions: int = 200):
        configured_path = path or os.getenv(
            "ORCHESTRATOR_MEMORY_PATH", "data/orchestrator_memory.json"
        )
        self.path = Path(configured_path)
        self.max_decisions = max_decisions

    def load(self) -> MemoryState:
        if not self.path.exists():
            return MemoryState()
        return MemoryState.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, state: MemoryState) -> None:
        state.updated_at = utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.path)

    def record_decision(self, record: DecisionRecord) -> None:
        state = self.load()
        state.decisions.append(record)
        state.decisions = state.decisions[-self.max_decisions :]
        self.save(state)

    def record_worker_report(self, report: WorkerReport) -> None:
        state = self.load()
        metrics = state.worker_metrics.setdefault(report.worker, WorkerMetrics())
        metrics.runs += 1
        metrics.successes += int(report.success)
        metrics.failures += int(not report.success)
        metrics.items_processed += report.items_processed
        metrics.total_duration_ms += report.duration_ms
        self.save(state)
