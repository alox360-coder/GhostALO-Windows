import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ghostalo import checks  # noqa: E402
from ghostalo.i18n import set_italian  # noqa: E402


class ChecksTest(unittest.TestCase):
    def setUp(self):
        set_italian(True)

    def test_hotfix_days(self):
        self.assertEqual(checks.parse_hotfix_days("2026-10-01", datetime.date(2026, 10, 31)), 30)
        self.assertIsNone(checks.parse_hotfix_days("boh"))
        self.assertIsNone(checks.parse_hotfix_days(""))

    def test_classify_command(self):
        self.assertEqual(checks.classify_command(r"C:\Program Files\App\app.exe"), "info")
        self.assertEqual(checks.classify_command(r"C:\Users\x\AppData\Local\Temp\a.exe"), "warn")
        self.assertEqual(checks.classify_command(r"C:\Users\x\Downloads\setup.exe"), "warn")
        self.assertEqual(checks.classify_command("powershell.exe -enc AAAA"), "warn")
        self.assertEqual(checks.classify_command(None), "info")

    def test_classify_program(self):
        self.assertEqual(checks.classify_program("AnyDesk"), "info")
        self.assertEqual(checks.classify_program("Spyrix Free Keylogger"), "warn")
        self.assertIsNone(checks.classify_program("Notepad++"))

    def test_manifest(self):
        broad = '{"name":"Ext","permissions":["storage"],"host_permissions":["<all_urls>"]}'
        self.assertEqual(checks.parse_manifest(broad), ("Ext", True))
        narrow = '{"name":"E2","permissions":["storage"]}'
        self.assertEqual(checks.parse_manifest(narrow), ("E2", False))
        cs = '{"name":"E3","content_scripts":[{"matches":["*://*/*"]}]}'
        self.assertEqual(checks.parse_manifest(cs), ("E3", True))
        self.assertIsNone(checks.parse_manifest("non json"))

    def test_resolve_name(self):
        import json, tempfile
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "_locales", "en"))
        with open(os.path.join(d, "_locales", "en", "messages.json"), "w", encoding="utf-8") as f:
            json.dump({"appName": {"message": "Mia Estensione"}}, f)
        self.assertEqual(checks.resolve_name("__MSG_appName__", d, "en"), "Mia Estensione")
        self.assertEqual(checks.resolve_name("__MSG_appname__", d), "Mia Estensione")
        self.assertIsNone(checks.resolve_name("__MSG_manca__", d, "en"))
        self.assertEqual(checks.resolve_name("Normale", d), "Normale")

    def test_hosts(self):
        text = "# commento\n127.0.0.1 localhost\n::1 localhost\n\n0.0.0.0 ads.example.com # blocco\n"
        self.assertEqual(checks.parse_hosts(text), ["0.0.0.0 ads.example.com"])

    def test_unavailable_is_never_ok(self):
        # Fuori da Windows nessun controllo può risultare 'ok' per errore.
        if os.name == "nt":
            self.skipTest("solo fuori da Windows")
        res = checks.run_security()
        self.assertTrue(all(c.status != "ok" for c in res if c.title not in ("Account amministratore",)))


if __name__ == "__main__":
    unittest.main()
