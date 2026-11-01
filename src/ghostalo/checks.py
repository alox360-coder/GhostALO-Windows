"""Controlli di sicurezza e privacy. Tutto in locale; ciò che non si può verificare è 'na', mai 'ok'."""
import datetime
import glob
import json
import os
import re

from . import winutil
from .i18n import tr, trf

# stati: ok, info, warn, bad, na (non verificabile)
RANK = {"ok": 0, "na": 0, "info": 1, "warn": 2, "bad": 3}


class Check:
    def __init__(self, status, title, detail=""):
        self.status = status
        self.title = title
        self.detail = detail


# ---------------------------------------------------------------- sicurezza

def _antivirus():
    rows = winutil.powershell_json(
        "Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct "
        "| Select-Object displayName | ConvertTo-Json -Compress"
    )
    if rows is None:
        return Check("na", tr("Antivirus"), tr("Non sono riuscito a leggerlo."))
    names = sorted({str(r.get("displayName", "")).strip() for r in rows if r.get("displayName")})
    if not names:
        return Check("warn", tr("Antivirus"), tr("Nessun antivirus registrato in Windows."))
    return Check("ok", tr("Antivirus"), ", ".join(names))


def _defender():
    rows = winutil.powershell_json(
        "Get-MpComputerStatus | Select-Object RealTimeProtectionEnabled,AntivirusSignatureAge "
        "| ConvertTo-Json -Compress"
    )
    if not rows:
        return Check("na", tr("Windows Defender"), tr("Non risponde (forse usi un altro antivirus)."))
    r = rows[0]
    if r.get("RealTimeProtectionEnabled") is False:
        return Check("warn", tr("Windows Defender"), tr("Protezione in tempo reale spenta."))
    age = r.get("AntivirusSignatureAge")
    if isinstance(age, int) and age > 7:
        return Check("warn", tr("Windows Defender"), trf("Definizioni non aggiornate da %s giorni.", age))
    return Check("ok", tr("Windows Defender"), tr("Protezione attiva e aggiornata."))


def _firewall():
    rows = winutil.powershell_json("Get-NetFirewallProfile | Select-Object Name,Enabled | ConvertTo-Json -Compress")
    if not rows:
        return Check("na", tr("Firewall"), tr("Non sono riuscito a leggerlo."))
    off = [str(r.get("Name")) for r in rows if r.get("Enabled") in (False, 0)]
    if off:
        return Check("warn", tr("Firewall"), tr("Spento per i profili: ") + ", ".join(off))
    return Check("ok", tr("Firewall"), tr("Attivo su tutti i profili."))


def parse_hotfix_days(text, today=None):
    """Da 'AAAA-MM-GG' ai giorni trascorsi; None se non valido."""
    try:
        d = datetime.datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None
    today = today or datetime.date.today()
    return (today - d).days


def _updates():
    rc, out = winutil.powershell(
        "(Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 1).InstalledOn.ToString('yyyy-MM-dd')"
    )
    days = parse_hotfix_days(out) if rc == 0 else None
    if days is None:
        return Check("na", tr("Aggiornamenti di Windows"), tr("Data dell'ultimo aggiornamento non disponibile."))
    if days > 90:
        return Check("warn", tr("Aggiornamenti di Windows"), trf("Ultimo aggiornamento installato %s giorni fa.", days))
    return Check("ok", tr("Aggiornamenti di Windows"), trf("Ultimo aggiornamento installato %s giorni fa.", days))


def _uac():
    v = winutil.reg_get("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "EnableLUA")
    if v is None:
        return Check("na", tr("Controllo account utente (UAC)"), tr("Non disponibile."))
    if v == 0:
        return Check("bad", tr("Controllo account utente (UAC)"), tr("Disattivato: i programmi possono ottenere privilegi senza chiedere."))
    return Check("ok", tr("Controllo account utente (UAC)"), tr("Attivo."))


def _rdp():
    v = winutil.reg_get("HKLM", r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections")
    if v is None:
        return Check("na", tr("Desktop remoto"), tr("Non disponibile."))
    if v == 0:
        return Check("warn", tr("Desktop remoto"), tr("Attivo: se non ti serve, spegnilo (Impostazioni > Sistema > Desktop remoto)."))
    return Check("ok", tr("Desktop remoto"), tr("Spento."))


def _secure_boot():
    v = winutil.reg_get("HKLM", r"SYSTEM\CurrentControlSet\Control\SecureBoot\State", "UEFISecureBootEnabled")
    if v is None:
        return Check("na", tr("Avvio protetto (Secure Boot)"), tr("Non disponibile o PC con BIOS tradizionale."))
    if v == 1:
        return Check("ok", tr("Avvio protetto (Secure Boot)"), tr("Attivo."))
    return Check("info", tr("Avvio protetto (Secure Boot)"), tr("Non attivo."))


def _bitlocker():
    rc, out = winutil.powershell(
        "(New-Object -ComObject Shell.Application).NameSpace($env:SystemDrive).Self."
        "ExtendedProperty('System.Volume.BitLockerProtection')"
    )
    v = out.strip() if rc == 0 else ""
    if v == "1":
        return Check("ok", tr("Cifratura del disco (BitLocker)"), tr("Attiva sul disco di sistema."))
    if v in ("0", "2"):
        return Check(
            "info", tr("Cifratura del disco (BitLocker)"),
            tr("Non risulta attiva. Su un portatile proteggerebbe i dati in caso di furto (non è disponibile su tutte le edizioni di Windows)."),
        )
    return Check("na", tr("Cifratura del disco (BitLocker)"), tr("Stato non verificabile."))


def _admin_account():
    if winutil.is_admin():
        return Check(
            "info", tr("Account amministratore"),
            tr("Stai usando il programma come amministratore. Per l'uso di tutti i giorni è più sicuro un account standard."),
        )
    return Check("ok", tr("Account amministratore"), tr("Account standard in uso."))


def run_security():
    out = []
    for f in (_antivirus, _defender, _firewall, _updates, _uac, _rdp, _secure_boot, _bitlocker, _admin_account):
        try:
            out.append(f())
        except Exception:
            out.append(Check("na", f.__name__.strip("_"), tr("Controllo non riuscito.")))
    return out


# ---------------------------------------------------------------- privacy

RISKY_DIRS = ("\\temp\\", "\\downloads\\", "\\appdata\\local\\temp", "\\users\\public\\")


def classify_command(cmd):
    """'warn' se il comando parte da una cartella tipica del malware, altrimenti 'info'."""
    c = (cmd or "").lower().replace("/", "\\")
    if any(d in c for d in RISKY_DIRS):
        return "warn"
    if "-enc" in c and "powershell" in c:
        return "warn"
    return "info"


def _startup():
    items = []
    keys = [
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"),
    ]
    for hive, path in keys:
        for name, val in winutil.reg_values(hive, path):
            items.append(Check(classify_command(str(val)), str(name), str(val)))
    startup_dirs = [
        winutil.pj(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
        winutil.pj(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup"),
    ]
    for d in startup_dirs:
        if d and os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.lower() != "desktop.ini":
                    items.append(Check("info", f, d))
    return items


def _tasks():
    rows = winutil.powershell_json(
        "Get-ScheduledTask | Where-Object { $_.TaskPath -notlike '\\Microsoft\\*' } | ForEach-Object { "
        "[pscustomobject]@{Name=$_.TaskName; Exec=(($_.Actions | Select-Object -First 1 | "
        "ForEach-Object { $_.Execute + ' ' + $_.Arguments }))} } | ConvertTo-Json -Compress",
        timeout=40,
    )
    if rows is None:
        return None
    out = []
    for r in rows:
        cmd = str(r.get("Exec") or "").strip()
        if cmd in ("", "None"):
            out.append(Check("info", str(r.get("Name")), tr("comando non disponibile")))
        else:
            out.append(Check(classify_command(cmd), str(r.get("Name")), cmd))
    return out


REMOTE_TOOLS = (
    "anydesk", "teamviewer", "ultraviewer", "rustdesk", "ammyy", "logmein", "realvnc", "tightvnc",
    "ultravnc", "remote utilities", "radmin", "splashtop", "supremo", "chrome remote desktop", "screenconnect",
)
MONITOR_TOOLS = (
    "kidlogger", "spyrix", "refog", "actual spy", "ardamax", "spytech", "keylogger", "revealer", "pc monitor",
    "employee monitoring", "spyagent",
)


def classify_program(name):
    n = (name or "").lower()
    if any(k in n for k in MONITOR_TOOLS):
        return "warn"
    if any(k in n for k in REMOTE_TOOLS):
        return "info"
    return None


def installed_programs():
    names = set()
    paths = [
        ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, base in paths:
        for sub in winutil.reg_subkeys(hive, base):
            n = winutil.reg_get(hive, base + "\\" + sub, "DisplayName")
            if n:
                names.add(str(n))
    return sorted(names)


def _remote_tools():
    found = []
    for n in installed_programs():
        c = classify_program(n)
        if c:
            found.append(Check(c, n, tr("Programma installato.")))
    for p in sorted(winutil.running_processes()):
        c = classify_program(p.replace(".exe", ""))
        if c:
            found.append(Check(c, p, tr("In esecuzione adesso.")))
    return found


def parse_manifest(text):
    """Estrae (nome, accesso_ampio) da un manifest di estensione; None se non valido."""
    try:
        m = json.loads(text)
    except ValueError:
        return None
    name = str(m.get("name", ""))
    perms = [str(p) for p in m.get("permissions", []) if isinstance(p, str)]
    perms += [str(p) for p in m.get("host_permissions", []) if isinstance(p, str)]
    for cs in m.get("content_scripts", []) or []:
        perms += [str(p) for p in cs.get("matches", []) if isinstance(p, str)]
    broad = any(p in ("<all_urls>", "*://*/*", "http://*/*", "https://*/*") for p in perms)
    return name, broad


def resolve_name(name, ext_dir, default_locale=None):
    """Risolve un nome tipo __MSG_appName__ leggendo _locales/<lingua>/messages.json."""
    if not (name.startswith("__MSG_") and name.endswith("__")):
        return name
    key = name[6:-2].lower()
    langs = [l for l in (default_locale, "it", "en", "en_US", "en_GB") if l]
    try:
        langs += [d for d in os.listdir(os.path.join(ext_dir, "_locales")) if d not in langs]
    except OSError:
        return None
    for lang in langs:
        try:
            with open(os.path.join(ext_dir, "_locales", lang, "messages.json"), encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        for k, v in data.items():
            if k.lower() == key and isinstance(v, dict) and v.get("message"):
                return str(v["message"])
    return None


def _extensions():
    local = os.environ.get("LOCALAPPDATA", "")
    roots = {
        "Chrome": r"Google\Chrome\User Data",
        "Edge": r"Microsoft\Edge\User Data",
        "Brave": r"BraveSoftware\Brave-Browser\User Data",
    }
    out = []
    for browser, rel in roots.items():
        base = winutil.pj(local, rel)
        for manifest in glob.glob(os.path.join(base, "*", "Extensions", "*", "*", "manifest.json")):
            try:
                with open(manifest, encoding="utf-8-sig") as f:
                    parsed = parse_manifest(f.read())
            except OSError:
                continue
            if not parsed:
                continue
            name, broad = parsed
            ext_id = manifest.split(os.sep)[-3]
            if name.startswith("__MSG_"):
                try:
                    dl = json.loads(open(manifest, encoding="utf-8-sig").read()).get("default_locale")
                except (OSError, ValueError):
                    dl = None
                name = resolve_name(name, os.path.dirname(manifest), dl) or ext_id
            out.append(Check(
                "info" if broad else "ok", "%s: %s" % (browser, name),
                tr("Può leggere tutti i siti che visiti.") if broad else tr("Accesso limitato."),
            ))
    return out


def parse_hosts(text):
    """Righe attive del file hosts (esclusi commenti e localhost)."""
    out = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and all(h.lower() not in ("localhost", "localhost.localdomain", "broadcasthost") for h in parts[1:]):
            out.append(line)
    return out


def _hosts():
    path = winutil.pj(os.environ.get("SystemRoot", r"C:\Windows"), r"System32\drivers\etc\hosts")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return parse_hosts(f.read())
    except OSError:
        return None


def _proxy():
    enabled = winutil.reg_get("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", "ProxyEnable")
    server = winutil.reg_get("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", "ProxyServer")
    if enabled is None:
        return Check("na", tr("Proxy di sistema"), tr("Non disponibile."))
    if enabled == 1:
        return Check("warn", tr("Proxy di sistema"), tr("Attivo: ") + str(server) + tr(". Se non l'hai impostato tu, il traffico potrebbe passare da altri."))
    return Check("ok", tr("Proxy di sistema"), tr("Nessun proxy impostato."))


class PrivacyReport:
    def __init__(self):
        self.startup = []
        self.tasks = None
        self.remote = []
        self.extensions = []
        self.hosts = None
        self.proxy = None

    def findings(self):
        """Le voci che richiedono attenzione (warn o info rilevanti), con la sezione."""
        out = []
        for c in self.startup:
            if c.status == "warn":
                out.append(Check("warn", tr("Avvio automatico: ") + c.title, c.detail))
        for c in (self.tasks or []):
            if c.status == "warn":
                out.append(Check("warn", tr("Attività pianificata: ") + c.title, c.detail))
        for c in self.remote:
            out.append(Check(c.status, tr("Accesso remoto o monitoraggio: ") + c.title, c.detail))
        if self.hosts:
            out.append(Check("info", tr("File hosts modificato"), trf("%s righe personalizzate.", len(self.hosts))))
        if self.proxy and self.proxy.status in ("warn", "bad"):
            out.append(self.proxy)
        return out

    def incomplete(self):
        return self.tasks is None or self.hosts is None or (self.proxy is not None and self.proxy.status == "na")


def run_privacy():
    r = PrivacyReport()
    steps = [
        ("startup", _startup), ("tasks", _tasks), ("remote", _remote_tools),
        ("extensions", _extensions), ("hosts", _hosts), ("proxy", _proxy),
    ]
    for attr, fn in steps:
        try:
            setattr(r, attr, fn())
        except Exception:
            setattr(r, attr, None if attr in ("tasks", "hosts", "proxy") else [])
    return r
