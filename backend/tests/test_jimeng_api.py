import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.services.jimeng_api import JimengClient


class JimengServiceHealthTests(unittest.IsolatedAsyncioTestCase):
    @patch("app.services.jimeng_api.httpx.AsyncClient.get", new_callable=AsyncMock)
    async def test_service_available_accepts_ping(self, get):
        get.return_value = httpx.Response(200, text="pong")
        self.assertTrue(await JimengClient.service_available())

    @patch("app.services.jimeng_api.httpx.AsyncClient.get", new_callable=AsyncMock)
    async def test_service_available_rejects_connection_error(self, get):
        get.side_effect = httpx.ConnectError("offline")
        self.assertFalse(await JimengClient.service_available())
