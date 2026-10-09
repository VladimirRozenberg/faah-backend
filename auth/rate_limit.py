"""Compteur partagé des échecs de connexion dans une fenêtre glissante."""

import os
from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError

MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300

redis_client = Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)

# L'horloge Redis évite les écarts entre les horloges des processus backend.
# Chaque membre a son propre horodatage ; les contrôles ne prolongent pas le TTL.
LOGIN_ATTEMPTS_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local window = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if ARGV[2] == 'register' then
    redis.call('ZADD', KEYS[1], now, ARGV[3])
    redis.call('EXPIRE', KEYS[1], window)
end
return redis.call('ZCARD', KEYS[1])
"""


def login_attempts_key(key: str) -> str:
    return "auth:failed-logins:" + sha256(key.encode("utf-8")).hexdigest()


async def _count_attempts(key: str, action: str) -> int:
    try:
        return await redis_client.eval(
            LOGIN_ATTEMPTS_SCRIPT,
            1,
            login_attempts_key(key),
            LOGIN_WINDOW_SECONDS,
            action,
            uuid4().hex,
        )
    except RedisError as error:
        raise HTTPException(
            status_code=503,
            detail="Login temporarily unavailable. Please try again later.",
        ) from error


async def check_login_rate_limit(key: str) -> None:
    if await _count_attempts(key, "check") >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later.",
        )


async def register_failed_login(key: str) -> None:
    await _count_attempts(key, "register")


async def clear_failed_logins(key: str) -> None:
    try:
        await redis_client.delete(login_attempts_key(key))
    except RedisError as error:
        raise HTTPException(
            status_code=503,
            detail="Login temporarily unavailable. Please try again later.",
        ) from error
