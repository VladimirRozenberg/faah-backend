"""HTTP access for RSS feeds, independent of database and LLM clients."""

import os
from urllib.parse import urlsplit

import httpx


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}


class FeedAccessError(RuntimeError):
    """The feed needs configuration or its server denied access."""


def request_headers(feed_url: str) -> dict[str, str]:
    headers = REQUEST_HEADERS.copy()
    host = urlsplit(feed_url).hostname or ""
    identified_hosts = ("sec.gov", "bls.gov")
    if any(
        host == domain or host.endswith(f".{domain}")
        for domain in identified_hosts
    ):
        user_agent = os.getenv("SEC_USER_AGENT", "").strip()
        if not user_agent:
            raise FeedAccessError(
                "SEC and BLS requests require SEC_USER_AGENT with your app "
                "name and a real contact email; configure it in .env and "
                "recreate the app"
            )
        headers["User-Agent"] = user_agent
    return headers


async def fetch_feed_content(feed_url: str) -> bytes:
    async with httpx.AsyncClient(
        headers=request_headers(feed_url),
        follow_redirects=True,
        timeout=20.0,
    ) as client:
        response = await client.get(feed_url)
        if response.status_code == 403:
            raise FeedAccessError(
                f"HTTP 403: feed server denied access to {feed_url}; "
                "no articles were fetched"
            )
        response.raise_for_status()
        return response.content
