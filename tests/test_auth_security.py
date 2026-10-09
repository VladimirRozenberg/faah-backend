"""Authentication error handling and optional isolated Redis integration tests."""

import os
import time
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock, patch

import httpx
import jwt
from fastapi import FastAPI, HTTPException
from redis.asyncio import Redis
from redis.exceptions import ConnectionError

from auth.authService import InvalidCredentialsError, auth_service
from auth.login import router
from auth import rate_limit
from db import get_db
from schemas import TokenResponse


class AuthSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI()
        self.app.include_router(router)

        async def test_db():
            yield AsyncMock()

        self.app.dependency_overrides[get_db] = test_db
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url='http://test',
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_long_password_is_401_and_counts_as_failure(self):
        # Exercise the actual service password check with a mocked database result.
        user = type('User', (), {'usr_password_hash': auth_service._hash_password('password123')})()
        db = AsyncMock()
        db.execute.return_value.scalar_one_or_none = lambda: user

        async def test_db():
            yield db

        self.app.dependency_overrides[get_db] = test_db
        with patch('auth.login.check_login_rate_limit', new_callable=AsyncMock), \
             patch('auth.login.register_failed_login', new_callable=AsyncMock) as register:
            for password in ('a' * 73, 'é' * 37):
                response = await self.client.post('/auth/login', json={
                    'username': 'Alice', 'password': password,
                })
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()['detail'], 'Incorrect username or password.')
            self.assertEqual(register.await_count, 2)

    async def test_malformed_signed_subject_returns_401(self):
        key = 'test-signing-key-with-at-least-thirty-two-bytes'
        with patch('auth.authService.TOKEN_HEX_KEY', key):
            for subject in ('abc', '', '0', '-1', '2147483648', '9' * 100):
                token = jwt.encode({'sub': subject, 'exp': int(time.time()) + 60}, key, algorithm='HS256')
                response = await self.client.get('/auth/me', headers={'Authorization': 'Bearer ' + token})
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(response.json()['detail'], 'Malformed session token.')

    async def test_unavailable_redis_returns_503_before_checking_password(self):
        with patch.object(rate_limit.redis_client, 'eval', new=AsyncMock(side_effect=ConnectionError())), \
             patch.object(auth_service, 'login', new_callable=AsyncMock) as login:
            response = await self.client.post('/auth/login', json={'username': 'alice', 'password': 'password123'})
            self.assertEqual(response.status_code, 503)
            login.assert_not_awaited()


@unittest.skipUnless(os.getenv('TEST_AUTH_REDIS') == '1', 'Set TEST_AUTH_REDIS=1 for Redis integration')
class RedisLoginLimitTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)
        self.other_client = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)
        self.key = f'test-{uuid4().hex}:alice'
        self.keys = [self.key, self.key + ':other-ip', self.key + ':other-user']
        client_patch = patch.object(rate_limit, 'redis_client', self.client)
        client_patch.start()
        self.addCleanup(client_patch.stop)

    async def asyncTearDown(self):
        await self.client.delete(*(rate_limit.login_attempts_key(key) for key in self.keys))
        await self.client.aclose()
        await self.other_client.aclose()

    async def test_five_failures_block_other_client_and_success_resets(self):
        for _ in range(5):
            await rate_limit.check_login_rate_limit(self.key)
            await rate_limit.register_failed_login(self.key)
        with patch.object(rate_limit, 'redis_client', self.other_client):
            with self.assertRaises(HTTPException) as caught:
                await rate_limit.check_login_rate_limit(self.key)
            self.assertEqual(caught.exception.status_code, 429)
        for key in self.keys[1:]:
            await rate_limit.check_login_rate_limit(key)
        await rate_limit.clear_failed_logins(self.key)
        await rate_limit.check_login_rate_limit(self.key)
        self.assertFalse(await self.client.exists(rate_limit.login_attempts_key(self.key)))

    async def test_sliding_window_expires_individual_failures(self):
        seconds, micros = await self.client.time()
        now = seconds + micros / 1_000_000
        redis_key = rate_limit.login_attempts_key(self.key)
        await self.client.zadd(redis_key, {
            'old': now - 301, **{f'recent-{i}': now - 10 for i in range(4)},
        })
        await rate_limit.check_login_rate_limit(self.key)
        self.assertEqual(await self.client.zcard(redis_key), 4)
        await rate_limit.register_failed_login(self.key)
        self.assertTrue(0 < await self.client.ttl(redis_key) <= 300)
        with self.assertRaises(HTTPException):
            await rate_limit.check_login_rate_limit(self.key)

    async def test_route_blocks_sixth_attempt_and_normalizes_username(self):
        app = FastAPI()
        app.include_router(router)

        async def test_db():
            yield None

        app.dependency_overrides[get_db] = test_db
        # Scope every route operation to our disposable test key.
        original_key = rate_limit.login_attempts_key
        with patch.object(rate_limit, 'login_attempts_key', side_effect=lambda key: original_key(self.key)), \
             patch.object(auth_service, 'login', new=AsyncMock(side_effect=InvalidCredentialsError())) as login:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                for username in ('Alice', 'alice', ' ALICE ', 'alice', 'Alice'):
                    response = await client.post('/auth/login', json={'username': username, 'password': 'wrong'})
                    self.assertEqual(response.status_code, 401)
                login.return_value = TokenResponse(token='valid', message='welcome')
                login.side_effect = None
                response = await client.post('/auth/login', json={'username': 'alice', 'password': 'correct'})
                self.assertEqual(response.status_code, 429)
                self.assertEqual(login.await_count, 5)
                await rate_limit.clear_failed_logins(self.key)
                response = await client.post('/auth/login', json={'username': 'alice', 'password': 'correct'})
                self.assertEqual(response.status_code, 200)
                self.assertFalse(await self.client.exists(original_key(self.key)))
