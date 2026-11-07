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

## Privacy e funzionamento offline

Onyx funziona completamente in locale. La parola di attivazione (openWakeWord) e il riconoscimento vocale (Vosk) girano sul tuo computer: l'audio del microfono non viene mai inviato online, non viene salvato e non passa per nessun servizio esterno. Non servono account né chiavi API, e il progetto non raccoglie né trasmette dati.

Internet serve solo per la preparazione iniziale: installare i pacchetti Python, scaricare i modelli (openWakeWord e Vosk) e compilare l'interfaccia. Dopo, l'ascolto e l'esecuzione dei comandi funzionano senza connessione.



I suoni locali `Suoni` accompagnano apertura, chiusura ed errore; Onyx filtra l'eco della risposta d'errore per non trasformarla in un nuovo comando. Dì `niente` per chiudere l'ascolto del comando. La forma concava e i flare laterali derivano dal componente `EdgeSurface` di Bloom, distribuito con licenza GPL-3.0-only; il codice originale resta nella cartella `UI\BloomSource`.

I comandi collegati includono timer (fino a 24 ore), controlli multimediali, volume regolabile, luminosità, Wi-Fi, Bluetooth, modalità aereo, screenshot, sospensione, desktop, blocco del PC e controlli delle finestre. Puoi dire “aumenta la luminosità dello schermo” o “diminuisci la luminosità”; per il volume, “alza il volume” o “abbassa il volume”. Per ChatGPT, dì “apri chat” o “apri ChatGPT”. Se l'app ChatGPT è installata, Onyx la apre; altrimenti apre `chatgpt.com` nel browser predefinito. Altri esempi: “spegni il Wi-Fi”, “accendi il Bluetooth”, “mostrami i dispositivi”, “attiva modalità aereo”, “disattiva modalità aereo”, “vai al sito YouTube”, “fai uno screenshot”, “fai uno screen della finestra”, “copia l'ultimo screenshot”, “sospendi il PC”, “alza il volume di sette”, “brano successivo”, “ingrandisci”, “mostra nome”, “metti Chrome davanti” e “blocca PC”. Wi-Fi e Bluetooth sono cambiati tramite le API radio di Windows; la modalità aereo di Onyx spegne entrambe le radio e al comando di disattivazione ne ripristina gli stati precedenti. Gli screenshot acquisiscono l'intero desktop o la finestra attiva se la frase nomina la finestra, e vengono salvati in `Screenshot`. Onyx può copiare negli appunti l'immagine dell'ultimo screenshot. Le azioni finestra senza un nome agiscono sulla finestra attiva; se pronunci un nome, Onyx cerca una finestra corrispondente. Se chiedi di avviare un’app già aperta, Onyx la porta davanti invece di lanciarne un'altra; puoi anche dire direttamente il nome dell'app. Il timer mostra un notch interattivo Bloom con conto alla rovescia, pausa/riprendi e annulla; alla scadenza riproduce tre volte l’allarme MP3 in `Suoni`. Il programma stampa anche ciò che ha riconosciuto.

È possibile avviare Netflix, Spotify, WhatsApp, Samsung Notes e Quick Share con frasi come “apri Spotify” o “apri Quick Share”. Se Quick Share è già aperto, Onyx porta la finestra esistente in primo piano. Le cartelle Desktop, Documenti e Download sono disponibili con “apri cartella …”. Per aggiungere cartelle personali, inserisci in `Azioni\cartelle.json` una coppia nome-percorso, per esempio `"Progetti": "C:\\Users\\cris1\\Documents\\Progetti"`.

È possibile selezionare un altro modello con `--modello`. Per esempio, il modello italiano completo va estratto in `Modelli/vosk-model-it-0.22` e avviato in modalità libera; i modelli completi Vosk usano una rete statica e non supportano i test con grammatica ristretta.
