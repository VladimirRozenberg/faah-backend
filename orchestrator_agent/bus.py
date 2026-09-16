"""In-process delivery of approved instructions to workers."""

import asyncio

from orchestrator_agent.schemas import Instruction


class InstructionBus:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Instruction]] = {}

    def queue_for(self, worker: str) -> asyncio.Queue[Instruction]:
        return self._queues.setdefault(worker, asyncio.Queue())

    async def publish(self, instruction: Instruction) -> None:
        await self.queue_for(instruction.target).put(instruction)
