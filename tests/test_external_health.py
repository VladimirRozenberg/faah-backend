import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

from external_health import CachedCheck, check_twelve, check_yahoo, twelve_result


class ExternalHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_readers_share_one_check(self):
        cache = CachedCheck(300)
        probe = AsyncMock(return_value=("connected", "OK"))
        results = await asyncio.gather(*(cache.get(probe) for _ in range(8)))
        self.assertEqual(probe.await_count, 1)
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(results[0]["cache_seconds"], 300)
        cache.expires = 0
        await cache.get(probe)
        self.assertEqual(probe.await_count, 2)

    async def test_failure_is_cached_without_leaking_exception(self):
        cache = CachedCheck(1800)
        probe = AsyncMock(side_effect=ValueError("secret-key"))
        result = await cache.get(probe)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("secret-key", str(result))
        await cache.get(probe)
        self.assertEqual(probe.await_count, 1)

    async def test_timeout_is_safe(self):
        result = await CachedCheck(300).get(AsyncMock(side_effect=TimeoutError))
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("time", result["detail"])

    async def test_missing_key_makes_no_request(self):
        with patch.dict(os.environ, {"TWELVE_DATA_API_KEY": ""}):
            self.assertEqual((await check_twelve())[0], "not_configured")

    async def test_yahoo_valid_empty_and_rate_limited(self):
        with patch("external_health._read_yahoo", return_value=True):
            self.assertEqual((await check_yahoo())[0], "connected")
        with patch("external_health._read_yahoo", return_value=False):
            self.assertEqual((await check_yahoo())[0], "unavailable")
        with patch("external_health._read_yahoo", side_effect=type("YFRateLimitError", (Exception,), {})()):
            self.assertEqual((await check_yahoo())[0], "rate_limited")

    async def test_twelve_responses(self):
        self.assertEqual(twelve_result(200, {"current_usage": 1, "plan_limit": 8})[0], "connected")
        for code in (401, 403):
            self.assertEqual(twelve_result(code, {})[0], "authentication_failed")
        self.assertEqual(twelve_result(429, {})[0], "rate_limited")
        self.assertEqual(twelve_result(200, {"status": "error", "code": 429})[0], "rate_limited")
        self.assertEqual(twelve_result(200, {"current_usage": 8, "plan_limit": 8})[0], "rate_limited")
        self.assertEqual(twelve_result(200, {"current_usage": 1, "plan_limit": 8,
                                            "daily_usage": 800, "plan_daily_limit": 800})[0], "rate_limited")
        self.assertEqual(twelve_result(200, {})[0], "unavailable")
        self.assertEqual(twelve_result(500, {})[0], "unavailable")


if __name__ == "__main__":
    unittest.main()
