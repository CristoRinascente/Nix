# Orb – interfaccia visiva per l'assistente vocale

Piccola sfera animata (C++ + Raylib + GLSL) che compare sullo schermo quando chiami l'assistente.
Ha occhi che seguono il mouse, espressioni, animazioni di ingresso e uscita e dei **tag** a pillola
(fatto, non ho capito, attendo). Un altro programma (per esempio uno script Python) la controlla
inviando comandi di testo.

---

## 1. Struttura del progetto

```
Orb/
├── CMakeLists.txt
├── README.md
├── test_orb.py              (script di prova, opzionale)
├── src/
│   ├── main.cpp             logica, animazioni, comandi
│   ├── net.cpp / net.h      ricezione comandi via UDP
├── shaders/
│   ├── orb.fs               disegno della sfera, occhi, goccia
│   └── tag.fs               disegno dei tag a pillola
├── assets/
│   └── InterTight-SemiBold.ttf   font dei tag
└── build/                   generata da CMake (da non versionare)
```

## 2. Compilare e avviare

Requisiti: Windows, MSYS2 (UCRT64) con `g++`, `cmake` e `ninja`, VS Code con le estensioni
**C/C++** e **CMake Tools**, connessione internet alla prima configurazione (Raylib viene
scaricata da CMake).

1. Apri la cartella `Orb` in VS Code.
2. `Ctrl+Shift+P` → **CMake: Configure** (scegli il kit GCC `ucrt64`).
3. `Ctrl+Shift+P` → **CMake: Build**.
4. `Ctrl+Shift+P` → **CMake: Run Without Debugging**, oppure avvia `build/orb.exe`.

La build copia automaticamente `shaders/` e `assets/` accanto a `orb.exe`.

**Importante:** all'avvio l'orb è **nascosto**. Per vederlo manda il comando `show`
(oppure premi **F6**).

Se sposti la cartella del progetto, cancella prima la cartella `build/` e riconfigura.
Per chiudere l'orb: comando `quit`, oppure da PowerShell `taskkill /IM orb.exe /F`.

---

## 3. Come si comanda l'orb

L'orb resta in ascolto su **UDP, 127.0.0.1, porta 50555** (solo questo PC). Ogni messaggio è una
riga di testo in minuscolo. Se l'orb non è in esecuzione il messaggio va perso, senza errori.

### Esempio minimo in Python

```python
import socket

_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def orb(cmd: str):
    _sock.sendto(cmd.encode("utf-8"), ("127.0.0.1", 50555))

orb("show 960 540")
orb("tag done")
orb("hide")
```

### Classe di comodo

```python
import socket

class Orb:
    def __init__(self, host="127.0.0.1", port=50555):
        self._addr = (host, port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(self, cmd: str):
        self._sock.sendto(cmd.encode("utf-8"), self._addr)

    # presenza e posizione
    def show(self, x=None, y=None):
        self.send("show" if x is None else f"show {int(x)} {int(y)}")
    def hide(self):              self.send("hide")
    def move(self, x, y):        self.send(f"move {int(x)} {int(y)}")
    def glide(self, x, y):       self.send(f"glide {int(x)} {int(y)}")

    # stati degli occhi
    def idle(self):              self.send("idle")
    def rest(self):              self.send("rest")
    def working(self):           self.send("working")
    def eye_roll(self):          self.send("eye_roll")
    def stare_down(self):        self.send("stare_down")

    # reazioni
    def ok(self):                self.send("ok")
    def error(self):             self.send("error")

    # tag
    def tag_done(self, text=""):          self.send(f"tag done {text}".strip())
    def tag_notunderstand(self, text=""): self.send(f"tag notunderstand {text}".strip())
    def tag_rest(self, text=""):          self.send(f"tag rest {text}".strip())

    def quit(self):              self.send("quit")
```

---

## 4. Elenco dei comandi

| Comando | Effetto |
|---|---|
| `show` | L'orb compare dove si trova (animazione della goccia). |
| `show X Y` | Compare con il **centro** nel punto (X, Y) dello schermo. |
| `hide` | Esce (si richiude in una goccia che sale). Se c'è un tag visibile, prima esce il tag. |
| `move X Y` | Sposta subito il centro dell'orb in (X, Y). |
| `glide X Y` | Sposta il centro in (X, Y) con uno scivolamento morbido. |
| `idle` | Modalità base: gli occhi seguono il mouse, ammiccamento ogni 4 secondi. |
| `rest` | Modalità di attesa comando (vedi sotto). Resta attiva finché non ne chiami un'altra. |
| `working` | Modalità di esecuzione comando (vedi sotto). Resta attiva finché non ne chiami un'altra. |
| `eye_roll` (o `roll`) | Gli occhi fanno un giro completo a cerchio (1,2 s). |
| `stare_down` (o `stare`) | Zoom rapido +30% e occhi giganti bloccati sul mouse (1 s). |
| `ok` (o `success`) | Una spunta si "scrive" al posto dell'occhio destro. |
| `error` | L'orb vibra e fa un flash rosso (0,7 s), poi torna normale. |
| `tag done [testo]` | Tag verde smeraldo con spunta. |
| `tag notunderstand [testo]` | Tag arancione con triangolo di avviso. |
| `tag rest [testo]` | Tag grigio con tre puntini. |
| `quit` | Chiude il programma. |

Coordinate: pixel dello schermo, con (0, 0) in alto a sinistra del monitor principale. Su più
monitor possono essere negative. Indicano sempre il **centro dell'orb**.

Dopo `show` l'orb parte sempre in modalità `idle`.

---

## 5. Le animazioni

### Ingresso (`show`)
Una goccia cade dall'alto, l'orb nasce da lì e si espande con un piccolo rimbalzo, con un'onda
che si allarga. Gli occhi si aprono alla fine. Durata circa 1,15 s.

### Uscita (`hide`)
Gli occhi si chiudono, l'orb si contrae in una goccia che sale e svanisce. Durata circa 1,1 s.
Se chiami `show` durante l'uscita (o `hide` durante l'ingresso) l'orb aspetta la fine
dell'animazione in corso invece di scattare.

### Idle (`idle`)
Lo sguardo segue il mouse su tutto lo schermo. Leggera fluttuazione verticale.

### Attesa comando (`rest`)
- Oscillazione sinusoidale lenta con effetto respiro.
- Sguardi casuali, ogni 1,2–3,5 secondi circa. Non segue il mouse.
- Palpebre che si socchiudono a caso, e ammiccamenti a intervalli irregolari.
- Ogni circa **15 secondi** (±3) scatta un evento casuale: **25% `eye_roll`**, **15% `stare_down`**,
  altrimenti non succede nulla di speciale.

### Esecuzione comando (`working`)
Lo sguardo va da destra a sinistra e gli occhi cambiano dimensione in prospettiva: a destra
**oO**, a sinistra **Oo**. Ogni tanto guarda in alto.

### Eventi singoli
- **`eye_roll`**: lo sguardo compie un giro completo (360°). Richiamabile in qualsiasi momento.
- **`stare_down`**: zoom dell'orb verso lo schermo (+30%) con piccolo rimbalzo, occhi giganti
  fissi sul mouse, durata 1 secondo, poi tutto torna morbido.

Entrambi funzionano solo con l'orb visibile e non partono se un altro evento singolo è in corso.

### Reazioni (`ok`, `error`)
- **`ok`**: la spunta si disegna al posto dell'occhio destro, resta circa 1 secondo, poi l'occhio
  torna a pillola. Leggero aumento di luce.
- **`error`**: vibrazione orizzontale e flash rosso con alone, durata 0,7 s.

Le reazioni sono indipendenti dai tag: puoi usarle insieme o separatamente.

---

## 6. I tag

Pillole con icona a sinistra e testo a destra, stile glossy, bordo sottile, testo dello stesso
colore del bordo (font Inter Tight SemiBold).

| Comando | Colore | Simbolo | Testi predefiniti (scelti a caso) |
|---|---|---|---|
| `tag done` | verde smeraldo | spunta | fatto, done, ok, ricevuto |
| `tag notunderstand` | arancione caldo | triangolo con punto esclamativo | riprova, non ho capito, come?, ripeti |
| `tag rest` | grigio neutro | tre puntini | aspetto, ricevuto, ok, attendo |

**Testo personalizzato**: scrivilo dopo il tipo, per esempio `tag done tutto fatto`.
Massimo 63 caratteri. Le lettere accentate sono supportate.

### Come si comporta
1. Una pallina esce dall'orb scendendo di poco.
2. Il simbolo appare "scritto" a tratti dentro la pallina.
3. La pallina si espande a pillola.
4. Il testo entra con un effetto flip 3D.
5. Il tag resta visibile **2 secondi**.
6. Il testo si ribalta, la pillola si richiude a pallina e rientra nell'orb salendo.

Regole:
- I tag funzionano solo quando l'orb è **visibile** (non durante l'ingresso o l'uscita).
- Se ne arriva uno nuovo mentre un altro è visibile, il primo esce e poi entra il nuovo.
- Se mandi `hide` con un tag visibile, il tag esce per primo e poi l'orb.

---

## 7. Esempio di flusso

```python
orb = Orb()

orb.show(960, 540)      # wake word riconosciuta: l'orb compare
orb.rest()              # attesa del comando vocale

orb.working()           # comando in esecuzione
orb.tag_done()          # comando riuscito
orb.ok()                # (facoltativo) spunta nell'occhio

orb.rest()              # torna in attesa
# oppure, comando non capito:
orb.error()
orb.tag_notunderstand()

orb.hide()              # fine della conversazione
```

Il flusso esatto (quando chiamare `rest`, `working` e così via) dipende dal tuo script: l'orb
esegue semplicemente l'ultimo comando ricevuto.

---

## 8. Prove senza lo script dell'assistente

**Tasti globali** (funzionano anche se la finestra dell'orb non ha il focus):

| Tasto | Comando |
|---|---|
| F6 | `show` |
| F7 | `hide` |
| F8 | `error` |
| F9 | `ok` |

**Script interattivo** `test_orb.py`:

```python
import socket

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print("Comandi: show, hide, idle, rest, working, roll, stare, ok, error,")
print("         move x y, glide x y, tag done|notunderstand|rest [testo], quit")
print("Invio vuoto = esci dallo script")
while True:
    cmd = input("> ").strip()
    if not cmd:
        break
    s.sendto(cmd.encode(), ("127.0.0.1", 50555))
```

---

## 9. Personalizzazione

Quasi tutto si regola con numeri in `src/main.cpp` e nei file `.fs`. Dopo ogni modifica serve
una nuova build.

| Cosa | Dove |
|---|---|
| Durata ingresso / uscita dell'orb | `kShowDur`, `kHideDur` |
| Durata errore / spunta | `kErrorDur`, `kSuccessDur` |
| Durata `eye_roll` / `stare_down` | `kRollDur`, `kStareDur` |
| Intensità della vibrazione dell'errore | `0.09f` nella sezione "errore" del ciclo principale |
| Timer degli eventi casuali nel `rest` | `15.0` in `updateEyes` |
| Probabilità di `eye_roll` / `stare_down` | `25` e `40` (cioè 25% + 15%) in `updateEyes` |
| Velocità dello sguardo in `working` | `2.6f` in `updateEyes` |
| Effetto oO / Oo | `0.28f` in `updateEyes` |
| Zoom dello `stare_down` | `0.30f`, occhi giganti `0.75f` in `updateEyes` |
| Secondi di permanenza del tag | `kTagHold` |
| Distanza del tag dall'orb | `kTagY` |
| Dimensione del testo dei tag | `kFontSize` |
| Colori dei tag | tabella `kTagCols` |
| Testi predefiniti dei tag | `kTextsDone`, `kTextsNotU`, `kTextsRest` |
| Colori e dimensione dell'orb | `cyan`, `violet` e `R` in `shaders/orb.fs` |
| Porta UDP | `kPort` |

---

## 10. Problemi comuni

- **Non vedo nulla all'avvio**: è normale, l'orb parte nascosto. Manda `show` o premi F6.
- **Il tag non compare**: l'orb deve essere visibile; durante ingresso e uscita i tag vengono ignorati.
- **Il testo del tag manca o il font non si carica**: controlla che esista
  `build/assets/InterTight-SemiBold.ttf` (la copia avviene a ogni build).
- **Messaggio "impossibile aprire la porta UDP"**: un'altra istanza dell'orb è già aperta.
  Chiudila con `taskkill /IM orb.exe /F`.
- **Gli occhi guardano "sfalsati" rispetto al mouse, o l'orb si posiziona in un punto diverso**:
  succede con la scala dello schermo di Windows diversa dal 100%, perché alcune librerie Python
  usano coordinate scalate. Verifica con valori noti (`show 100 100`) e correggi con un fattore.
- **L'orb non risponde ai clic**: è voluto. La finestra lascia passare i clic alle finestre
  sotto, quindi non può nemmeno ricevere il focus.
- **Errore CMake dopo aver spostato la cartella**: cancella la cartella `build/` e riconfigura.
- **Errore di compilazione di uno shader**: leggi il messaggio nel terminale all'avvio di
  `orb.exe` (indica la riga del file `.fs`).
