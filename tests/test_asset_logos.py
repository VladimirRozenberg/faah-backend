"""Tests des logos sans appels réels à Twelve Data et sans base externe."""
import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from assets import logos
from db import get_db
from routers.assets import router

PNG = b'\x89PNG\r\n\x1a\nimage-test'


def asset(**kwargs):
    fields = dict(ast_symbol='AAPL', ast_type='stock', ast_logo=None,
                  ast_logo_mime_type=None, ast_logo_last_attempt_at=None)
    return SimpleNamespace(**(fields | kwargs))


def database(values=(True, 0, 0)):
    return SimpleNamespace(no_autoflush=nullcontext(), flush=AsyncMock(),
                           scalar=AsyncMock(side_effect=values))


class LogoTests(unittest.IsolatedAsyncioTestCase):
    def test_symbols(self):
        for symbol, kind, expected in [('AAPL', 'stock', 'AAPL'),
                ('BTC-USD', 'crypto', 'BTC/USD'), ('EURUSD=X', 'forex', 'EUR/USD'),
                ('GC=F', 'future', None)]:
            self.assertEqual(logos.get_logo_symbol(asset(ast_symbol=symbol, ast_type=kind)), expected)

    async def test_download_and_formats(self):
        real_client = httpx.AsyncClient
        for field in ['url', 'logo_base']:
            def handler(request):
                if request.url.path == '/logo':
                    self.assertNotIn('apikey', request.url.params)
                    self.assertEqual(request.headers['authorization'], 'apikey test-key')
                    return httpx.Response(200, json={field: 'https://logo.twelvedata.com/a.png'})
                self.assertNotIn('apikey', request.url.params)
                self.assertNotIn('authorization', request.headers)
                return httpx.Response(200, content=PNG, headers={'content-type':'image/png'})
            with patch.object(logos.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
                self.assertEqual(await logos.download_logo('AAPL', 'test-key'), (PNG, 'image/png'))

    async def test_invalid_downloads(self):
        real_client = httpx.AsyncClient
        for url, mime, content in [
            ('http://127.0.0.1/private', 'image/png', PNG),
            ('https://example.com/a.png', 'image/png', PNG),
            ('https://logo.twelvedata.com/a', 'text/html', b'html'),
            ('https://logo.twelvedata.com/a', 'image/png', b'x'*(logos.MAX_LOGO_BYTES+1)),
            ('https://logo.twelvedata.com/a', 'image/png', b''),
        ]:
            def handler(request):
                if request.url.path == '/logo': return httpx.Response(200, json={'url':url})
                return httpx.Response(200, content=content, headers={'content-type':mime})
            with patch.object(logos.httpx, 'AsyncClient', side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
                self.assertIsNone(await logos.download_logo('AAPL','key'))

    async def test_missing_key_does_not_mark_attempt(self):
        a=asset();db=database()
        with patch.dict('os.environ', {'TWELVE_DATA_API_KEY':''}):
            await logos.fill_missing_logo(db,a)
        self.assertIsNone(a.ast_logo_last_attempt_at)
        db.scalar.assert_not_called()

    async def test_skip_logo_recent_attempt_and_future(self):
        for a in [asset(ast_logo_mime_type='image/png'),
                  asset(ast_logo_last_attempt_at=datetime.now(timezone.utc)),
                  asset(ast_type='future')]:
            db=database()
            with patch.dict('os.environ', {'TWELVE_DATA_API_KEY':'test'}):
                await logos.fill_missing_logo(db,a)
            db.scalar.assert_not_called()

    async def test_success_and_old_attempt(self):
        for previous in [None, datetime.now(timezone.utc)-timedelta(days=2)]:
            a=asset(ast_logo_last_attempt_at=previous)
            with patch.dict('os.environ', {'TWELVE_DATA_API_KEY':'test'}), patch.object(logos,'download_logo',AsyncMock(return_value=(PNG,'image/png'))):
                await logos.fill_missing_logo(database(),a)
            self.assertEqual(a.ast_logo,PNG)
            self.assertEqual(a.ast_logo_mime_type,'image/png')
            self.assertGreater(a.ast_logo_last_attempt_at, datetime.now(timezone.utc)-timedelta(minutes=1))

    async def test_limits_and_other_worker_do_not_mark_attempt(self):
        for values in [(False,), (True,7), (True,0,750)]:
            a=asset()
            with patch.dict('os.environ', {'TWELVE_DATA_API_KEY':'test'}), patch.object(logos,'download_logo',AsyncMock()) as download:
                await logos.fill_missing_logo(database(values),a)
            download.assert_not_called()
            self.assertIsNone(a.ast_logo_last_attempt_at)

    async def test_provider_failure_keeps_asset_without_logo(self):
        for error in [httpx.ConnectError('offline'), ValueError('invalid JSON'), asyncio.TimeoutError()]:
            a=asset()
            with patch.dict('os.environ', {'TWELVE_DATA_API_KEY':'test'}), patch.object(logos,'download_logo',AsyncMock(side_effect=error)):
                await logos.fill_missing_logo(database(),a)
            self.assertIsNone(a.ast_logo)
            self.assertIsNotNone(a.ast_logo_last_attempt_at)

    async def test_missing_logo(self):
        a=asset()
        with patch.dict('os.environ', {'TWELVE_DATA_API_KEY':'test'}), patch.object(logos,'download_logo',AsyncMock(return_value=None)):
            await logos.fill_missing_logo(database(),a)
        self.assertIsNone(a.ast_logo)
        self.assertIsNotNone(a.ast_logo_last_attempt_at)

    async def test_http_logo_and_404(self):
        app=FastAPI();app.include_router(router)
        for row, status in [((PNG,'image/png'),200),((None,None),404),(None,404)]:
            db=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(first=lambda:row)))
            async def dependency(): yield db
            app.dependency_overrides[get_db]=dependency
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                response=await client.get('/api/assets/AAPL/logo')
            self.assertEqual(response.status_code,status)
            if status==200:
                self.assertEqual(response.content,PNG)
                self.assertEqual(response.headers['content-type'],'image/png')


    async def test_detection_saves_new_and_existing_assets(self):
        from sqlalchemy import select, func
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from db import Base
        from models import Asset, Stock, Crypto, Forex, Future, Prompt, DataSource, SourceClassification, ClassificationAsset
        from assets.repository import save_detected_assets
        from assets.schemas import DetectedAsset
        engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        tables=[m.__table__ for m in [Asset,Stock,Crypto,Forex,Future,Prompt,DataSource,SourceClassification,ClassificationAsset]]
        try:
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync: Base.metadata.create_all(sync,tables=tables))
            async with async_sessionmaker(engine,expire_on_commit=False)() as db:
                source=DataSource(src_type='test'); prompt=Prompt(prm_name='test',prm_type='test',prm_prompt_text='test')
                db.add_all([source,prompt]);await db.flush()
                classification=SourceClassification(cls_src_id=source.src_id,cls_prm_id=prompt.prm_id,cls_should_trigger=True)
                db.add(classification);await db.flush()
                candidate=DetectedAsset(symbol='AAPL',confidence=90,reason='test')
                information=dict(symbol='AAPL',name='Apple',type='stock',yahoo_type='EQUITY',exchange='NASDAQ',currency='USD',country='US',sector='Technology',industry='Devices')
                async def fill(session, item):
                    item.ast_logo=PNG;item.ast_logo_mime_type='image/png'
                with patch('assets.repository.get_yahoo_information',return_value=information), patch('assets.repository.fill_missing_logo',AsyncMock(side_effect=fill)) as complete:
                    first=await save_detected_assets(db,classification.cls_id,[candidate])
                    first_id=first[0].ast_id
                    second=await save_detected_assets(db,classification.cls_id,[candidate])
                self.assertEqual(complete.await_count,2)
                self.assertEqual(second[0].ast_id,first_id)
                self.assertEqual(second[0].ast_logo,PNG)
                self.assertEqual(await db.scalar(select(func.count()).select_from(Asset)),1)
                self.assertEqual(await db.scalar(select(func.count()).select_from(ClassificationAsset)),1)
        finally:
            await engine.dispose()
