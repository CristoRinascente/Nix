# Onyx
Onyx è un progetto personale: un assistente vocale per Windows che si attiva con la parola chiave "Onyx" e trascrive ed esegue comandi in italiano. Il progetto è in sviluppo e verrà ampliato e sistemato col tempo, quindi alcune parti possono cambiare o essere incomplete.

Le cartelle principali sono `Azioni` (motore vocale e configurazione), `UI\BloomSource` (notch), `Suoni` (file audio originali) e `PowerShell` (script). I log, i modelli e gli screenshot restano nelle rispettive cartelle alla radice.

## Modelli

I modelli stanno nella cartella `models` alla radice del progetto.

**Parola di attivazione (`models/onyx.onnx`).** È un modello openWakeWord addestrato da me seguendo le istruzioni del repository ufficiale di openWakeWord. È già incluso in questo repository. Il pacchetto `openwakeword` richiede inoltre i modelli di base (melspectrogram ed embedding), che si scaricano una sola volta con:

    python -c "import openwakeword; openwakeword.utils.download_models()"

**Riconoscimento vocale (Vosk).** Il modello Vosk italiano **non è incluso nel repository** perché pesa oltre 2 GB e supera il limite di GitHub. Va scaricato a parte:

1. Scarica `vosk-model-it-0.22` da https://alphacephei.com/vosk/models
2. Estrailo dentro `models`, in modo da avere `models/vosk-model-it-0.22`
3. Controlla che dentro ci siano direttamente le cartelle `am`, `conf` e `graph`, senza una seconda cartella con lo stesso nome annidata dentro.

È possibile usare un altro modello con `--modello`.

## Calibrare il riconoscimento della parola di attivazione

Lo strumento `Azioni\calibra_vosk.py` usa il modello Vosk italiano già presente in `Modelli/vosk-model-small-it-0.22`. Ascolta dal microfono senza inviare audio online e stampa ogni frase riconosciuta dopo una breve pausa.

Per avviare l'ascolto di “Ehi Onix” con il modello Vosk italiano completo, usa `Azioni\ascolta_onix.py`. L'interfaccia usa la grafica del notch Bloom, con forme morbide e animazioni spring, e si collega al motore Python tramite una pipe locale. Compare solo quando Onyx viene chiamato; durante il parlato mostra la trascrizione, si ritrae dopo un comando riuscito e resta aperta con un lieve segnale rosso se deve riprovare. I suoni locali `Suoni` accompagnano apertura, chiusura ed errore; Onyx filtra l'eco della risposta d'errore per non trasformarla in un nuovo comando. Dì `niente` per chiudere l'ascolto del comando. La forma concava e i flare laterali derivano dal componente `EdgeSurface` di Bloom, distribuito con licenza GPL-3.0-only; il codice originale resta nella cartella `UI\BloomSource`.

I comandi collegati includono timer (fino a 24 ore), controlli multimediali, volume regolabile, luminosità, Wi-Fi, Bluetooth, modalità aereo, screenshot, sospensione, desktop, blocco del PC e controlli delle finestre. Puoi dire “aumenta la luminosità dello schermo” o “diminuisci la luminosità”; per il volume, “alza il volume” o “abbassa il volume”. Per ChatGPT, dì “apri chat” o “apri ChatGPT”. Se l'app ChatGPT è installata, Onyx la apre; altrimenti apre `chatgpt.com` nel browser predefinito. Altri esempi: “spegni il Wi-Fi”, “accendi il Bluetooth”, “mostrami i dispositivi”, “attiva modalità aereo”, “disattiva modalità aereo”, “vai al sito YouTube”, “fai uno screenshot”, “fai uno screen della finestra”, “copia l'ultimo screenshot”, “sospendi il PC”, “alza il volume di sette”, “brano successivo”, “ingrandisci”, “mostra nome”, “metti Chrome davanti” e “blocca PC”. Wi-Fi e Bluetooth sono cambiati tramite le API radio di Windows; la modalità aereo di Onyx spegne entrambe le radio e al comando di disattivazione ne ripristina gli stati precedenti. Gli screenshot acquisiscono l'intero desktop o la finestra attiva se la frase nomina la finestra, e vengono salvati in `Screenshot`. Onyx può copiare negli appunti l'immagine dell'ultimo screenshot. Le azioni finestra senza un nome agiscono sulla finestra attiva; se pronunci un nome, Onyx cerca una finestra corrispondente. Se chiedi di avviare un’app già aperta, Onyx la porta davanti invece di lanciarne un'altra; puoi anche dire direttamente il nome dell'app. Il timer mostra un notch interattivo Bloom con conto alla rovescia, pausa/riprendi e annulla; alla scadenza riproduce tre volte l’allarme MP3 in `Suoni`. Il programma stampa anche ciò che ha riconosciuto.

È possibile avviare Netflix, Spotify, WhatsApp, Samsung Notes e Quick Share con frasi come “apri Spotify” o “apri Quick Share”. Se Quick Share è già aperto, Onyx porta la finestra esistente in primo piano. Le cartelle Desktop, Documenti e Download sono disponibili con “apri cartella …”. Per aggiungere cartelle personali, inserisci in `Azioni\cartelle.json` una coppia nome-percorso, per esempio `"Progetti": "C:\\Users\\cris1\\Documents\\Progetti"`.

È possibile selezionare un altro modello con `--modello`. Per esempio, il modello italiano completo va estratto in `Modelli/vosk-model-it-0.22` e avviato in modalità libera; i modelli completi Vosk usano una rete statica e non supportano i test con grammatica ristretta.

L'interfaccia Bloom integrata richiede Bun, Rust stable con target MSVC e i C++ Build Tools di Visual Studio. Dopo averli installati, apri PowerShell in questa cartella e compila l'interfaccia una volta:

```powershell
.\PowerShell\Compila-Interfaccia-Onyx.ps1
```

Poi esegui una volta la preparazione Python:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r Azioni\requirements.txt
```

Dopo aver modificato Bloom o aggiunto risorse all'interfaccia, aggiorna e riavvia Onyx con:

```powershell
.\Riavvia-Onyx.cmd
```

Questo comando ferma l'ascolto, ricompila l'interfaccia Bloom e il launcher della tray, poi riavvia Onyx. `PowerShell\Avvia-Onyx.ps1` da solo avvia l'ultima interfaccia già compilata e non ricompila i sorgenti.

L'installazione dei pacchetti Python e la prima compilazione richiedono internet. Dopo la preparazione, l'ascolto, il modello e l'interfaccia funzionano offline. La dock Bloom, la barra di Windows e gli aggiornamenti online Bloom non vengono avviati da Onyx.

Avvia la calibrazione:

```powershell
.\.venv\Scripts\python.exe .\Azioni\calibra_vosk.py
```

Avvia il rilevatore di “Ehi Onix”:

```powershell
.\.venv\Scripts\python.exe .\Azioni\ascolta_onix.py
```

Compila l'applicazione con icona nell'area di notifica con `PowerShell\Compila-Onyx.ps1`. Poi avvia `Onyx.exe` oppure usa lo script `PowerShell\Avvia-Onyx.ps1` per lanciarlo in background senza finestra del terminale:

```powershell
.\PowerShell\Avvia-Onyx.ps1
```

Per fermare solo l'ascolto:

```powershell
.\PowerShell\Ferma-Onyx.ps1
```

Al primo avvio Onyx si registra per l'avvio automatico quando accedi a Windows e inizia subito ad ascoltare “Ehi Onix”. L'icona compare vicino all'orologio: dal menu puoi mettere in pausa o riprendere l'ascolto, aprire i log, disattivare l'avvio automatico o uscire da Onyx. `PowerShell\Ferma-Onyx.ps1` ferma l'ascolto senza chiudere l'icona; per uscire completamente usa **Esci da Onyx** dal menu dell'icona.

Le trascrizioni sono registrate in `logs/onyx.log`; gli errori audio e tecnici in `logs/onyx-error.log`. Per vedere il log mentre Onyx gira:

Dal menu dell'icona Onyx, **Riavvia** esegue la procedura completa: arresta Onyx e i processi figli, ricompila Bloom e il launcher, quindi riavvia l'applicazione. La stessa procedura è disponibile con `Riavvia-Onyx.cmd`.

```powershell
Get-Content .\logs\onyx.log -Wait
```

Per confrontare il riconoscimento libero con la grammatica ristretta alla parola candidata `onix`, avvia una sessione:

```powershell
.\.venv\Scripts\python.exe .\Azioni\calibra_vosk.py --grammatica-onix
```

Per provare la frase più distintiva “Ehi Onix”, usa invece:

```powershell
.\.venv\Scripts\python.exe .\Azioni\calibra_vosk.py --grammatica-ehi-onix
```

Per provare il modello italiano completo dopo averlo scaricato ed estratto:

```powershell
.\.venv\Scripts\python.exe .\Azioni\calibra_vosk.py --modello .\Modelli\vosk-model-it-0.22
```

Fai prove pronunciando “Ehi Onix” e poi parlando normalmente senza chiamarlo. La modalità ristretta può forzare l’ipotesi anche su parole diverse: serve solo a valutare il compromesso tra riconoscimenti corretti e falsi allarmi, non è ancora il rilevatore definitivo.

Pronuncia “Onyx” più volte, lasciando una breve pausa tra le chiamate. Annota le trascrizioni stampate; premi `Ctrl+C` per terminare. Questo strumento è intenzionalmente visibile nel terminale per poter osservare i risultati.



