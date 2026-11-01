# GhostALO per Windows (beta)

Programma per Windows in stile terminale (verde su nero) per controllare sicurezza e privacy del PC e fare pulizia.
Versione "gemella" dell'app Android GhostALO: stessa filosofia, ma è un programma scritto da zero.

- **Controllo rapido**: un clic per vedere se qualcosa richiede attenzione. Distingue ciò che è stato controllato da ciò che non si è potuto verificare.
- **Sicurezza del computer**: antivirus registrato, Windows Defender, firewall, aggiornamenti, UAC, Desktop remoto, Secure Boot, BitLocker, account amministratore.
- **Controllo privacy**: programmi all'avvio, attività pianificate non Microsoft, programmi di accesso remoto o di monitoraggio, estensioni dei browser con accesso ampio, file hosts modificato, proxy di sistema.
- **Pulizia**: file temporanei, rapporti di errore, miniature, cache dei browser, elenco dei file recenti, cookie, installer vecchi in Download. Si vede l'elenco, si conferma, e prima di eliminare si ricontrolla che i file non siano cambiati.
- **File grandi e vecchi**: nella cartella utente, con soglia a scelta. I file vanno nel Cestino di Windows.

Cache e temporanei si eliminano subito (i programmi li ricreano). I file dell'utente vanno sempre nel Cestino.

## Limiti

- Non è un antivirus e non ha un database di malware: cerca indizi, non virus.
- Alcuni controlli richiedono i permessi di amministratore; se non sono verificabili lo dice, non li dà per buoni.
- Non invia nulla: non usa la rete.
- Il file `.exe` non è firmato digitalmente: Windows può mostrare l'avviso SmartScreen ("Esegui comunque").

## Scaricare e verificare

Gli `.exe` sono nella sezione **Releases**, con il file `GhostALO.exe.sha256`: confronta l'impronta SHA-256 del file scaricato.

## Sviluppo

```
python -m unittest discover -s tests -v
python -m PyInstaller --onefile --windowed --name GhostALO --paths src main.py
```

I test girano anche fuori da Windows (con un'interfaccia finta). La compilazione avviene in GitHub Actions (`.github/workflows/build.yml`).
