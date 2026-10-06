"""Import retained JSON history without running the model or applying actions.

Run after the history migration, with the application's database environment:
    python -m orchestrator_agent.import_history
    python -m orchestrator_agent.import_history --source test --memory-path data/orchestrator_swagger_memory.json
"""

import argparse
import asyncio

from db import AsyncSessionLocal, engine
from orchestrator_agent.history import OrchestratorHistoryRepository
from orchestrator_agent.memory import JsonMemoryStore


async def import_history(memory_path: str | None, source: str) -> None:
    state = JsonMemoryStore(memory_path).load()
    try:
        async with AsyncSessionLocal() as db:
            await OrchestratorHistoryRepository(db, source=source).import_memory(state)
        print(f"Imported retained {source} history ({len(state.cycles)} cycles considered).")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-path", default=None)
    parser.add_argument("--source", choices=("background", "test"), default="background")
    args = parser.parse_args()
    asyncio.run(import_history(args.memory_path, args.source))


if __name__ == "__main__":
    main()
