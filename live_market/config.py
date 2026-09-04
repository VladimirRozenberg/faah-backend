"""Configuration simple du marché en direct."""

import os


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
