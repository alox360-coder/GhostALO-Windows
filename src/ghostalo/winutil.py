"""Funzioni di basso livello per Windows. Ogni errore diventa un risultato 'non disponibile'."""
import json
import os
import shutil
import subprocess
import sys

IS_WIN = os.name == "nt"
_NO_WINDOW = 0x08000000 if IS_WIN else 0

try:
    import winreg  # type: ignore
except ImportError:  # non Windows (test)
    winreg = None


def pj(base, rel):
    """Unisce una cartella base e un percorso scritto con il backslash di Windows."""
    return os.path.join(base, *rel.split("\\"))


def run(cmd, timeout=25):
    """Esegue un comando. Restituisce (codice, testo) oppure (None, '') se fallisce."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            errors="replace", creationflags=_NO_WINDOW, stdin=subprocess.DEVNULL,
        )
        return p.returncode, p.stdout or ""
    except Exception:
        return None, ""


def powershell(script, timeout=30):
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout,
    )


def powershell_json(script, timeout=30):
    """Esegue uno script che stampa JSON. Restituisce una lista (anche vuota) o None se non disponibile."""
    rc, out = powershell(script, timeout)
    if rc is None or rc != 0:
        return None
    out = out.strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, list) else [data]


def reg_get(hive, path, name):
    """Legge un valore del registro; None se manca o non è leggibile."""
    if winreg is None:
        return None
    try:
        h = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive]
        with winreg.OpenKey(h, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def reg_values(hive, path):
    """Elenco (nome, valore) di una chiave; lista vuota se manca."""
    out = []
    if winreg is None:
        return out
    try:
        h = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive]
        with winreg.OpenKey(h, path) as k:
            i = 0
            while True:
                try:
                    n, v, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                out.append((n, v))
                i += 1
    except OSError:
        pass
    return out


def reg_subkeys(hive, path):
    out = []
    if winreg is None:
        return out
    try:
        h = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}[hive]
        with winreg.OpenKey(h, path) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumKey(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


def is_admin():
    if not IS_WIN:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def running_processes():
    """Nomi dei processi attivi in minuscolo (tasklist, indipendente dalla lingua)."""
    rc, out = run(["tasklist", "/fo", "csv", "/nh"], 20)
    names = set()
    if rc != 0:
        return names
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('"'):
            names.add(line.split('","')[0].strip('"').lower())
    return names


def recycle(path):
    """Sposta un file o una cartella nel Cestino di Windows. True se riuscito.
    Fuori da Windows (solo test) sposta in una cartella di prova."""
    if not IS_WIN:
        try:
            dest = os.path.join(os.path.expanduser("~"), ".ghostalo_test_trash")
            os.makedirs(dest, exist_ok=True)
            base = os.path.basename(path.rstrip("/\\"))
            target = os.path.join(dest, base)
            n = 1
            while os.path.exists(target):
                target = os.path.join(dest, "%s.%d" % (base, n))
                n += 1
            shutil.move(path, target)
            return True
        except Exception:
            return False
    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 3
        FOF_SILENT = 0x0004
        FOF_NOCONFIRMATION = 0x0010
        FOF_ALLOWUNDO = 0x0040
        FOF_NOERRORUI = 0x0400
        op = SHFILEOPSTRUCTW()
        op.hwnd = None
        op.wFunc = FO_DELETE
        op.pFrom = os.path.abspath(path) + "\0"
        op.pTo = None
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return rc == 0 and not op.fAnyOperationsAborted
    except Exception:
        return False


def crash_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "GhostALO")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def resource_path(rel):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)
