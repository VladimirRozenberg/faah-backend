import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from live_market.market_schemas import LiveWorkerStatus
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
            patch(
                "routers.health.get_live_worker_status",
                return_value=None,
            ),
        ):
            result = await health(request, UnavailableDatabase())

        self.assertEqual(result.status, "degraded")
        self.assertFalse(result.database.connected)
        self.assertEqual(result.live_market_worker.status, "down")
        self.assertFalse(result.live_market_worker.healthy)
        self.assertEqual(result.orchestrator.status, "degraded")
        self.assertTrue(result.orchestrator.running)
        self.assertEqual(result.portfolio_strategists.status, "degraded")
        self.assertEqual(result.rss_feeds.status, "degraded")
        self.assertEqual(result.rss_feeds.items, [])

    async def test_health_reports_worker_connection_and_subscribed_count(self):
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(background_tasks=[]))
        )
        worker_status = LiveWorkerStatus(
            running=True,
            connected=True,
            subscribed_assets=42,
            last_heartbeat_at=datetime.now(timezone.utc),
            last_quote_at=datetime.now(timezone.utc),
            quotes_received=128,
            live_prices=10,
            delayed_prices=20,
            unavailable_prices=12,
            error="Redis quote write failed (ConnectionError)",
        )

        with (
            patch.dict(
                "os.environ",
                {"RUN_ORCHESTRATOR": "false", "RUN_STRATEGISTS": "false"},
            ),
            patch(
                "routers.health.JsonMemoryStore.load",
                return_value=MemoryState(),
            ),
            patch(
                "routers.health.get_live_worker_status",
                return_value=worker_status,
            ),
        ):
            result = await health(request, UnavailableDatabase())

        self.assertEqual(result.live_market_worker.status, "running")
        self.assertTrue(result.live_market_worker.healthy)
        self.assertEqual(result.live_market_worker.subscribed_assets, 42)
        self.assertEqual(result.live_market_worker.quotes_received, 128)
        self.assertEqual(result.live_market_worker.live_prices, 10)
        self.assertEqual(result.live_market_worker.delayed_prices, 20)
        self.assertEqual(result.live_market_worker.unavailable_prices, 12)
        self.assertIsNotNone(result.live_market_worker.last_quote_at)
        self.assertEqual(
            result.live_market_worker.error,
            "Redis quote write failed (ConnectionError)",
        )


if __name__ == "__main__":
    unittest.main()
