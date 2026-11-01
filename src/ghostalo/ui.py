"""Interfaccia in stile terminale (verde su nero). Le scansioni girano in un thread a parte."""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

from . import VERSION, checks, cleaner, winutil
from .i18n import tr, trf

BG = "#000000"
GREEN = "#00FF41"
DARK = "#00E63B"
GREY = "#00A329"
ORANGE = "#FFB000"
RED = "#FF3B30"
FONT = ("Consolas", 11)
FONT_B = ("Consolas", 11, "bold")
WRAP = 820


def fmt(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def items(n):
    return tr("1 elemento") if n == 1 else trf("%s elementi", n)


class App:
    def __init__(self, root):
        self.root = root
        root.title("GhostALO")
        root.configure(bg=BG)
        root.geometry("900x720")
        root.minsize(760, 520)
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.token = 0
        self.screen = "menu"
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self.bar = tk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.box = tk.Frame(self.canvas, bg=BG)
        self.win = self.canvas.create_window((0, 0), window=self.box, anchor="nw")
        self.box.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        root.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(int(-e.delta / 120), "units"))
        root.report_callback_exception = self.on_error
        self.poll()
        self.show_menu()

    # ---------- infrastruttura ----------

    def poll(self):
        try:
            while True:
                fn = self.q.get_nowait()
                fn()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def run_bg(self, fn, done):
        """Esegue fn in un thread; done(risultato) gira nel thread dell'interfaccia."""
        self.cancel.set()
        self.cancel = threading.Event()
        cancel = self.cancel
        my = self.token

        def job():
            try:
                res = fn(cancel)
            except cleaner.Cancelled:
                return
            except Exception as e:  # mai bloccare l'interfaccia
                res = e
            self.q.put(lambda: done(res) if my == self.token else None)

        threading.Thread(target=job, daemon=True).start()

    def on_error(self, exc, val, tb):
        import traceback
        txt = "".join(traceback.format_exception(exc, val, tb))
        path = os.path.join(winutil.crash_dir(), "crash.txt")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("GhostALO %s\n%s\n\n%s" % (VERSION, time.ctime(), txt))
        except OSError:
            path = "?"
        messagebox.showerror("GhostALO", tr("Si è verificato un errore. Il rapporto è salvato qui (non è stato inviato da nessuna parte):") + "\n" + path)

    def reset(self):
        self.token += 1
        self.cancel.set()
        for w in self.box.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)

    def label(self, text, color=DARK, bold=False, size=11, pad=4):
        lb = tk.Label(self.box, text=text, fg=color, bg=BG, justify="left", anchor="w",
                      font=("Consolas", size, "bold" if bold else "normal"), wraplength=WRAP)
        lb.pack(fill="x", padx=16, pady=pad)
        return lb

    def title(self, s):
        self.label("> %s_" % s, GREEN, True, 20, 6)
        self.label("=" * 60, GREY, False, 10, 0)

    def section(self, s):
        self.label("## %s ##" % s, GREEN, True, 13, 10)

    def button(self, text, action):
        b = tk.Button(self.box, text=text, command=action, fg=GREEN, bg=BG, activebackground="#004D14",
                      activeforeground=GREEN, relief="solid", bd=1, anchor="w", justify="left",
                      font=FONT_B, padx=10, pady=6, cursor="hand2")
        b.pack(fill="x", padx=16, pady=5)
        return b

    def check(self, text, value, on_change):
        var = tk.BooleanVar(value=value)

        def changed():
            on_change(var.get())

        cb = tk.Checkbutton(self.box, text=text, variable=var, command=changed, fg=GREEN, bg=BG,
                            selectcolor=BG, activebackground=BG, activeforeground=GREEN, anchor="w",
                            justify="left", font=FONT_B, wraplength=WRAP)
        cb.pack(fill="x", padx=16, pady=3)
        return var

    def back(self):
        self.button(tr("[<] Menu principale"), self.show_menu)

    # ---------- menu ----------

    def show_menu(self):
        self.reset()
        self.screen = "menu"
        self.label("> GhostALO_", GREEN, True, 26, 4)
        self.label(tr("Versione") + " " + VERSION + " (beta) - " + tr("per Windows"), GREY, False, 10, 1)
        self.label(tr("Tutto resta nel computer: nessun dato viene inviato."), GREY, False, 10, 1)
        self.label("=" * 60, GREY, False, 10, 0)
        self.button(tr("[>] CONTROLLO RAPIDO\n     un clic: sicurezza e privacy del PC"), self.show_quick)
        self.button(tr("[S] Sicurezza del computer\n     antivirus, firewall, aggiornamenti, cifratura"), self.show_security)
        self.button(tr("[P] Controllo privacy\n     avvio automatico, accesso remoto, estensioni, proxy"), self.show_privacy)
        self.button(tr("[C] Pulizia\n     temporanei, cache, cookie, file recenti"), self.show_clean_home)
        self.button(tr("[G] File grandi e vecchi\n     trova i file che occupano più spazio"), self.show_big_home)
        self.button(tr("[?] Informazioni e limiti"), self.show_about)

    # ---------- controllo rapido ----------

    def show_quick(self):
        self.reset()
        self.screen = "quick"
        self.title(tr("CONTROLLO_RAPIDO"))
        self.label(tr("Controllo il computer…"), GREY)

        def work(cancel):
            return checks.run_security(), checks.run_privacy()

        self.run_bg(work, self.render_quick)

    def render_quick(self, res):
        self.reset()
        self.screen = "quickReport"
        self.title(tr("CONTROLLO_RAPIDO"))
        if isinstance(res, Exception):
            self.label(tr("Non sono riuscito a completare il controllo."), RED)
            self.button(tr("[>] Riprova"), self.show_quick)
            self.back()
            return
        sec, priv = res
        rows = [c for c in sec if c.status in ("warn", "bad", "info")]
        rows += priv.findings()
        rows.sort(key=lambda c: -checks.RANK[c.status])
        na = [c for c in sec if c.status == "na"]
        worst = max([checks.RANK[c.status] for c in rows] or [0])
        incomplete = len(na) >= 3 or priv.incomplete()
        if worst >= 3:
            self.label(tr("[XX] PROBLEMI DA RISOLVERE"), RED, True, 18, 8)
        elif worst >= 2:
            self.label(tr("[!!] DA VERIFICARE") + " (%d)" % len(rows), ORANGE, True, 18, 8)
            self.label(tr("Segnali che richiedono un controllo tuo: non sono la prova di un'infezione."), GREY, False, 10, 2)
        elif incomplete:
            self.label(tr("[??] CONTROLLO INCOMPLETO"), ORANGE, True, 18, 8)
        else:
            self.label(tr("[OK] NESSUN SEGNALE RILEVATO"), GREEN, True, 18, 8)
        self.section(tr("CONTROLLI ESEGUITI"))
        done = [c for c in sec if c.status != "na"]
        self.label("[v] " + trf("Sicurezza del computer: %s controlli completati", len(done)), GREY, False, 10, 1)
        if na:
            self.label("[--] " + trf("%s controlli non verificabili (di solito servono i permessi di amministratore)", len(na)), ORANGE, False, 10, 1)
        self.label("[v] " + tr("Privacy: avvio automatico, attività pianificate, accesso remoto, estensioni, file hosts, proxy"), GREY, False, 10, 1)
        for c in rows:
            col = RED if c.status == "bad" else (ORANGE if c.status == "warn" else DARK)
            self.label(("[XX] " if c.status == "bad" else "[!!] " if c.status == "warn" else "[i] ") + c.title + ("\n   " + c.detail if c.detail else ""), col, False, 11, 4)
        self.label(tr("Nessun segnale non significa nessun virus: questo programma non è un antivirus e non ha un database di malware."), GREY, False, 10, 8)
        self.button(tr("[>] Dettagli sicurezza"), self.show_security)
        self.button(tr("[>] Dettagli privacy"), self.show_privacy)
        self.button(tr("[>] Ripeti controllo"), self.show_quick)
        self.back()

    # ---------- sicurezza ----------

    def show_security(self):
        self.reset()
        self.screen = "security"
        self.title(tr("SICUREZZA_DEL_COMPUTER"))
        self.label(tr("Controllo…"), GREY)
        self.run_bg(lambda cancel: checks.run_security(), self.render_security)

    def render_security(self, res):
        self.reset()
        self.title(tr("SICUREZZA_DEL_COMPUTER"))
        if isinstance(res, Exception):
            self.label(tr("Non sono riuscito a completare il controllo."), RED)
            self.back()
            return
        tag = {"ok": "[OK] ", "info": "[i]  ", "warn": "[!!] ", "bad": "[XX] ", "na": "[--] "}
        col = {"ok": GREEN, "info": DARK, "warn": ORANGE, "bad": RED, "na": GREY}
        for c in res:
            self.label(tag[c.status] + c.title + "\n     " + c.detail, col[c.status], False, 11, 5)
        if not winutil.is_admin():
            self.label(tr("Alcuni controlli sono più completi se avvii il programma come amministratore (clic destro > Esegui come amministratore)."), GREY, False, 10, 8)
        self.button(tr("[>] Ripeti controllo"), self.show_security)
        self.back()

    # ---------- privacy ----------

    def show_privacy(self):
        self.reset()
        self.screen = "privacy"
        self.title(tr("CONTROLLO_PRIVACY"))
        self.label(tr("Controllo…"), GREY)
        self.run_bg(lambda cancel: checks.run_privacy(), self.render_privacy)

    def render_privacy(self, r):
        self.reset()
        self.title(tr("CONTROLLO_PRIVACY"))
        if isinstance(r, Exception):
            self.label(tr("Non sono riuscito a completare il controllo."), RED)
            self.back()
            return
        self.label(tr("Sono indizi, non prove: molti programmi legittimi si avviano da soli o permettono l'accesso remoto."), GREY, False, 10, 4)
        self.section(tr("DA VERIFICARE"))
        f = r.findings()
        if not f:
            self.label(tr("Nessun segnale evidente."), GREEN)
        for c in f:
            self.label(("[!!] " if c.status in ("warn", "bad") else "[i] ") + c.title + ("\n     " + c.detail if c.detail else ""), ORANGE if c.status in ("warn", "bad") else DARK, False, 11, 4)
        self.section(tr("PROGRAMMI ALL'AVVIO") + " (%d)" % len(r.startup))
        for c in r.startup:
            self.label("- " + c.title + "\n    " + c.detail, ORANGE if c.status == "warn" else GREY, False, 10, 2)
        self.section(tr("ATTIVITÀ PIANIFICATE (NON MICROSOFT)"))
        if r.tasks is None:
            self.label("[--] " + tr("Non verificabile."), GREY)
        elif not r.tasks:
            self.label(tr("Nessuna."), GREY)
        for c in (r.tasks or []):
            self.label("- " + c.title + "\n    " + c.detail, ORANGE if c.status == "warn" else GREY, False, 10, 2)
        self.section(tr("ESTENSIONI DEL BROWSER"))
        if not r.extensions:
            self.label(tr("Nessuna estensione trovata (Chrome, Edge, Brave)."), GREY)
        for c in r.extensions:
            self.label("- " + c.title + " - " + c.detail, DARK if c.status == "info" else GREY, False, 10, 2)
        self.section(tr("PROXY"))
        if r.proxy:
            self.label(r.proxy.detail, ORANGE if r.proxy.status == "warn" else GREY)
        self.button(tr("[>] Ripeti controllo"), self.show_privacy)
        self.back()

    # ---------- pulizia ----------

    def show_clean_home(self):
        self.reset()
        self.screen = "cleanHome"
        self.title(tr("PULIZIA"))
        self.label(tr("Cerca file inutili e mostra cosa occupano. Prima di eliminare vedi l'elenco e ti viene chiesta conferma. Cache e temporanei si eliminano subito (i programmi li ricreano); i file tuoi vanno nel Cestino di Windows."), GREY, False, 11, 4)
        self.button(tr("[>] Avvia scansione"), self.start_clean_scan)
        self.back()

    def start_clean_scan(self):
        self.reset()
        self.screen = "cleanScan"
        self.title(tr("PULIZIA"))
        self.label(tr("Scansione in corso…"), GREY)
        self.button(tr("[x] Annulla"), self.show_clean_home)

        def work(cancel):
            cats = cleaner.build_categories()
            return cleaner.scan(cats, cancel)

        self.run_bg(work, self.render_clean)

    def render_clean(self, cats):
        self.reset()
        self.screen = "cleanReport"
        self.title(tr("RISULTATO_PULIZIA"))
        if isinstance(cats, Exception):
            self.label(tr("Non sono riuscito a completare la scansione."), RED)
            self.button(tr("[>] Riprova"), self.start_clean_scan)
            self.back()
            return
        if not cats:
            self.label(tr("Non ho trovato niente da pulire."), GREEN, True, 14)
            self.back()
            return
        self.label(tr("Spunta ciò che vuoi eliminare."), GREY, False, 10, 2)
        total = self.label("", ORANGE, True, 11, 6)
        state = {c.key: c.checked for c in cats}

        def upd():
            sel = [c for c in cats if state[c.key]]
            total.config(text=trf("Selezionato: %s", fmt(sum(c.bytes for c in sel))))

        for c in cats:
            def mk(cat):
                def ch(v):
                    state[cat.key] = v
                    upd()
                return ch
            self.check("%s - %s, %s" % (c.title, items(c.count), fmt(c.bytes)), c.checked, mk(c))
            self.label(c.hint, GREY, False, 10, 0)
            running = cleaner.process_running(c)
            if running:
                self.label(tr("[!!] Chiudi prima: ") + ", ".join(running), ORANGE, False, 10, 0)
            for it in c.items[:3]:
                self.label("   " + it.path, GREY, False, 9, 0)
        upd()

        def go():
            sel = [c for c in cats if state[c.key]]
            if not sel:
                messagebox.showinfo("GhostALO", tr("Nessuna voce selezionata."))
                return
            n = sum(c.count for c in sel)
            b = sum(c.bytes for c in sel)
            msg = trf("Verranno eliminati %s (", items(n)) + fmt(b) + tr("). Le voci dei file tuoi vanno nel Cestino di Windows, le altre vengono eliminate subito. Continuare?")
            if messagebox.askyesno(tr("Conferma eliminazione"), msg):
                self.do_delete(sel)

        self.button(tr("[>] Elimina selezionati"), go)
        self.button(tr("[>] Ripeti scansione"), self.start_clean_scan)
        self.back()

    def do_delete(self, sel):
        self.reset()
        self.screen = "cleanDelete"
        self.title(tr("ELIMINAZIONE"))
        self.label(tr("Eliminazione in corso…"), GREEN, True, 14)
        self.run_bg(lambda cancel: cleaner.delete(sel), self.render_deleted)

    def render_deleted(self, res):
        self.reset()
        self.title(tr("PULIZIA_COMPLETATA"))
        if isinstance(res, Exception):
            self.label(tr("Si è verificato un errore durante l'eliminazione."), RED)
        else:
            if res.freed:
                self.label(tr("Spazio liberato: ") + fmt(res.freed), GREEN, True, 16, 6)
            if res.recycled:
                self.label(tr("Spostati nel Cestino: ") + fmt(res.recycled), GREEN, True, 14, 4)
                self.label(tr("Lo spazio si libera quando svuoti il Cestino di Windows."), GREY, False, 10, 0)
            if res.changed:
                self.label(trf("%s file sono cambiati dopo la scansione e non sono stati toccati.", res.changed), ORANGE)
            if res.failed:
                self.label(trf("%s file non è stato possibile eliminarli (in uso o protetti).", res.failed), ORANGE)
        self.button(tr("[>] Nuova scansione"), self.start_clean_scan)
        self.back()

    # ---------- file grandi ----------

    big_mb = 500
    big_days = 90

    def show_big_home(self):
        self.reset()
        self.screen = "bigHome"
        self.title(tr("FILE_GRANDI_E_VECCHI"))
        self.label(tr("Cerca nella tua cartella utente (esclusa AppData) i file pesanti non modificati da tempo. Vedi l'elenco e confermi tu; i file vanno nel Cestino."), GREY, False, 11, 4)
        self.section(tr("DIMENSIONE MINIMA"))
        for m in (100, 500, 1000):
            self.button(("[x] " if m == self.big_mb else "[ ] ") + "%d MB" % m, lambda m=m: self.set_big(m, None))
        self.section(tr("NON MODIFICATI DA"))
        for d in (30, 90, 365):
            self.button(("[x] " if d == self.big_days else "[ ] ") + trf("%s giorni", d), lambda d=d: self.set_big(None, d))
        self.button(tr("[>] Avvia scansione"), self.start_big_scan)
        self.back()

    def set_big(self, mb, days):
        if mb:
            self.big_mb = mb
        if days:
            self.big_days = days
        self.show_big_home()

    def start_big_scan(self):
        self.reset()
        self.screen = "bigScan"
        self.title(tr("FILE_GRANDI_E_VECCHI"))
        self.label(tr("Scansione in corso…"), GREY)
        self.button(tr("[x] Annulla"), self.show_big_home)
        mb, days = self.big_mb, self.big_days
        home = cleaner.default_env()["USERPROFILE"]
        self.run_bg(lambda cancel: cleaner.scan_big(home, mb, days, cancel), self.render_big)

    def render_big(self, cat):
        self.reset()
        self.screen = "bigReport"
        self.title(tr("FILE_GRANDI_E_VECCHI"))
        if isinstance(cat, Exception):
            self.label(tr("Non sono riuscito a completare la scansione."), RED)
            self.button(tr("[<] Cambia criteri"), self.show_big_home)
            self.back()
            return
        if not cat.items:
            self.label(tr("Nessun file trovato con questi criteri."), GREEN)
            self.button(tr("[<] Cambia criteri"), self.show_big_home)
            self.back()
            return
        chosen = set()
        total = self.label("", ORANGE, True, 11, 6)

        def upd():
            total.config(text=trf("Selezionati: %s file, %s", len(chosen), fmt(sum(i.size for i in cat.items if i.path in chosen))))

        for it in cat.items:
            def mk(item):
                def ch(v):
                    (chosen.add if v else chosen.discard)(item.path)
                    upd()
                return ch
            age = int((time.time() - it.mtime) / 86400)
            self.check("%s\n%s - %s\n%s" % (os.path.basename(it.path), fmt(it.size), trf("%s giorni", age), os.path.dirname(it.path)), False, mk(it))
        upd()

        def go():
            sel = [i for i in cat.items if i.path in chosen]
            if not sel:
                messagebox.showinfo("GhostALO", tr("Nessun file selezionato."))
                return
            if messagebox.askyesno(tr("Eliminare questi file?"), trf("%s file, %s. Vanno nel Cestino di Windows e puoi ripristinarli.", len(sel), fmt(sum(i.size for i in sel)))):
                c2 = cleaner.Category("big", cat.title, cat.hint, "recycle", False, cat.roots)
                c2.items = sel
                self.do_delete([c2])

        self.button(tr("[>] Elimina i selezionati"), go)
        self.button(tr("[<] Cambia criteri"), self.show_big_home)
        self.back()

    # ---------- info ----------

    def show_about(self):
        self.reset()
        self.screen = "about"
        self.title("INFO")
        self.label(tr("GhostALO per Windows usa solo funzioni ufficiali di Windows. Non invia nulla, non ha un database di malware e non elimina niente senza la tua conferma."), DARK)
        self.section(tr("Limiti"))
        self.label(tr("• Non è un antivirus: cerca indizi, non virus.\n• Alcuni controlli richiedono i permessi di amministratore.\n• I risultati sono indizi, non prove.\n• Cache e temporanei si eliminano subito; i file tuoi vanno nel Cestino.\n• Se sospetti un controllo nascosto del PC, il ripristino di Windows è la soluzione più sicura (salva prima i dati e cambia le password da un altro dispositivo)."), GREY, False, 11, 4)
        self.back()


def main():
    from . import i18n
    i18n.init()
    root = tk.Tk()
    App(root)
    root.mainloop()
