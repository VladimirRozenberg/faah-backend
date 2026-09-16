from dataclasses import dataclass


@dataclass
class RSSFeed:
    name: str
    url: str
    poll_interval: int  # in seconds
    source_prefix: str = ""  # Optional prefix for source identification


RSS_FEEDS = [
    RSSFeed(
        name="Investing.com",
        url="https://www.investing.com/rss/news_25.rss",
        poll_interval=3600,
        source_prefix="rss:investing",
    ),
    RSSFeed(
        name="Google Tech News",
        url=(
            "https://news.google.com/rss/search?q=technology+stocks"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
        poll_interval=3600,
        source_prefix="rss:google",
    ),
    RSSFeed(
        name="Oil and Energy",
        url=(
            "https://news.google.com/rss/search?"
            "q=oil+prices+crude+oil+energy+stocks"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
        poll_interval=3600,
        source_prefix="rss:google",
    ),
    RSSFeed(
        name="Gold and Mining",
        url=(
            "https://news.google.com/rss/search?"
            "q=gold+prices+gold+mining+stocks"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
        poll_interval=3600,
        source_prefix="rss:google",
    ),
    RSSFeed(
        name="Mergers and Acquisitions",
        url=(
            "https://news.google.com/rss/search?"
            "q=mergers+acquisitions+takeovers+stocks"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
        poll_interval=3600,
        source_prefix="rss:google",
    ),
    RSSFeed(
        name="Federal Reserve Press Releases",
        url="https://www.federalreserve.gov/feeds/press_all.xml",
        poll_interval=3600,
        source_prefix="rss:federal-reserve",
    ),
    RSSFeed(
        name="SEC Press Releases",
        url="https://www.sec.gov/news/pressreleases.rss",
        poll_interval=3600,
        source_prefix="rss:sec",
    ),
    RSSFeed(
        name="SEC EDGAR 8-K Filings",
        url=(
            "https://www.sec.gov/cgi-bin/browse-edgar?"
            "action=getcurrent&type=8-K&owner=exclude"
            "&count=100&output=atom"
        ),
        poll_interval=3600,
        source_prefix="rss:sec-edgar",
    ),
    RSSFeed(
        name="ECB Communications",
        url="https://www.ecb.europa.eu/rss/press.html",
        poll_interval=3600,
        source_prefix="rss:ecb",
    ),
    RSSFeed(
        name="BLS Latest Releases",
        url="https://www.bls.gov/feed/bls_latest.rss",
        poll_interval=3600,
        source_prefix="rss:bls",
    ),
    RSSFeed(
        name="EIA Today in Energy",
        url="https://www.eia.gov/rss/todayinenergy.xml",
        poll_interval=3600,
        source_prefix="rss:eia",
    ),
    RSSFeed(
        name="Bloomberg Markets",
        url="https://feeds.bloomberg.com/markets/news.rss",
        poll_interval=3600,
        source_prefix="rss:bloomberg",
    ),
    RSSFeed(
        name="CNBC Top News",
        url="https://www.cnbc.com/id/100003114/device/rss/rss.html",
        poll_interval=3600,
        source_prefix="rss:cnbc",
    ),
    RSSFeed(
        name="BBC Business",
        url="https://feeds.bbci.co.uk/news/business/rss.xml",
        poll_interval=3600,
        source_prefix="rss:bbc",
    ),
    RSSFeed(
        name="TechCrunch",
        url="https://techcrunch.com/feed/",
        poll_interval=3600,
        source_prefix="rss:techcrunch",
    ),
    RSSFeed(
        name="CoinDesk",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        poll_interval=3600,
        source_prefix="rss:coindesk",
    ),
]
