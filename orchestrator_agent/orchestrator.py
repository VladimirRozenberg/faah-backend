"""Policy-gated orchestrator service."""

from orchestrator_agent.bus import InstructionBus
from orchestrator_agent.memory import JsonMemoryStore
from orchestrator_agent.history import OrchestratorHistoryRepository
from orchestrator_agent.policy import OrchestratorPolicy, PolicyRejected
from orchestrator_agent.schemas import (
    DecisionProposal,
    DecisionRecord,
    Instruction,
    WorkerReport,
)


class Orchestrator:
    def __init__(
        self,
        policy: OrchestratorPolicy,
        memory: JsonMemoryStore | None = None,
        bus: InstructionBus | None = None,
        history: OrchestratorHistoryRepository | None = None,
    ) -> None:
        self.policy = policy
        self.memory = memory or JsonMemoryStore()
        self.bus = bus or InstructionBus()
        self.history = history

    async def submit(
        self, proposal: DecisionProposal, *, cycle_id: int | None = None,
        position: int = 0,
    ) -> Instruction | None:
        """Validate, remember and publish an AI proposal."""

        try:
            instruction = self.policy.authorize(proposal)
        except PolicyRejected as exc:
            if self.history is not None and cycle_id is not None:
                await self.history.record_decision(
                    cycle_id, position, ord_approved=False, ord_status="rejected",
                    ord_rejection_reason=str(exc),
                )
            self.memory.record_decision(
                DecisionRecord(
                    proposal=proposal,
                    approved=False,
                    rejection_reason=str(exc),
                )
            )
            return None

        if self.history is not None and cycle_id is not None:
            await self.history.record_decision(
                cycle_id, position, ord_approved=True, ord_status="approved",
                ord_instruction_id=instruction.instruction_id,
            )
        self.memory.record_decision(
            DecisionRecord(
                proposal=proposal,
                approved=True,
                instruction_id=instruction.instruction_id,
            )
        )
        try:
            await self.bus.publish(instruction)
        except Exception as exc:
            if self.history is not None and cycle_id is not None:
                await self.history.session.rollback()
                await self.history.record_decision(
                    cycle_id, position, ord_status="failed", ord_error=str(exc),
                )
            raise
        if self.history is not None and cycle_id is not None:
            await self.history.record_decision(cycle_id, position, ord_status="applied")
        return instruction

    def report(self, report: WorkerReport) -> None:
        self.memory.record_worker_report(report)
