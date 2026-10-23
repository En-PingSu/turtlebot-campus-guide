"""Tests for the same-origin check used by the dashboard and the speech UI.

Run from the repo root:  python3 -m unittest discover -s tests
"""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPIES = [ROOT / "dashboard" / "local_origin.py", ROOT / "speech_web_ui" / "local_origin.py"]


def load(path):
    spec = importlib.util.spec_from_file_location(f"local_origin_{path.parent.name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalOriginTest(unittest.TestCase):
    def test_both_copies_are_identical(self):
        self.assertEqual(COPIES[0].read_text(), COPIES[1].read_text())

    def test_rules(self):
        allowed = load(COPIES[0]).request_allowed
        # The UI talking to its own server, locally or from another device on the LAN
        self.assertTrue(allowed("127.0.0.1:8080", "http://127.0.0.1:8080"))
        self.assertTrue(allowed("localhost:8080", "http://localhost:8080"))
        self.assertTrue(allowed("192.168.50.10:8888", "http://192.168.50.10:8888"))
        self.assertTrue(allowed("[::1]:8080", "http://[::1]:8080"))
        # Non-browser tools send no Origin
        self.assertTrue(allowed("127.0.0.1:8080", None))
        # Other websites
        self.assertFalse(allowed("127.0.0.1:8080", "https://evil.example"))
        self.assertFalse(allowed("127.0.0.1:8080", "null"))
        self.assertFalse(allowed("127.0.0.1:8080", "http://127.0.0.1:9999"))
        # DNS rebinding: a domain name in Host, even with a matching Origin
        self.assertFalse(allowed("evil.example:8080", "http://evil.example:8080"))
        self.assertFalse(allowed("evil.example:8080", None))
        # Missing or malformed Host
        self.assertFalse(allowed(None, None))
        self.assertFalse(allowed("", None))


if __name__ == "__main__":
    unittest.main()
