import unittest

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routers.outlook_mailboxes import router
from app.core.database import get_db
from app.models.outlook_mailbox import OutlookMailbox


class MailboxApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(OutlookMailbox.__table__.create)
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def db():
            async with sessions() as session:
                yield session

        app = FastAPI()
        app.include_router(router, prefix="/mailboxes")
        app.dependency_overrides[get_db] = db
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.engine.dispose()

    async def test_imports_both_provider_types_without_exposing_code_url(self):
        outlook = await self.client.post(
            "/mailboxes/batch",
            json={"emails": ["a@example.test"], "provider_type": "outlook"},
        )
        self.assertEqual(outlook.status_code, 200)

        generic = await self.client.post(
            "/mailboxes/batch",
            json={
                "emails": [
                    "b@example.test----https://mail.example.test/code?token=SECRET"
                ],
                "provider_type": "generic_api",
            },
        )
        self.assertEqual(generic.status_code, 200)
        listed = await self.client.get("/mailboxes")
        self.assertNotIn("SECRET", listed.text)
        by_email = {row["email"]: row for row in listed.json()["items"]}
        self.assertEqual(by_email["a@example.test"]["provider_type"], "outlook")
        self.assertEqual(by_email["b@example.test"]["provider_type"], "generic_api")
        self.assertTrue(by_email["b@example.test"]["has_code_url"])
