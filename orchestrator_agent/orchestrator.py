"""Policy-gated orchestrator service."""

from orchestrator_agent.bus import InstructionBus
from orchestrator_agent.memory import JsonMemoryStore
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
    ) -> None:
        self.policy = policy
        self.memory = memory or JsonMemoryStore()
        self.bus = bus or InstructionBus()

    async def submit(self, proposal: DecisionProposal) -> Instruction | None:
        """Validate, remember and publish an AI proposal."""

        try:
            instruction = self.policy.authorize(proposal)
        except PolicyRejected as exc:
            self.memory.record_decision(
                DecisionRecord(
                    proposal=proposal,
                    approved=False,
                    rejection_reason=str(exc),
                )
            )
            return None

        self.memory.record_decision(
            DecisionRecord(
                proposal=proposal,
                approved=True,
                instruction_id=instruction.instruction_id,
            )
        )
        await self.bus.publish(instruction)
        return instruction

    def report(self, report: WorkerReport) -> None:
        self.memory.record_worker_report(report)
