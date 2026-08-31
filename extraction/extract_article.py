import httpx
import trafilatura

from models import DataSource

async def extract_article(url: str) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.investing.com/",
    }

    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=True,
        timeout=20,
    ) as client:
        response = await client.get(url)

    if response.status_code != 200:
        print(
            "Article fetch failed:",
            response.status_code,
            url,
        )
        return None

    article = trafilatura.extract(
        response.text,
        include_comments=False,
        include_tables=False,
    )

    return article.strip() if article else None