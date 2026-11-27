import unittest
import random
from datetime import date

from app.services.protocol_register import (
    BrowserProfileRotator,
    DreaminaProtocolFlow,
    ProtocolRegistrationError,
    ProtocolResponse,
    xor5_hex,
)
from app.services.random_generator import RandomGenerator


class FakeTransport:
    def __init__(self, *, registered: bool = False):
        self.registered = registered
        self.calls = []

    async def post_form(self, base_url, path, form, *, extra_query=None):
        self.calls.append(("form", base_url, path, form, extra_query))
        payloads = {
            "/passport/web/region/": {
                "data": {
                    "country_code": "jp",
                    "domain": "https://login-row.www.capcut.com",
                },
                "message": "success",
            },
            "/passport/web/user/check_email_registered": {
                "data": {"is_registered": int(self.registered), "need_verify_email": 0},
                "message": "success",
            },
            "/passport/web/email/send_code/": {
                "data": {"email_ticket": "SEND_TICKET"},
                "message": "success",
            },
            "/passport/web/email/register/code_verify/": {
                "data": {"email_ticket": "VERIFIED_TICKET"},
                "message": "success",
            },
            "/passport/web/email/register_verify_login/": {
                "data": {"new_user": 1, "store_country": "jp", "user_id_str": "123"},
                "message": "success",
            },
        }
        data = payloads[path]
        return ProtocolResponse(200, base_url + path, data)

    async def post_json(self, url, payload, *, extra_headers=None):
        self.calls.append(("json", url, payload))
        return ProtocolResponse(
            200,
            url,
            {"ret": "0", "errmsg": "success", "data": {"passed": True}},
        )

    async def cookies(self):
        return []


class ProtocolRegistrationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_har_sequence_and_ticket_transition(self):
        transport = FakeTransport()
        steps = []

        async def code_provider():
            return "29BF8T"

        async def report(step):
            steps.append(step)

        async def check():
            return None

        result = await DreaminaProtocolFlow(
            transport,
            code_provider=code_provider,
            step_reporter=report,
            interruption_check=check,
        ).run(
            email="user@example.com",
            password="Strong8!Pass",
            birthday=date(2000, 5, 4),
            requested_region="JP",
        )

        form_calls = [call for call in transport.calls if call[0] == "form"]
        self.assertEqual(
            [call[2] for call in form_calls],
            [
                "/passport/web/region/",
                "/passport/web/user/check_email_registered",
                "/passport/web/email/send_code/",
                "/passport/web/email/register/code_verify/",
                "/passport/web/email/register_verify_login/",
            ],
        )
        self.assertEqual(form_calls[3][2][-1], "/")
        self.assertEqual(form_calls[4][3]["email_ticket"], "VERIFIED_TICKET")
        self.assertEqual(form_calls[4][3]["force_user_region"], "JP")
        self.assertEqual(form_calls[4][3]["birthday"], "2000-05-04")
        self.assertEqual(form_calls[4][3]["code"], xor5_hex("29BF8T"))
        self.assertEqual(result["region"], "jp")
        self.assertEqual(steps[-1], "protocol_register")

    async def test_registered_email_stops_before_send_code(self):
        transport = FakeTransport(registered=True)

        async def noop(*args):
            return None

        with self.assertRaisesRegex(ProtocolRegistrationError, "邮箱已注册"):
            await DreaminaProtocolFlow(
                transport,
                code_provider=noop,
                step_reporter=noop,
                interruption_check=noop,
            ).run(
                email="used@example.com",
                password="Strong8!Pass",
                birthday=date(2000, 5, 4),
                requested_region="JP",
            )
        self.assertEqual(len([c for c in transport.calls if c[0] == "form"]), 2)


class ProtocolEncodingTests(unittest.TestCase):
    def test_browser_profiles_use_randomized_round_robin(self):
        profiles = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        rotator = BrowserProfileRotator(profiles, rng=random.Random(7))

        first_cycle = [rotator.next()["name"] for _ in profiles]
        second_cycle = [rotator.next()["name"] for _ in profiles]

        self.assertEqual(set(first_cycle), {"A", "B", "C"})
        self.assertEqual(set(second_cycle), {"A", "B", "C"})
        self.assertNotEqual(first_cycle[-1], second_cycle[0])

    def test_xor5_matches_har_value(self):
        self.assertEqual(
            xor5_hex("0.toffees-ocean@icloud.com"),
            "352b716a6363606076286a6660646b456c66696a70612b666a68",
        )

    def test_generated_birth_date_is_already_over_18(self):
        today = date.today()
        for _ in range(100):
            birthday = RandomGenerator.generate_birth_date(min_age=19, max_age=45)
            age = today.year - birthday.year - (
                (today.month, today.day) < (birthday.month, birthday.day)
            )
            self.assertGreaterEqual(age, 19)
