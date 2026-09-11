"""Adresse Redis et durée du cache."""

import os


# Docker fournit REDIS_URL avec l'adresse et le mot de passe de Redis.
# Sans cette variable, on essaie Redis sur la machine locale.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Redis attend une durée en secondes : 24 heures = 86 400 secondes.
CACHE_TTL_SECONDS = 24 * 60 * 60
