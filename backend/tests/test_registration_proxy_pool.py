import unittest

from app.services.proxy_pool import ProxyConfig, ProxyPoolManager
from app.services.proxy_pool_import import parse_proxy_line


class ProxyImportTests(unittest.TestCase):
    def test_four_supported_formats(self):
        cases = [
            ("proxy.test:8080", ("http", "proxy.test", 8080, None, None)),
            ("proxy.test:8080:user:pass", ("http", "proxy.test", 8080, "user", "pass")),
            ("socks5://proxy.test:1080", ("socks5", "proxy.test", 1080, None, None)),
            ("http://u%40x:p%3Ass@proxy.test:8080", ("http", "proxy.test", 8080, "u@x", "p:ss")),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                proxy = parse_proxy_line(raw)
                self.assertEqual((proxy.protocol, proxy.host, proxy.port, proxy.username, proxy.password), expected)


class CountryPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_selects_only_requested_country(self):
        manager = ProxyPoolManager()
        manager.proxies = [
            ProxyConfig("sg.test", 80, region_tag="SG", name="sg"),
            ProxyConfig("jp.test", 80, region_tag="JP", name="jp"),
        ]
        selected = await manager.acquire_proxy(strategy="least_used", region="jp")
        self.assertEqual(selected.name, "jp")

    async def test_empty_or_unmatched_pool_has_no_clash_fallback(self):
        manager = ProxyPoolManager()
        self.assertIsNone(await manager.acquire_proxy(region="US"))
        manager.proxies = [ProxyConfig("sg.test", 80, region_tag="SG")]
        self.assertIsNone(await manager.acquire_proxy(region="US"))
