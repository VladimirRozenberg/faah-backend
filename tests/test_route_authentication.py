"""Exercise bearer authentication and account isolation through the HTTP routes."""

import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import httpx
import jwt
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from admin.gestion import router as admin_router
from auth.authService import auth_service
from auth.login import router as auth_router
from db import Base, get_db
from models import Asset, Portfolio, PortfolioStrategist, Transaction, User
from routers import assets, data_sources, favorites, health, orchestrator, portfolios


class RouteAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key = 'test-signing-key-with-at-least-thirty-two-bytes'
        self.key_patch = patch('auth.authService.TOKEN_HEX_KEY', self.key)
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[User.__table__, Asset.__table__, Portfolio.__table__,
                           PortfolioStrategist.__table__, Transaction.__table__],
            ))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            users = [User(usr_username=name, usr_email=f'{name}@example.com',
                          usr_password_hash=auth_service._hash_password('password123'),
                          usr_role=role, usr_is_active=active, usr_balance=balance)
                     for name, role, active, balance in (
                         ('alice', 'employe', True, 100),
                         ('bob', 'employe', True, 900),
                         ('admin', 'admin', True, 0),
                         ('disabled', 'employe', False, 0),
                     )]
            db.add_all(users)
            await db.flush()
            self.user_ids = {user.usr_username: user.usr_id for user in users}
            other_portfolio = Portfolio(prt_usr_id=self.user_ids['bob'], prt_name='Bob portfolio')
            db.add(other_portfolio)
            await db.commit()
            self.other_portfolio_id = other_portfolio.prt_id
        self.app = FastAPI()
        for router in [auth_router, admin_router, health.router, portfolios.router,
                       assets.router, data_sources.router, favorites.router, orchestrator.router]:
            self.app.include_router(router)
        async def test_db():
            async with self.sessions() as db:
                yield db
        self.app.dependency_overrides[get_db] = test_db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url='http://test')

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()

    def headers(self, username='alice', **claims):
        payload = {'sub': str(self.user_ids[username]), 'exp': int(time.time()) + 7200}
        payload.update(claims)
        return {'Authorization': 'Bearer ' + jwt.encode(payload, self.key, algorithm='HS256')}

    def protected_requests(self):
        # Cover every listed route plus all adjacent personal portfolio routes.
        requests = []
        for route in self.app.routes:
            path = route.path
            protect = (path.startswith(('/api/users/me/', '/admin/', '/api/favorites'))
                       or path in {'/auth/me', '/auth/me/password', '/health', '/health/external',
                                   '/api/assets', '/api/niches', '/api/history-options',
                                   '/api/data-sources', '/api/data-sources/{source_id}',
                                   '/api/orchestrator/decisions'}
                       or path in {'/api/assets/{symbol}/market', '/api/assets/{symbol}/usd-quote',
                                   '/api/assets/{symbol}/candles', '/api/assets/{symbol}/news'})
            if protect:
                path = path.replace('{user_id}', '2').replace('{portfolio_id}', '1')
                path = path.replace('{asset_id}', '1').replace('{symbol}', 'AAPL').replace('{source_id}', '1')
                for method in route.methods:
                    requests.append((method, path))
        return requests

    async def test_all_protected_routes_reject_missing_invalid_and_expired_tokens(self):
        for headers, expected in [({}, 403), ({'Authorization': 'Bearer invalid'}, 401),
                                  (self.headers(exp=int(time.time()) - 1), 401)]:
            for method, path in self.protected_requests():
                with self.subTest(method=method, path=path, expected=expected):
                    response = await self.client.request(method, path, headers=headers, json={})
                    self.assertEqual(response.status_code, expected, response.text)

    async def test_login_is_public_and_issues_a_two_hour_token(self):
        now = int(time.time())
        response = await self.client.post('/auth/login', json={'username': 'alice', 'password': 'password123'})
        self.assertEqual(response.status_code, 200, response.text)
        payload = jwt.decode(response.json()['token'], self.key, algorithms=['HS256'])
        self.assertGreaterEqual(payload['exp'], now + 7200)
        self.assertLessEqual(payload['exp'], int(time.time()) + 7200)
        self.assertEqual(payload['sub'], str(self.user_ids['alice']))

    async def test_personal_routes_take_identity_from_token_and_old_paths_are_removed(self):
        headers = self.headers()
        response = await self.client.get('/auth/me', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user_id'], self.user_ids['alice'])
        # Supplied user IDs cannot select Bob's balance.
        response = await self.client.get('/api/users/me/available-cash?user_id=2&uid=2', headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['user_id'], self.user_ids['alice'])
        self.assertEqual(response.json()['available_cash'], 100)
        response = await self.client.get('/api/users/me/portfolios', headers=headers)
        self.assertEqual(response.json(), {'count': 0, 'items': []})
        response = await self.client.get('/api/users/2/portfolios', headers=headers)
        self.assertEqual(response.status_code, 404)
        for path, operations in self.app.openapi()['paths'].items():
            if path.startswith('/api/users/'):
                self.assertTrue(path.startswith('/api/users/me/'), path)
                for operation in operations.values():
                    self.assertFalse(any(p['name'] in {'uid', 'user_id'} for p in operation.get('parameters', [])))

    async def test_cannot_read_update_trade_or_review_another_users_portfolio(self):
        prefix = f'/api/users/me/portfolios/{self.other_portfolio_id}'
        requests = [('GET', '', None), ('PATCH', '', {'is_active': False}),
                    ('GET', '/transactions', None), ('GET', '/recommendations', None),
                    ('GET', '/strategist', None), ('GET', '/strategist/reviews', None),
                    ('POST', '/strategist/reviews', None),
                    ('POST', '/assets/buy', {'symbol': 'AAPL', 'quantity': 1, 'purchase_price': 100}),
                    ('POST', '/assets/sell', {'symbol': 'AAPL', 'quantity': 1, 'sale_price': 100})]
        for method, suffix, body in requests:
            with self.subTest(method=method, suffix=suffix):
                response = await self.client.request(method, prefix + suffix, json=body, headers=self.headers())
                self.assertEqual(response.status_code, 404, response.text)
        async with self.sessions() as db:
            portfolio = await db.get(Portfolio, self.other_portfolio_id)
            self.assertTrue(portfolio.prt_is_active)

    async def test_admin_routes_require_admin_and_keep_target_account_id(self):
        for method, path in self.protected_requests():
            if path.startswith('/admin/'):
                response = await self.client.request(method, path, json={}, headers=self.headers())
                self.assertEqual(response.status_code, 403, response.text)
        response = await self.client.post(f"/admin/utilisateurs/{self.user_ids['bob']}/deposit",
                                          json={'amount': 10}, headers=self.headers('admin'))
        self.assertEqual(response.status_code, 200, response.text)
        async with self.sessions() as db:
            self.assertEqual((await db.get(User, self.user_ids['bob'])).usr_balance, 910)
            self.assertEqual((await db.get(User, self.user_ids['admin'])).usr_balance, 0)

    async def test_valid_token_allows_shared_routes_and_disabled_account_is_rejected(self):
        response = await self.client.get('/api/history-options', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        response = await self.client.get('/auth/me', headers=self.headers('disabled'))
        self.assertEqual(response.status_code, 401)

    async def test_user_transactions_include_all_owned_portfolios_and_exclude_other_users(self):
        path = '/api/users/me/transactions'
        response = await self.client.get(path, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'count': 0, 'transactions': []})

        async with self.sessions() as db:
            asset = Asset(ast_symbol='AAPL', ast_name='Apple', ast_type='stock')
            active = Portfolio(prt_usr_id=self.user_ids['alice'], prt_name='Active')
            paused = Portfolio(prt_usr_id=self.user_ids['alice'], prt_name='Paused', prt_is_active=False)
            db.add_all([asset, active, paused])
            await db.flush()
            now = datetime.now(timezone.utc)
            transactions = []
            for portfolio_id, kind, quantity, created_at in [
                (active.prt_id, 'buy', 2, now - timedelta(days=1)),
                (paused.prt_id, 'sell', 1, now),
                (active.prt_id, 'buy', 3, now),
                (self.other_portfolio_id, 'buy', 99, now + timedelta(days=1)),
            ]:
                transactions.append(Transaction(
                    prt_id_trans=portfolio_id, ast_id_trans=asset.ast_id,
                    type_trans=kind, quantity_trans=Decimal(quantity),
                    price_trans=Decimal('100.25'), fees_trans=Decimal('0.50'),
                    currency_trans='USD', createdAt_trans=created_at,
                ))
            db.add_all(transactions)
            await db.commit()
            expected_ids = [transactions[i].id_trans for i in (2, 1, 0)]
            bob_id = transactions[3].id_trans
            active_id, paused_id = active.prt_id, paused.prt_id

        # Client-supplied account IDs must not override the authenticated identity.
        response = await self.client.get(path + '?uid=2&user_id=2', headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body['count'], 3)
        self.assertEqual([item['id'] for item in body['transactions']], expected_ids)
        self.assertEqual([item['portfolio_id'] for item in body['transactions']],
                         [active_id, paused_id, active_id])
        self.assertEqual([item['portfolio_name'] for item in body['transactions']],
                         ['Active', 'Paused', 'Active'])
        newest = body['transactions'][0]
        self.assertEqual(newest['symbol'], 'AAPL')
        self.assertEqual(newest['name'], 'Apple')
        self.assertEqual(newest['type'], 'buy')
        self.assertEqual(newest['quantity'], 3)
        self.assertEqual(newest['price'], 100.25)
        self.assertEqual(newest['amount'], 300.75)
        self.assertEqual(newest['fees'], 0.5)
        self.assertEqual(newest['currency'], 'USD')
        self.assertIn('created_at', newest)

        response = await self.client.get(path, headers=self.headers('bob'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(response.json()['transactions'][0]['id'], bob_id)

    async def test_user_transactions_require_a_valid_active_account_token(self):
        for headers, expected in [({}, 403), ({'Authorization': 'Bearer invalid'}, 401),
                                  (self.headers(exp=int(time.time()) - 1), 401),
                                  (self.headers('disabled'), 401)]:
            with self.subTest(expected=expected, headers=headers):
                response = await self.client.get('/api/users/me/transactions', headers=headers)
                self.assertEqual(response.status_code, expected, response.text)
