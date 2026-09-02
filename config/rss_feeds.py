from dataclasses import dataclass

@dataclass
class RSSFeed:
    name: str
    url: str
    poll_interval: int  # in seconds
    source_prefix: str = ""  # Optional prefix for source identification    

RSS_FEEDS = [
    RSSFeed(name="Investing.com", url="https://www.investing.com/rss/news_25.rss", poll_interval=300, source_prefix="rss:investing"),
    RSSFeed(name="Google Tech News", url="https://news.google.com/rss/search?q=technology+stocks&hl=en-US&gl=US&ceid=US:en", poll_interval=300, source_prefix="rss:google"),
    RSSFeed(name="Oil and Energy", url="https://news.google.com/rss/search?q=oil+prices+crude+oil+energy+stocks&hl=en-US&gl=US&ceid=US:en", poll_interval=300, source_prefix="rss:google"),
    RSSFeed(name="Gold and Mining", url="https://news.google.com/rss/search?q=gold+prices+gold+mining+stocks&hl=en-US&gl=US&ceid=US:en", poll_interval=300, source_prefix="rss:google"),
    RSSFeed(name="Mergers and Acquisitions", url="https://news.google.com/rss/search?q=mergers+acquisitions+takeovers+stocks&hl=en-US&gl=US&ceid=US:en", poll_interval=300, source_prefix="rss:google"),]
    # Add more feeds as needed