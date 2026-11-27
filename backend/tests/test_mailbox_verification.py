import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.services.mailbox_verification import (
    GenericApiVerificationStrategy,
    extract_verification_code,
    get_verification_strategy,
    parse_mailbox_import_line,
)


class MailboxImportTests(unittest.TestCase):
    def test_outlook_line(self):
        entry = parse_mailbox_import_line("User@Example.com", "outlook")
        self.assertEqual(entry.email, "User@Example.com")
        self.assertIsNone(entry.code_url)

    def test_generic_api_line(self):
        entry = parse_mailbox_import_line(
            "User@Example.com----https://mail.example.com/code?token=secret",
            "generic_api",
        )
        self.assertEqual(entry.email, "User@Example.com")
        self.assertEqual(entry.code_url, "https://mail.example.com/code?token=secret")

    def test_generic_api_rejects_invalid_lines(self):
        for line in [
            "user@example.com",
            "user@example.com----http://mail.example.com/code",
            "user@example.com----https://127.0.0.1/code",
            "user@example.com----https://user:pass@mail.example.com/code",
        ]:
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_mailbox_import_line(line, "generic_api")


class VerificationStrategyTests(unittest.IsolatedAsyncioTestCase):
    def test_extracts_nested_verification_code(self):
        payload = {
            "status": "success",
            "data": {
                "email": "user@example.com",
                "latest_message": {"verification_code": "29BF8T"},
            },
        }
        self.assertEqual(extract_verification_code(payload, "user@example.com"), "29BF8T")

    def test_rejects_payload_for_another_email(self):
        payload = {
            "data": {
                "email": "other@example.com",
                "latest_message": {"verification_code": "29BF8T"},
            }
        }
        self.assertIsNone(extract_verification_code(payload, "user@example.com"))


    async def test_generic_strategy_reads_api_payload(self):
        async def allow(_url):
            return None

        def handler(request):
            self.assertEqual(request.url.params["token"], "secret")
            return httpx.Response(
                200,
                json={
                    "data": {
                        "email": "user@example.com",
                        "latest_message": {"verification_code": "29BF8T"},
                    }
                },
            )

        strategy = GenericApiVerificationStrategy(
            transport=httpx.MockTransport(handler),
            destination_validator=allow,
        )
        code = await strategy.poll(
            "user@example.com",
            code_url="https://mail.example.com/code?token=secret",
            timeout=1,
        )
        self.assertEqual(code, "29BF8T")

    async def test_generic_strategy_waits_for_code_newer_than_baseline(self):
        async def allow(_url):
            return None

        codes = iter(["OLDCODE", "NEWCODE"])

        def handler(_request):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "email": "user@example.com",
                        "latest_message": {"verification_code": next(codes)},
                    }
                },
            )

        strategy = GenericApiVerificationStrategy(
            transport=httpx.MockTransport(handler),
            destination_validator=allow,
        )
        with patch(
            "app.services.mailbox_verification.asyncio.sleep",
            new=AsyncMock(),
        ):
            code = await strategy.poll(
                "user@example.com",
                code_url="https://mail.example.com/code?token=secret",
                timeout=10,
                exclude_code="OLDCODE",
            )
        self.assertEqual(code, "NEWCODE")

    def test_strategy_registry(self):
        self.assertIsInstance(get_verification_strategy("generic_api"), GenericApiVerificationStrategy)
        self.assertEqual(get_verification_strategy("outlook").source, "outlook")
        self.assertEqual(get_verification_strategy("cloudflare").source, "cloudflare")
        with self.assertRaises(ValueError):
            get_verification_strategy("unknown")
