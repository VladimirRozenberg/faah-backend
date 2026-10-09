"""Account identifiers preserve casing and match case-insensitively."""

import unittest
from unittest.mock import patch

import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from admin.adminService import admin_service
from auth.authService import InvalidCredentialsError, UsernameTakenError, auth_service
from models import User
from schemas import RegisterRequest


class IdentifierValidationTests(unittest.TestCase):
    def test_registration_validation_preserves_username_case(self):
        request = RegisterRequest(username=' MixedCase ', email='Mixed@Example.COM', password='password123')
        self.assertEqual(request.username, 'MixedCase')
        self.assertEqual(request.email, 'Mixed@example.com')


class AuthIdentifierTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key = 'test-signing-key-with-at-least-thirty-two-bytes'
        key_patch = patch('auth.authService.TOKEN_HEX_KEY', self.key)
        key_patch.start()
        self.addCleanup(key_patch.stop)
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def create_account(self, db, username, email, admin=False):
        if admin:
            return await admin_service.create_user(username, email, 'password123', 'employe', db)
        return await auth_service.register(username, email, 'password123', db)

    async def test_creation_preserves_casing_and_login_ignores_case(self):
        for admin in (False, True):
            with self.subTest(admin=admin):
                username = 'AdminCreated' if admin else 'MixedCase'
                email = username + '@Example.COM'
                async with self.sessions() as db:
                    created = await self.create_account(db, ' ' + username + ' ', ' ' + email + ' ', admin)
                    user = (await db.execute(select(User).where(User.usr_username == username))).scalar_one()
                    self.assertEqual(user.usr_username, username)
                    self.assertEqual(user.usr_email, email)
                    claims = jwt.decode(created.token, self.key, algorithms=['HS256'])
                    self.assertEqual(claims['username'], username)
                    for identifier in (username.lower(), username.upper(), email.lower(), email.upper()):
                        logged_in = await auth_service.login(' ' + identifier + ' ', 'password123', db)
                        claims = jwt.decode(logged_in.token, self.key, algorithms=['HS256'])
                        self.assertEqual(claims['sub'], str(user.usr_id))
                        self.assertEqual(claims['username'], username)
                    with self.assertRaises(InvalidCredentialsError):
                        await auth_service.login(username.upper(), 'wrong-password', db)

    async def test_creation_rejects_case_only_duplicates(self):
        async with self.sessions() as db:
            await self.create_account(db, 'MixedCase', 'Mixed@Example.COM')
            for admin in (False, True):
                for username, email in (('mixedcase', 'other@example.com'),
                                        ('OtherUser', 'MIXED@EXAMPLE.COM')):
                    with self.subTest(admin=admin, username=username, email=email):
                        with self.assertRaises(UsernameTakenError):
                            await self.create_account(db, username, email, admin)

    async def test_database_rejects_case_only_duplicates(self):
        async with self.sessions() as db:
            await self.create_account(db, 'MixedCase', 'Mixed@Example.COM')
            for username, email in (('MIXEDCASE', 'other@example.com'),
                                    ('OtherUser', 'mixed@example.com')):
                with self.subTest(username=username, email=email):
                    db.add(User(usr_username=username, usr_email=email, usr_password_hash='unused'))
                    with self.assertRaises(IntegrityError):
                        await db.flush()
                    await db.rollback()
