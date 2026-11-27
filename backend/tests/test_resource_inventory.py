import unittest
from app.services.resource_inventory import parse_proxy, parse_mailbox, plan_import


class InventoryTests(unittest.TestCase):
    def test_four_formats(self):
        for raw, expected in [
            ("192.0.2.1:80", ("http", "192.0.2.1", 80, None)),
            ("192.0.2.1:80:alice:secret", ("http", "192.0.2.1", 80, "alice")),
            ("socks5://[2001:db8::1]:1080", ("socks5", "2001:db8::1", 1080, None)),
            ("https://a%40b:p%3Ass@Example.test:443", ("https", "example.test", 443, "a@b")),
        ]:
            with self.subTest(raw=raw):
                result = parse_proxy(raw)
                self.assertEqual((result.protocol, result.host, result.port, result.username), expected)
                self.assertNotIn("secret", repr(result))

    def test_invalid_and_redacted(self):
        for raw in ["ftp://host:21", "host:0", "host:65536", "host:01000/x",
                    "http://alice:private@host:80/a", "http://u:p%ZZ@host:80",
                    "http://[::1]bad:80", "http://host:80?", "http://host:80#", "http://a:b@@host:80", "http://a:%FF@host:80"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError) as err:
                parse_proxy(raw)
            self.assertNotIn("private", str(err.exception))

    def test_mailbox_syntax(self):
        self.assertEqual(parse_mailbox("Alice+dev@Example.test"), "Alice+dev@Example.test")
        for raw in ["alice", "alice@example", "a..z@example.test", "alice@-test.example", "u:p@host.test"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_mailbox(raw)

    def test_import_counts_and_line_numbers(self):
        planned, report = plan_import(
            ["", "a@example.test", "A@EXAMPLE.TEST", "bad", "b@example.test"],
            parse_mailbox, str.casefold, {"b@example.test"},
        )
        self.assertEqual(planned, ["a@example.test"])
        self.assertEqual(report["duplicates"], 2)
        self.assertEqual(report["errors"][0]["line"], 4)
