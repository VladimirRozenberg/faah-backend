import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from ingestion.feed_http import (
    FeedAccessError,
    REQUEST_HEADERS,
    fetch_feed_content,
    request_headers,
)


class FeedHTTPTests(unittest.IsolatedAsyncioTestCase):
    def test_government_feeds_require_identification(self):
        with patch.dict(os.environ, {}, clear=True):
            for url in ('https://www.sec.gov/feed', 'https://www.bls.gov/feed'):
                with self.subTest(url=url):
                    with self.assertRaisesRegex(FeedAccessError, 'SEC_USER_AGENT'):
                        request_headers(url)

    def test_identity_is_only_sent_to_sec_and_bls(self):
        identity = 'FAAH test@example.com'
        with patch.dict(os.environ, {'SEC_USER_AGENT': identity}):
            for url in ('https://www.sec.gov/feed', 'https://www.bls.gov/feed'):
                with self.subTest(url=url):
                    self.assertEqual(request_headers(url)['User-Agent'], identity)
            for url in ['https://example.com/feed', 'https://sec.gov.example.com/feed']:
                self.assertEqual(request_headers(url), REQUEST_HEADERS)

    async def fetch_with_status(self, status, content=b'feed'):
        response = httpx.Response(
            status, content=content,
            request=httpx.Request('GET', 'https://www.bls.gov/feed'),
        )
        with (
            patch.dict(os.environ, {'SEC_USER_AGENT': 'FAAH test.com'}),
            patch('ingestion.feed_http.httpx.AsyncClient') as client,
        ):
            client.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=response
            )
            return await fetch_feed_content('https://www.bls.gov/feed')

    async def test_forbidden_is_an_access_failure_not_empty_success(self):
        with self.assertRaisesRegex(FeedAccessError, 'HTTP 403'):
            await self.fetch_with_status(403)

    async def test_other_http_errors_are_preserved(self):
        with self.assertRaises(httpx.HTTPStatusError):
            await self.fetch_with_status(500)

    async def test_success_returns_feed(self):
        self.assertEqual(await self.fetch_with_status(200), b'feed')
