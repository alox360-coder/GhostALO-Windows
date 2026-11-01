import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ghostalo import cleaner, winutil  # noqa: E402
from ghostalo.winutil import pj  # noqa: E402
from ghostalo.i18n import set_italian  # noqa: E402

DAY = 86400


def touch(path, size=100, age_days=0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    t = time.time() - age_days * DAY
    os.utime(path, (t, t))


class CleanerTest(unittest.TestCase):
    def setUp(self):
        set_italian(True)
        self.d = tempfile.mkdtemp()
        self.env = {
            "TEMP": os.path.join(self.d, "Local", "Temp"),
            "LOCALAPPDATA": os.path.join(self.d, "Local"),
            "APPDATA": os.path.join(self.d, "Roaming"),
            "USERPROFILE": os.path.join(self.d, "User"),
        }
        self.trash = os.path.join(self.d, "fake_recycle")
        os.makedirs(self.trash)
        self._orig = winutil.recycle

        def fake_recycle(p):
            shutil.move(p, os.path.join(self.trash, os.path.basename(p)))
            return True

        winutil.recycle = fake_recycle

    def tearDown(self):
        winutil.recycle = self._orig
        shutil.rmtree(self.d, ignore_errors=True)

    def populate(self):
        e = self.env
        touch(os.path.join(e["TEMP"], "old.tmp"), 500, 3)
        touch(os.path.join(e["TEMP"], "new.tmp"), 500, 0)
        touch(os.path.join(e["LOCALAPPDATA"], "CrashDumps", "a.dmp"), 300, 1)
        touch(pj(e["LOCALAPPDATA"], r"Google\Chrome\User Data\Default\Cache\f_1"), 200)
        touch(pj(e["LOCALAPPDATA"], r"Google\Chrome\User Data\Default\Network\Cookies"), 50)
        touch(pj(e["LOCALAPPDATA"], r"Google\Chrome\User Data\Default\Network\Other"), 50)
        touch(os.path.join(e["USERPROFILE"], "Downloads", "setup.exe"), 1000, 100)
        touch(os.path.join(e["USERPROFILE"], "Downloads", "recent.exe"), 1000, 5)
        touch(os.path.join(e["USERPROFILE"], "Downloads", "notes.txt"), 1000, 200)

    def test_scan_finds_only_expected(self):
        self.populate()
        cats = {c.key: c for c in cleaner.scan(cleaner.build_categories(self.env))}
        self.assertEqual([i.size for i in cats["temp"].items], [500])
        self.assertEqual(cats["dumps"].count, 1)
        self.assertEqual(cats["browser"].count, 1)
        self.assertEqual(cats["cookies"].count, 1)
        self.assertEqual(cats["installers"].count, 1)
        self.assertTrue(cats["installers"].items[0].path.endswith("setup.exe"))
        self.assertEqual(cats["installers"].mode, "recycle")

    def test_delete_and_recycle(self):
        self.populate()
        cats = [c for c in cleaner.scan(cleaner.build_categories(self.env)) if c.key in ("temp", "installers")]
        res = cleaner.delete(cats)
        self.assertEqual(res.freed, 500)
        self.assertEqual(res.recycled, 1000)
        self.assertEqual(res.failed, 0)
        self.assertFalse(os.path.exists(os.path.join(self.env["TEMP"], "old.tmp")))
        self.assertTrue(os.path.exists(os.path.join(self.env["TEMP"], "new.tmp")))
        self.assertTrue(os.path.exists(os.path.join(self.trash, "setup.exe")))
        self.assertTrue(os.path.exists(os.path.join(self.env["USERPROFILE"], "Downloads", "notes.txt")))

    def test_changed_file_is_not_touched(self):
        self.populate()
        cats = [c for c in cleaner.scan(cleaner.build_categories(self.env)) if c.key == "temp"]
        p = os.path.join(self.env["TEMP"], "old.tmp")
        with open(p, "ab") as f:
            f.write(b"more data")
        res = cleaner.delete(cats)
        self.assertEqual(res.changed, 1)
        self.assertEqual(res.freed, 0)
        self.assertTrue(os.path.exists(p))

    def test_vanished_file_is_ignored(self):
        self.populate()
        cats = [c for c in cleaner.scan(cleaner.build_categories(self.env)) if c.key == "temp"]
        os.remove(os.path.join(self.env["TEMP"], "old.tmp"))
        res = cleaner.delete(cats)
        self.assertEqual((res.freed, res.failed, res.changed), (0, 0, 0))

    def test_item_outside_roots_is_refused(self):
        self.populate()
        outside = os.path.join(self.d, "precious.txt")
        touch(outside, 10, 400)
        cat = cleaner.Category("temp", "t", "h", "delete", True, [self.env["TEMP"]])
        st = os.stat(outside)
        cat.items = [cleaner.Item(outside, st.st_size, st.st_mtime)]
        res = cleaner.delete([cat])
        self.assertEqual(res.failed, 1)
        self.assertTrue(os.path.exists(outside))

    def test_symlink_not_followed(self):
        self.populate()
        target = os.path.join(self.d, "secret")
        touch(os.path.join(target, "s.tmp"), 10, 5)
        link = os.path.join(self.env["TEMP"], "link")
        try:
            os.symlink(target, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("collegamenti simbolici non disponibili")
        cats = [c for c in cleaner.scan(cleaner.build_categories(self.env)) if c.key == "temp"]
        cleaner.delete(cats)
        self.assertTrue(os.path.exists(os.path.join(target, "s.tmp")))

    def test_odd_temp_variable_is_ignored(self):
        env = dict(self.env)
        env["TEMP"] = self.d  # punta fuori dal profilo: non va usata
        touch(os.path.join(self.d, "other", "x.tmp"), 10, 5)
        cats = {c.key: c for c in cleaner.scan(cleaner.build_categories(env))}
        self.assertNotIn("temp", cats)

    def test_scan_big(self):
        touch(os.path.join(self.env["USERPROFILE"], "Videos", "big.bin"), 3 * 1024 * 1024, 200)
        touch(os.path.join(self.env["USERPROFILE"], "Videos", "recent.bin"), 3 * 1024 * 1024, 1)
        touch(os.path.join(self.env["USERPROFILE"], "AppData", "x.bin"), 3 * 1024 * 1024, 200)
        touch(os.path.join(self.env["USERPROFILE"], "Videos", "small.bin"), 100, 200)
        cat = cleaner.scan_big(self.env["USERPROFILE"], 1, 90)
        self.assertEqual([os.path.basename(i.path) for i in cat.items], ["big.bin"])

    def test_cancel(self):
        import threading
        self.populate()
        ev = threading.Event()
        ev.set()
        with self.assertRaises(cleaner.Cancelled):
            cleaner.scan(cleaner.build_categories(self.env), ev)


if __name__ == "__main__":
    unittest.main()
