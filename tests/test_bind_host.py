import unittest

from socket_util import normalize_bind_host


class TestNormalizeBindHost(unittest.TestCase):
    def test_specific_ip_falls_back_to_wildcard_for_dynamic_networks(self):
        self.assertEqual(normalize_bind_host("192.168.31.15"), "0.0.0.0")

    def test_loopback_ip_is_preserved(self):
        self.assertEqual(normalize_bind_host("127.0.0.1"), "127.0.0.1")

    def test_wildcard_ip_is_preserved(self):
        self.assertEqual(normalize_bind_host("0.0.0.0"), "0.0.0.0")


if __name__ == "__main__":
    unittest.main()
