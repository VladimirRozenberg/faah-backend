"""Exercise bearer authentication and account isolation through the HTTP routes."""

import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import jwt
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from admin.gestion import router as admin_router
from auth.authService import auth_service
from auth.login import router as auth_router
from db import Base, get_db
from models import Asset, Deposit, Portfolio, PortfolioStrategist, Transaction, User
from portfolio.repository import deposit_cash
from routers import assets, data_sources, favorites, health, orchestrator, portfolios


class RouteAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # These route tests isolate authentication from the external Redis service.
        for name in ('check_login_rate_limit', 'register_failed_login', 'clear_failed_logins'):
            limiter_patch = patch(f'auth.login.{name}', new_callable=AsyncMock)
            limiter_patch.start()
            self.addCleanup(limiter_patch.stop)
        self.key = 'test-signing-key-with-at-least-thirty-two-bytes'
        self.key_patch = patch('auth.authService.TOKEN_HEX_KEY', self.key)
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[User.__table__, Asset.__table__, Portfolio.__table__,
                           PortfolioStrategist.__table__, Transaction.__table__, Deposit.__table__],
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

    async def test_login_is_public_and_issues_a_four_hour_token(self):
        now = int(time.time())
        response = await self.client.post('/auth/login', json={'username': 'alice', 'password': 'password123'})
        self.assertEqual(response.status_code, 200, response.text)
        payload = jwt.decode(response.json()['token'], self.key, algorithms=['HS256'])
        self.assertGreaterEqual(payload['exp'], now + 14400)
        self.assertLessEqual(payload['exp'], int(time.time()) + 14400)
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
            deposit = await db.scalar(select(Deposit))
            self.assertEqual(deposit.dep_usr_id, self.user_ids['bob'])
            self.assertEqual(deposit.dep_admin_usr_id, self.user_ids['admin'])
            self.assertEqual(deposit.dep_amount, 10)
        response = await self.client.get('/api/users/me/deposits', headers=self.headers('bob'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['count'], 1)
        item = response.json()['deposits'][0]
        self.assertEqual(item['amount'], 10)
        self.assertEqual(item['currency'], 'USD')
        self.assertEqual(item['added_by'], 'admin')
        self.assertEqual(set(item), {'id', 'amount', 'currency', 'created_at', 'added_by'})
        response = await self.client.get('/api/users/me/deposits', headers=self.headers('admin'))
        self.assertEqual(response.json()['count'], 0)

    async def test_valid_token_allows_shared_routes_and_disabled_account_is_rejected(self):
        response = await self.client.get('/api/history-options', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        response = await self.client.get('/auth/me', headers=self.headers('disabled'))
        self.assertEqual(response.status_code, 401)

    async def test_user_transactions_include_all_owned_portfolios_and_exclude_other_users(self):
        path = '/api/users/me/transactions'
        response = await self.client.get(path, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'count': 0, 'page': 1, 'page_size': 10,
                                           'total_pages': 0, 'transactions': []})

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

    async def test_user_transactions_paginate_ten_items_with_total_count_and_stable_order(self):
        async with self.sessions() as db:
            asset = Asset(ast_symbol='MSFT', ast_name='Microsoft', ast_type='stock')
            portfolios = [Portfolio(prt_usr_id=self.user_ids['alice'], prt_name=name)
                          for name in ('First', 'Second')]
            db.add_all([asset, *portfolios])
            await db.flush()
            now = datetime.now(timezone.utc)
            transactions = [Transaction(
                prt_id_trans=portfolios[index % 2].prt_id, ast_id_trans=asset.ast_id,
                type_trans='buy', quantity_trans=Decimal('1'), price_trans=Decimal('10'),
                createdAt_trans=now,
            ) for index in range(23)]
            db.add_all(transactions)
            db.add(Transaction(
                prt_id_trans=self.other_portfolio_id, ast_id_trans=asset.ast_id,
                type_trans='buy', quantity_trans=Decimal('1'), price_trans=Decimal('10'),
                createdAt_trans=now + timedelta(days=1),
            ))
            await db.commit()
            expected_ids = sorted((item.id_trans for item in transactions), reverse=True)

        path = '/api/users/me/transactions'
        actual_ids = []
        for page, expected_length in [(1, 10), (2, 10), (3, 3), (4, 0)]:
            query = '' if page == 1 else f'?page={page}'
            response = await self.client.get(path + query, headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body['count'], 23)
            self.assertEqual(body['page'], page)
            self.assertEqual(body['page_size'], 10)
            self.assertEqual(body['total_pages'], 3)
            self.assertEqual(len(body['transactions']), expected_length)
            actual_ids.extend(item['id'] for item in body['transactions'])
        self.assertEqual(actual_ids, expected_ids)

        for page in ('0', '-1', 'abc'):
            response = await self.client.get(path + f'?page={page}', headers=self.headers())
            self.assertEqual(response.status_code, 422, response.text)

    async def test_portfolio_transactions_default_to_twenty_and_paginate_owned_history(self):
        async with self.sessions() as db:
            asset = Asset(ast_symbol='PAGE', ast_name='Pagination asset', ast_type='stock')
            portfolio = Portfolio(prt_usr_id=self.user_ids['alice'], prt_name='History')
            db.add_all([asset, portfolio])
            await db.flush()
            now = datetime.now(timezone.utc)
            transactions = [Transaction(
                prt_id_trans=portfolio.prt_id, ast_id_trans=asset.ast_id,
                type_trans='buy', quantity_trans=Decimal('1'), price_trans=Decimal('10'),
                createdAt_trans=now,
            ) for _ in range(25)]
            db.add_all(transactions)
            db.add(Transaction(prt_id_trans=self.other_portfolio_id, ast_id_trans=asset.ast_id,
                               type_trans='sell', quantity_trans=Decimal('1'),
                               price_trans=Decimal('10'), createdAt_trans=now + timedelta(days=1)))
            await db.commit()
            expected_ids = sorted((item.id_trans for item in transactions), reverse=True)
            portfolio_id = portfolio.prt_id
        path = f'/api/users/me/portfolios/{portfolio_id}/transactions'
        actual_ids = []
        for query, page, length in [('', 1, 20), ('?page=2', 2, 5), ('?page=3', 3, 0)]:
            response = await self.client.get(path + query, headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body['count'], 25)
            self.assertEqual(body['page'], page)
            self.assertEqual(body['page_size'], 20)
            self.assertEqual(body['total_pages'], 2)
            self.assertEqual(len(body['transactions']), length)
            self.assertEqual(body['by_asset'][0]['transaction_count'], 25)
            actual_ids.extend(item['id'] for item in body['transactions'])
        self.assertEqual(actual_ids, expected_ids)
        response = await self.client.get(path + '?page_size=10', headers=self.headers())
        self.assertEqual(len(response.json()['transactions']), 10)
        for query in ('page=0', 'page_size=0', 'page_size=101'):
            response = await self.client.get(path + '?' + query, headers=self.headers())
            self.assertEqual(response.status_code, 422)
        response = await self.client.get(path, headers=self.headers('bob'))
        self.assertEqual(response.status_code, 404)

    async def test_password_update_requires_eight_characters_and_at_most_72_bytes(self):
        path = '/auth/me/password'
        for password in ('abcdefg', '1234567', 'a' * 73, 'é' * 36 + '1'):
            response = await self.client.put(path, headers=self.headers(), json={'new_password': password})
            self.assertEqual(response.status_code, 422, response.text)
        async with self.sessions() as db:
            user = await db.get(User, self.user_ids['alice'])
            self.assertTrue(auth_service._verify_password('password123', user.usr_password_hash))
        for password in ('abcdefgh', 'a' * 72, 'é' * 36):
            response = await self.client.put(path, headers=self.headers(), json={'new_password': password})
            self.assertEqual(response.status_code, 204, response.text)
            response = await self.client.post('/auth/login', json={'username': 'alice', 'password': password})
            self.assertEqual(response.status_code, 200, response.text)
        response = await self.client.post('/auth/login', json={'username': 'alice', 'password': 'password123'})
        self.assertEqual(response.status_code, 401, response.text)

    async def test_user_deposits_paginate_and_only_show_the_authenticated_account(self):
        path = '/api/users/me/deposits'
        response = await self.client.get(path, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'count': 0, 'page': 1, 'page_size': 10,
                                           'total_pages': 0, 'deposits': []})
        async with self.sessions() as db:
            now = datetime.now(timezone.utc)
            deposits = [Deposit(
                dep_usr_id=self.user_ids['alice'], dep_admin_usr_id=self.user_ids['admin'],
                dep_amount=Decimal(index + 1), dep_created_at=now,
            ) for index in range(23)]
            db.add_all(deposits)
            db.add(Deposit(
                dep_usr_id=self.user_ids['bob'], dep_admin_usr_id=self.user_ids['admin'],
                dep_amount=Decimal('900'), dep_created_at=now + timedelta(days=1),
            ))
            await db.commit()
            expected_ids = sorted((item.dep_id for item in deposits), reverse=True)
        actual_ids = []
        for page, expected_length in [(1, 10), (2, 10), (3, 3), (4, 0)]:
            response = await self.client.get(path + f'?page={page}&uid=2&user_id=2',
                                             headers=self.headers())
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body['count'], 23)
            self.assertEqual(body['page'], page)
            self.assertEqual(body['page_size'], 10)
            self.assertEqual(body['total_pages'], 3)
            self.assertEqual(len(body['deposits']), expected_length)
            self.assertTrue(all(item['added_by'] == 'admin' for item in body['deposits']))
            actual_ids.extend(item['id'] for item in body['deposits'])
        self.assertEqual(actual_ids, expected_ids)
        response = await self.client.get(path, headers=self.headers('bob'))
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(response.json()['deposits'][0]['amount'], 900)
        for page in ('0', '-1', 'abc'):
            response = await self.client.get(path + f'?page={page}', headers=self.headers())
            self.assertEqual(response.status_code, 422, response.text)

    async def test_user_deposits_require_a_valid_active_account_token(self):
        for headers, expected in [({}, 403), ({'Authorization': 'Bearer invalid'}, 401),
                                  (self.headers(exp=int(time.time()) - 1), 401),
                                  (self.headers('disabled'), 401)]:
            response = await self.client.get('/api/users/me/deposits', headers=headers)
            self.assertEqual(response.status_code, expected, response.text)

    async def test_failed_deposit_record_rolls_back_the_balance_change(self):
        # The HTTP schema rejects negative amounts; exercise the DB constraint too.
        async with self.sessions() as db:
            with self.assertRaises(IntegrityError):
                await deposit_cash(db, self.user_ids['alice'], Decimal('-10'),
                                   admin_user_id=self.user_ids['admin'])
            await db.rollback()
            account = await db.get(User, self.user_ids['alice'])
            self.assertEqual(account.usr_balance, 100)
            self.assertEqual(await db.scalar(select(func.count(Deposit.dep_id))), 0)

    async def test_user_transactions_require_a_valid_active_account_token(self):
        for headers, expected in [({}, 403), ({'Authorization': 'Bearer invalid'}, 401),
                                  (self.headers(exp=int(time.time()) - 1), 401),
                                  (self.headers('disabled'), 401)]:
            with self.subTest(expected=expected, headers=headers):
                response = await self.client.get('/api/users/me/transactions', headers=headers)
                self.assertEqual(response.status_code, expected, response.text)
