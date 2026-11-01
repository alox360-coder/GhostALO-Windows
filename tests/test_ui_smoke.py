"""Prova l'interfaccia con un tkinter finto: scova errori di nomi e di logica in tutte le schermate."""
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


class UiSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tk = mock.MagicMock()
        patcher = mock.patch.dict(sys.modules, {"tkinter": self.tk, "tkinter.messagebox": self.tk.messagebox})
        patcher.start()
        self.addCleanup(patcher.stop)
        import importlib
        import ghostalo
        sys.modules.pop("ghostalo.ui", None)
        if hasattr(ghostalo, "ui"):
            delattr(ghostalo, "ui")
        ui = importlib.import_module("ghostalo.ui")
        from ghostalo import cleaner
        from ghostalo.i18n import set_italian
        set_italian(True)
        self.ui = ui
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        env = {k: os.path.join(self.d, k) for k in ("LOCALAPPDATA", "APPDATA", "USERPROFILE")}
        env["TEMP"] = os.path.join(env["LOCALAPPDATA"], "Temp")
        os.makedirs(env["TEMP"])
        p = os.path.join(env["TEMP"], "old.tmp")
        with open(p, "wb") as f:
            f.write(b"x" * 100)
        os.utime(p, (1, 1))
        self.p = p
        mock.patch.object(cleaner, "default_env", lambda: env).start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(ui.App, "run_bg", lambda s, fn, done: done(fn(threading.Event()))).start()
        mock.patch.object(ui.App, "poll", lambda s: None).start()
        self.app = ui.App(mock.MagicMock())

    def texts(self):
        out = []
        for call in self.tk.Label.call_args_list:
            out.append(call.kwargs.get("text", ""))
        return "\n".join(out)

    def test_all_screens_render(self):
        a = self.app
        for fn in (a.show_menu, a.show_quick, a.show_security, a.show_privacy, a.show_clean_home,
                   a.show_big_home, a.show_about):
            self.tk.reset_mock()
            fn()
            self.assertTrue(self.tk.Label.called or self.tk.Button.called)

    def test_error_results_render(self):
        a = self.app
        err = RuntimeError("boom")
        for fn in (a.render_quick, a.render_security, a.render_privacy, a.render_clean, a.render_big, a.render_deleted):
            fn(err)

    def test_clean_flow_deletes_after_confirm(self):
        a = self.app
        self.tk.messagebox.askyesno.return_value = True
        a.start_clean_scan()
        self.assertIn("File temporanei", self.texts() + "".join(str(c) for c in self.tk.Checkbutton.call_args_list))
        buttons = [c for c in self.tk.Button.call_args_list if "Elimina selezionati" in c.kwargs.get("text", "")]
        self.assertTrue(buttons)
        buttons[0].kwargs["command"]()
        self.assertFalse(os.path.exists(self.p))
        self.assertIn("Spazio liberato", self.texts())

    def test_clean_flow_declined_keeps_file(self):
        a = self.app
        self.tk.messagebox.askyesno.return_value = False
        a.start_clean_scan()
        buttons = [c for c in self.tk.Button.call_args_list if "Elimina selezionati" in c.kwargs.get("text", "")]
        buttons[0].kwargs["command"]()
        self.assertTrue(os.path.exists(self.p))

    def test_english(self):
        from ghostalo.i18n import set_italian
        set_italian(False)
        self.tk.reset_mock()
        self.app.show_about()
        self.assertIn("Limits", self.texts())


if __name__ == "__main__":
    unittest.main()
