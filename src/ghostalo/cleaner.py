"""Pulizia con anteprima. Mai alla cieca: si scansiona, si mostra, si conferma, poi si elimina.

Due modalità:
- 'delete': dati che i programmi ricreano da soli (temporanei, cache). Eliminati subito.
- 'recycle': file dell'utente (Download, file grandi). Vanno nel Cestino di Windows.
Prima di eliminare si ricontrolla che ogni file non sia cambiato dopo la scansione.
"""
import glob
import os
import threading
import time

from . import winutil
from .i18n import tr

DAY = 86400
MAX_VISITED = 400000


class Cancelled(Exception):
    pass


class Item:
    def __init__(self, path, size, mtime):
        self.path = path
        self.size = size
        self.mtime = mtime


class Category:
    def __init__(self, key, title, hint, mode, checked, roots, processes=()):
        self.key = key
        self.title = title
        self.hint = hint
        self.mode = mode          # 'delete' | 'recycle'
        self.checked = checked
        self.roots = roots        # cartelle in cui sono ammessi i file (sicurezza)
        self.processes = processes  # programmi da chiudere prima (nomi .exe in minuscolo)
        self.items = []

    @property
    def bytes(self):
        return sum(i.size for i in self.items)

    @property
    def count(self):
        return len(self.items)


class Result:
    def __init__(self):
        self.freed = 0
        self.failed = 0
        self.changed = 0
        self.recycled = 0


def _check(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def walk_files(root, cancel=None, limit=MAX_VISITED, skip_dirs=()):
    """Genera (percorso, dimensione, data) dei file sotto root, senza seguire collegamenti o giunzioni."""
    stack = [root]
    visited = 0
    skip = {s.lower() for s in skip_dirs}
    while stack and visited < limit:
        _check(cancel)
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                visited += 1
                try:
                    if e.is_symlink() or getattr(e, "is_junction", lambda: False)():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if e.name.lower() in skip:
                            continue
                        stack.append(e.path)
                    elif e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        yield e.path, st.st_size, st.st_mtime
                except OSError:
                    continue


def _under(path, roots):
    try:
        rp = os.path.realpath(path)
        for r in roots:
            rr = os.path.realpath(r)
            if rp == rr or rp.startswith(rr.rstrip("\\/") + os.sep):
                return True
    except OSError:
        pass
    return False


def default_env():
    e = os.environ
    home = e.get("USERPROFILE") or os.path.expanduser("~")
    return {
        "TEMP": e.get("TEMP") or os.path.join(home, "AppData", "Local", "Temp"),
        "LOCALAPPDATA": e.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local"),
        "APPDATA": e.get("APPDATA") or os.path.join(home, "AppData", "Roaming"),
        "USERPROFILE": home,
    }


BROWSERS = {
    # nome: (cartella dati in LOCALAPPDATA, processo)
    "Chrome": (r"Google\Chrome\User Data", "chrome.exe"),
    "Edge": (r"Microsoft\Edge\User Data", "msedge.exe"),
    "Brave": (r"BraveSoftware\Brave-Browser\User Data", "brave.exe"),
}


def _profiles(base):
    out = []
    for name in ("Default",) + tuple("Profile %d" % i for i in range(1, 10)):
        p = os.path.join(base, name)
        if os.path.isdir(p):
            out.append(p)
    return out


def _firefox_profiles(root):
    return [p for p in glob.glob(os.path.join(root, "*")) if os.path.isdir(p)]


def build_categories(env=None):
    """Crea le categorie (vuote) con le cartelle in cui possono lavorare."""
    env = env or default_env()
    local, roam, home, temp = env["LOCALAPPDATA"], env["APPDATA"], env["USERPROFILE"], env["TEMP"]
    # Sicurezza: se TEMP punta fuori dal profilo utente (es. una cartella radice), non lo si usa.
    if not _under(temp, [home, local]):
        temp = os.path.join(local, "Temp")

    cats = []
    cats.append(Category("temp", tr("File temporanei"), tr("Cartella Temp dell'utente: file più vecchi di un giorno che i programmi ricreano."),
                         "delete", True, [temp]))
    cats.append(Category("dumps", tr("Rapporti di errore e dump"), tr("Dump di crash e rapporti di errore di Windows."),
                         "delete", True,
                         [os.path.join(local, "CrashDumps"), winutil.pj(local, r"Microsoft\Windows\WER")]))
    cats.append(Category("thumbs", tr("Miniature e icone in cache"), tr("Cache di Esplora file: Windows la ricrea se serve."),
                         "delete", True, [winutil.pj(local, r"Microsoft\Windows\Explorer")]))
    cache_roots = []
    procs = []
    for name, (rel, proc) in BROWSERS.items():
        base = winutil.pj(local, rel)
        for prof in _profiles(base):
            for sub in ("Cache", "Code Cache", "GPUCache"):
                cache_roots.append(os.path.join(prof, sub))
        procs.append(proc)
    cache_roots += [os.path.join(p, "cache2") for p in _firefox_profiles(winutil.pj(local, r"Mozilla\Firefox\Profiles"))]
    procs.append("firefox.exe")
    cats.append(Category("browser", tr("Cache dei browser"), tr("Cache di Chrome, Edge, Brave e Firefox. Chiudi il browser prima."),
                         "delete", True, cache_roots, tuple(procs)))
    cats.append(Category("recent", tr("Elenco dei file recenti"), tr("Cronologia di Windows dei file aperti di recente (privacy)."),
                         "delete", False,
                         [winutil.pj(roam, r"Microsoft\Windows\Recent")]))
    cookie_roots = []
    for name, (rel, _p) in BROWSERS.items():
        base = winutil.pj(local, rel)
        for prof in _profiles(base):
            cookie_roots.append(os.path.join(prof, "Network"))
    cookie_roots += _firefox_profiles(winutil.pj(roam, r"Mozilla\Firefox\Profiles"))
    cats.append(Category("cookies", tr("Cookie dei browser"), tr("Attenzione: dopo averli eliminati vieni disconnesso dai siti. Chiudi il browser prima."),
                         "delete", False, cookie_roots, tuple(procs)))
    cats.append(Category("installers", tr("Installer vecchi in Download"),
                         tr("File .exe, .msi, .iso e archivi in Download non modificati da oltre 90 giorni. Vanno nel Cestino."),
                         "recycle", False, [os.path.join(home, "Downloads")]))
    return cats


COOKIE_NAMES = ("cookies", "cookies-journal", "cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm")
INSTALLER_EXT = (".exe", ".msi", ".msix", ".iso", ".zip", ".rar", ".7z")


def _accept(cat, path, mtime, now):
    name = os.path.basename(path).lower()
    if cat.key == "temp":
        return now - mtime > DAY
    if cat.key == "dumps":
        return True
    if cat.key == "thumbs":
        return name.startswith(("thumbcache_", "iconcache_"))
    if cat.key == "browser":
        return True
    if cat.key == "recent":
        return name.endswith(".lnk") or "destinations" in path.lower()
    if cat.key == "cookies":
        return name in COOKIE_NAMES
    if cat.key == "installers":
        return name.endswith(INSTALLER_EXT) and now - mtime > 90 * DAY
    return False


def scan(cats, cancel=None, now=None):
    """Riempie le categorie. Non modifica nulla."""
    now = now or time.time()
    for cat in cats:
        cat.items = []
        seen = set()
        for root in cat.roots:
            if not os.path.isdir(root):
                continue
            for path, size, mtime in walk_files(root, cancel):
                if path in seen:
                    continue
                if _accept(cat, path, mtime, now):
                    seen.add(path)
                    cat.items.append(Item(path, size, mtime))
    return [c for c in cats if c.count > 0]


def scan_big(root, min_mb, age_days, cancel=None, now=None, limit_results=40):
    """File grandi e non modificati da tempo nel profilo utente (esclusa AppData). Non modifica nulla."""
    now = now or time.time()
    cat = Category("big", tr("File grandi e vecchi"), tr("File pesanti non modificati da tempo. Vanno nel Cestino."),
                   "recycle", False, [root])
    min_bytes = min_mb * 1024 * 1024
    found = []
    for path, size, mtime in walk_files(root, cancel, skip_dirs=("AppData", "$Recycle.Bin")):
        if size >= min_bytes and now - mtime > age_days * DAY:
            found.append(Item(path, size, mtime))
    found.sort(key=lambda i: i.size, reverse=True)
    cat.items = found[:limit_results]
    return cat


def process_running(cat):
    if not cat.processes:
        return []
    running = winutil.running_processes()
    return sorted(p for p in cat.processes if p in running)


def delete(cats, cancel=None):
    """Elimina gli elementi delle categorie. Ricontrolla ogni file prima di toccarlo."""
    res = Result()
    for cat in cats:
        for it in cat.items:
            _check(cancel)
            try:
                st = os.stat(it.path, follow_symlinks=False)
            except OSError:
                continue  # già sparito
            if st.st_size != it.size or abs(st.st_mtime - it.mtime) > 1.0:
                res.changed += 1
                continue
            if os.path.islink(it.path) or not _under(it.path, cat.roots):
                res.failed += 1
                continue
            if cat.mode == "recycle":
                if winutil.recycle(it.path):
                    res.recycled += it.size
                else:
                    res.failed += 1
            else:
                try:
                    os.remove(it.path)
                    res.freed += it.size
                except OSError:
                    res.failed += 1
    return res
