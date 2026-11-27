import unittest

from app.services.browser_profile import normalize_registration_browser_profile


class BrowserProfileNormalizationTests(unittest.TestCase):
    def test_uses_explicit_profile_fields(self):
        profile, version = normalize_registration_browser_profile(
            {
                "profile_name": "Chrome-150-Windows",
                "chrome_version": "150.0.0.0",
                "user_agent": "Chrome/150.0.0.0",
            }
        )
        self.assertEqual(profile, "Chrome-150-Windows")
        self.assertEqual(version, "150.0.0.0")

    def test_derives_legacy_profile_from_user_agent(self):
        profile, version = normalize_registration_browser_profile(
            '{"impersonate":"chrome136","user_agent":"Mozilla/5.0 '
            '(Macintosh; Intel Mac OS X 10_15_7) Chrome/136.0.0.0 Safari/537.36"}'
        )
        self.assertEqual(profile, "Chrome-136-macOS")
        self.assertEqual(version, "136.0.0.0")

    def test_empty_fingerprint_remains_unrecorded(self):
        self.assertEqual(normalize_registration_browser_profile(""), (None, None))
