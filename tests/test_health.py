import unittest
from types import SimpleNamespace
from unittest.mock import patch

from orchestrator_agent.schemas import MemoryState
from routers.health import health


class FakeTask:
    def __init__(self, name: str, done: bool = False):
        self.name = name
        self.is_done = done

    def get_name(self) -> str:
        return self.name

    def done(self) -> bool:
        return self.is_done


class UnavailableDatabase:
    async def execute(self, _statement):
        raise ConnectionError("database is unavailable")


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_failure_returns_degraded_snapshot(self):
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    background_tasks=[
                        FakeTask("faah-orchestrator"),
                        FakeTask("faah-portfolio-strategists"),
                    ]
                )
            )
        )

        with (
            patch.dict(
                "os.environ",
                {"RUN_ORCHESTRATOR": "true", "RUN_STRATEGISTS": "true"},
            ),
            patch(
                "routers.health.JsonMemoryStore.load",
                return_value=MemoryState(),
            ),
        ):
            result = await health(request, UnavailableDatabase())

        self.assertEqual(result.status, "degraded")
        self.assertFalse(result.database.connected)
        self.assertEqual(result.orchestrator.status, "degraded")
        self.assertTrue(result.orchestrator.running)
        self.assertEqual(result.portfolio_strategists.status, "degraded")
        self.assertEqual(result.rss_feeds.status, "degraded")
        self.assertEqual(result.rss_feeds.items, [])


if __name__ == "__main__":
    unittest.main()
