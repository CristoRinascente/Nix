"""Ascolta con il modello Vosk italiano completo e risponde alla chiamata di Onyx."""

from __future__ import annotations

import argparse
import ctypes
import difflib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path

import sounddevice as sd
from vosk import KaldiRecognizer, Model, SetLogLevel
from onyx_overlay_client import OverlayClient
import numpy as np
from openwakeword.model import Model as WakeModel

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "vosk-model-it-0.22"
WAKE_MODEL_PATH = ROOT / "models" / "onyx.onnx"
WAKE_THRESHOLD = 0.7
WAKE_COOLDOWN_SECONDS = 1.0
CONTROL_POLL_SECONDS = 0.25
SAMPLE_RATE = 16_000
BLOCK_SIZE = 1_280
VOLUME_STEPS = 5
ERROR_CUE_ECHO_GUARD_SECONDS = 2.2
VK_VOLUME_UP = 0xAF
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_MUTE = 0xAD
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_LWIN = 0x5B
VK_TAB = 0x09
VK_F11 = 0x7A
KEYEVENTF_KEYUP = 0x0002
NUMBER_WORDS = {
    "uno": 1, "una": 1, "un": 1,
    "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    "undici": 11, "dodici": 12, "tredici": 13, "quattordici": 14,
    "quindici": 15, "sedici": 16, "diciassette": 17, "diciotto": 18,
    "diciannove": 19, "venti": 20, "ventuno": 21, "ventidue": 22,
    "ventitre": 23, "ventitré": 23, "ventiquattro": 24, "venticinque": 25,
    "ventisei": 26, "ventisette": 27, "ventotto": 28, "ventinove": 29,
    "trenta": 30, "quaranta": 40, "cinquanta": 50, "sessanta": 60,
}
WAKE_TRANSCRIPTIONS = {
    ("onix",),
    ("e", "onix"),
    ("modix",),
    ("hodge",),
    ("kronic",),
    ("helix",),
    ("unix",),
    ("policy",),
    ("oris",),
    ("phoenix",),
    ("oh", "modix"),
    ("ehi", "onix"),
    ("ehi", "joe", "wright"),
    ("ehi", "joe"),
    ("ehi", "x"),
    ("ehi", "alex"),
    ("ehi", "olive"),
    ("e", "olive"),
    ("ehi", "modi"),
    ("ehi", "ogni"),
    ("ehi", "c"),
    ("ehi", "policy"),
    ("ehi", "unix"),
    ("e", "unix"),
    ("re", "onix"),
    ("ehi", "jones"),
    ("ehi", "nick"),
    ("ehi", "hodges"),
    ("e", "hodgins"),
    ("ehi", "hodgins"),
    ("e", "unife"),
}
APP_IDS = {
    "netflix": "4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App",
    "spotify": "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
    "whatsapp": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App",
    "samsung notes": "SAMSUNGELECTRONICSCoLtd.SamsungNotes_wyx1vj98g3asy!App",
    "quick share": "SAMSUNGELECTRONICSCoLtd.SamsungQuickShare_wyx1vj98g3asy!App",
}
APP_ALIASES = {
    "netflix": (("netflix",), ("net", "flix")),
    "spotify": (("spotify",), ("spot", "ify"), ("spoty", "fi")),
    "whatsapp": (("whatsapp",), ("whats", "app"), ("what", "s", "app"), ("whatsup",)),
    "samsung notes": (("samsung", "notes"), ("samsung", "note"), ("samsung", "nots")),
    "quick share": (("quick", "share"), ("quickshare",), ("quik", "share"), ("quick", "shear"), ("quick", "shar")),
}
LAUNCH_VERBS = {"apri", "apre", "aprire", "avvia", "avviare", "lancia", "lanciare", "start", "esegui", "eseguire"}
CLOSE_VERBS = {"chiudi", "chiudere", "termina", "terminare", "esci", "chiuso"}
MINIMIZE_VERBS = {"riduci", "riduce", "ridurre", "minimizza", "minimizzare"}
ICON_WORDS = {"icona", "icone", "icon"}
WINDOW_VERBS = LAUNCH_VERBS | CLOSE_VERBS | MINIMIZE_VERBS | ICON_WORDS | {"ingrandisci", "massimizza", "nascondi", "mostra", "metti", "porta", "davanti", "attiva", "nome"}
FOLDER_OPEN_VERBS = LAUNCH_VERBS | {"mostra", "mostrami", "mostrare", "visualizza", "visualizzare", "vedi", "vedere", "elenca", "elencami", "vai", "portami"}
FOLDER_NOUNS = {"cartella", "cartelle", "folder", "folders", "directory"}


def normalize_app_name(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def start_menu_apps() -> list[tuple[str, str]]:
    """Restituisce (nome visualizzato, AppID) dal catalogo Windows Start."""
    script = (
        "$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "Get-StartApps | Where-Object { $_.AppID } | "
        "Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", timeout=12, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = json.loads(result.stdout or "[]")
        if isinstance(raw, dict):
            raw = [raw]
        return [(str(item["Name"]), str(item["AppID"])) for item in raw if item.get("Name") and item.get("AppID")]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"Catalogo app Windows non disponibile: {exc}", file=sys.stderr)
        return []


def match_start_app(spoken: str, catalog: list[tuple[str, str]]) -> tuple[str, str] | None | str:
    """Ritorna match, None o un messaggio se i candidati sono ambigui."""
    query = normalize_app_name(spoken)
    if not query:
        return None
    ranked = []
    for name, app_id in catalog:
        candidate = normalize_app_name(name)
        ratio = difflib.SequenceMatcher(None, query, candidate).ratio()
        qwords, cwords = set(query.split()), set(candidate.split())
        overlap = len(qwords & cwords) / max(1, len(qwords))
        score = max(ratio, overlap * 0.88)
        if query == candidate:
            score = 1.0
        elif query in candidate or candidate in query:
            score = max(score, 0.9)
        if score >= 0.62:
            ranked.append((score, name, app_id))
    ranked.sort(reverse=True)
    if not ranked:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.09:
        options = ", ".join(item[1] for item in ranked[:3])
        return f"Ho trovato più app simili: {options}. Ripeti il nome più precisamente."
    return ranked[0][1], ranked[0][2]


def start_app_id(app_id: str, name: str) -> tuple[bool, str]:
    if activate_open_app(name):
        return True, f"{name} era già aperto; l'ho portato in primo piano."
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], close_fds=True)
        return True, f"{name} avviato."
    except OSError as exc:
        return False, f"Non sono riuscito ad avviare {name}: {exc}."


def activate_open_app(name: str) -> bool:
    """Riusa una finestra già aperta se titolo o processo corrispondono all'app."""
    needle = normalize_app_name(name)
    aliases = {"chrome": "google chrome", "samsung notes": "samsung notes"}
    needle = aliases.get(needle, needle)
    process_aliases = {"quick share": {"quickshare", "samsungquickshare"}}
    matches = []
    for hwnd, title, process_name in visible_windows():
        process = normalize_app_name(os.path.splitext(process_name)[0])
        title_norm = normalize_app_name(title)
        matched = needle == process or process in process_aliases.get(needle, set()) or needle in title_norm or title_norm in needle
        if needle == "google chrome" and process == "chrome":
            matched = True
        if matched and title:
            matches.append(hwnd)
    if not matches:
        return False
    user32 = ctypes.windll.user32
    hwnd = matches[0]
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    return True


def open_settings(uri: str, description: str) -> tuple[bool, str]:
    try:
        subprocess.Popen(["explorer.exe", uri], close_fds=True)
        return True, description
    except OSError as exc:
        return False, f"Non riesco ad aprire le Impostazioni di Windows: {exc}."


def run_windows_helper(script_name: str, arguments: list[str], timeout: int = 20) -> tuple[bool, str]:
    script = ROOT / "PowerShell" / script_name
    if not script.is_file():
        return False, f"File di supporto mancante: {script_name}."
    powershell = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
    )
    try:
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-STA",
             "-ExecutionPolicy", "Bypass", "-File", str(script), *arguments],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Non riesco a eseguire l'azione di Windows: {exc}."

    for line in reversed(result.stdout.splitlines()):
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(response, dict) and "Ok" in response:
            return bool(response["Ok"]), str(response.get("Messaggio", ""))

    details = (result.stderr or result.stdout).strip().splitlines()
    detail = details[-1] if details else f"codice di uscita {result.returncode}"
    return False, f"Windows non ha completato l'azione: {detail}"


def set_wifi_enabled(enabled: bool) -> tuple[bool, str]:
    state = "on" if enabled else "off"
    return run_windows_helper("Gestisci-Radio.ps1", [f"wifi-{state}"])


def set_bluetooth_enabled(enabled: bool) -> tuple[bool, str]:
    state = "on" if enabled else "off"
    return run_windows_helper("Gestisci-Radio.ps1", [f"bluetooth-{state}"])


def set_airplane_mode(action: str) -> tuple[bool, str]:
    return run_windows_helper("Gestisci-Radio.ps1", [f"airplane-{action}"])


def suspend_computer() -> tuple[bool, str]:
    try:
        result = ctypes.windll.powrprof.SetSuspendState(False, False, False)
        if result:
            return True, "Mando il PC in sospensione."
        return False, "Windows non ha accettato la sospensione del PC."
    except (AttributeError, OSError) as exc:
        return False, f"Non riesco a sospendere il PC: {exc}."


def take_screenshot(window_only: bool = False) -> tuple[bool, str]:
    output_dir = ROOT / "Screenshot"
    filename = f"Onyx_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    destination = output_dir / filename
    arguments = ["-Percorso", str(destination)]
    if window_only:
        arguments.append("-Finestra")
    try:
        success, message = run_windows_helper(
            "Cattura-Schermo.ps1", arguments, timeout=15
        )
        if success and destination.is_file():
            tipo = "della finestra" if window_only else "dello schermo"
            return True, f"Screenshot {tipo} salvato in {destination}."
        return False, message or "Non sono riuscito a salvare lo screenshot."
    except OSError as exc:
        return False, f"Non riesco a salvare lo screenshot: {exc}."


def copy_latest_screenshot() -> tuple[bool, str]:
    return run_windows_helper("Copia-Ultimo-Screenshot.ps1", [], timeout=10)


def open_website(site: str) -> tuple[bool, str]:
    site = site.strip().strip(". ")
    if not site:
        return False, "Dimmi il nome del sito."
    known_sites = {
        "youtube": "youtube.com", "google": "google.com", "gmail": "mail.google.com",
        "facebook": "facebook.com", "instagram": "instagram.com", "netflix": "netflix.com",
        "spotify": "open.spotify.com", "amazon": "amazon.it", "twitch": "twitch.tv",
        "reddit": "reddit.com", "github": "github.com", "whatsapp": "web.whatsapp.com",
    }
    normalized = normalize_app_name(site)
    host = known_sites.get(normalized)
    if host is None:
        host = site.casefold().replace(" ", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.[a-z]{2,}", host):
            host += ".com"
    url = "https://" + host
    candidates = [shutil.which("chrome.exe"),
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe")]
    chrome = next((p for p in candidates if p and os.path.isfile(p)), None)
    if not chrome:
        return False, "Non trovo Google Chrome installato."
    if activate_open_app("Google Chrome"):
        # Chrome reuses its running instance and opens the URL in a tab.
        try:
            subprocess.Popen([chrome, url], close_fds=True)
            return True, f"Apro {host} in Chrome."
        except OSError as exc:
            return False, f"Non riesco ad aprire {host}: {exc}."
    try:
        subprocess.Popen([chrome, url], close_fds=True)
        return True, f"Apro {host} in Chrome."
    except OSError as exc:
        return False, f"Non riesco ad aprire {host}: {exc}."


def open_chatgpt(app_catalog: list[tuple[str, str]] | None = None) -> tuple[bool, str]:
    """Apre l'app ChatGPT se installata, altrimenti usa il browser predefinito."""
    if activate_open_app("ChatGPT"):
        return True, "ChatGPT era già aperto; l'ho portato in primo piano."

    for name, app_id in app_catalog or []:
        if normalize_app_name(name) in {"chatgpt", "chat gpt"}:
            return start_app_id(app_id, name)

    try:
        os.startfile("https://chatgpt.com")
        return True, "ChatGPT aperto nel browser predefinito."
    except (AttributeError, OSError) as exc:
        return False, f"Non riesco ad aprire ChatGPT: {exc}."


def close_process_names(process_names: tuple[str, ...], display_name: str) -> tuple[bool, str]:
    script = "$names = @(" + ",".join(json.dumps(item) for item in process_names) + "); " \
        "$p = Get-Process | Where-Object { $names -contains ($_.ProcessName + '.exe') -or $names -contains $_.ProcessName }; " \
        "if (-not $p) { exit 5 }; $p | Stop-Process -Force -ErrorAction SilentlyContinue; exit 0"
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode == 0:
            return True, f"{display_name} chiuso."
        return False, f"{display_name} non risulta in esecuzione; non ho chiuso nulla."
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Non sono riuscito a chiudere {display_name}: {exc}."


def visible_windows() -> list[tuple[int, str, str]]:
    """Ritorna handle, titolo e nome processo delle finestre visibili."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    rows: list[tuple[int, str, str]] = []
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = ""
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if process:
            path_buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(path_buf))
            if kernel32.QueryFullProcessImageNameW(process, 0, path_buf, ctypes.byref(size)):
                process_name = os.path.basename(path_buf.value)
            kernel32.CloseHandle(process)
        rows.append((int(hwnd), title_buf.value, process_name))
        return True
    user32.EnumWindows(enum_proc(visit), 0)
    return rows


def operate_window(action: str, target: str = "") -> tuple[bool, str]:
    user32 = ctypes.windll.user32
    windows = visible_windows()
    if target:
        needle = normalize_app_name(target)
        candidates = [w for w in windows if needle in normalize_app_name(w[1]) or
                      needle in normalize_app_name(os.path.splitext(w[2])[0]) or
                      ("chrome" in needle and os.path.splitext(w[2])[0].casefold() == "chrome")]
        if not candidates:
            return False, f"Non trovo una finestra aperta per {target}."
        hwnd = candidates[0][0]
        shown_name = target
    else:
        hwnd = int(user32.GetForegroundWindow())
        if not hwnd:
            return False, "Non trovo una finestra attiva."
        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
        shown_name = title_buf.value or "finestra attiva"
    if action == "name":
        return True, f"Finestra attiva: {shown_name}."
    if action == "maximize":
        user32.ShowWindow(hwnd, 3)
        return True, f"Finestra ingrandita: {shown_name}."
    if action == "minimize":
        user32.ShowWindow(hwnd, 6)
        return True, f"Finestra ridotta a icona: {shown_name}."
    if action == "close":
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE, lascia all'app la chiusura normale
        return True, f"Richiesta chiusura per {shown_name}."
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True, f"Finestra portata in primo piano: {shown_name}."


def parse_spoken_number(tokens: list[str]) -> int | None:
    for token in tokens:
        if token.isdigit():
            return int(token)
        if token in NUMBER_WORDS:
            return NUMBER_WORDS[token]
    return None


def chrome_search(query: str) -> tuple[bool, str]:
    if not query.strip():
        return False, "Dimmi cosa cercare su Chrome."
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query.strip())
    candidates = [shutil.which("chrome.exe"),
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
                  os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe")]
    chrome = next((p for p in candidates if p and os.path.isfile(p)), None)
    if not chrome:
        return False, "Non trovo l'eseguibile di Google Chrome."
    try:
        subprocess.Popen([chrome, url], close_fds=True)
        return True, f"Cerco su Chrome: {query.strip()}."
    except OSError as exc:
        return False, f"Non riesco ad avviare la ricerca su Chrome: {exc}."


def close_app_id(app_id: str, name: str) -> tuple[bool, str]:
    if normalize_app_name(name) in {"google chrome", "chrome"} or app_id.casefold() == "chrome":
        return close_process_names(("chrome",), "Google Chrome")
    if "netflix" in normalize_app_name(name):
        return close_process_names(("Netflix",), "Netflix")
    # Termina solo i processi associati all'identità di pacchetto dell'app selezionata.
    script = (
        "$id = " + json.dumps(app_id) + "; "
        "$app = Get-StartApps | Where-Object AppID -eq $id | Select-Object -First 1; "
        "if (-not $app) { exit 3 }; "
        "$pkg = Get-AppxPackage | Where-Object { $app.AppID -like ($_.PackageFamilyName + '! *') -or $app.AppID.StartsWith($_.PackageFamilyName + '!') } | Select-Object -First 1; "
        "if (-not $pkg) { exit 4 }; "
        "$procs = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($pkg.InstallLocation, [StringComparison]::OrdinalIgnoreCase) }; "
        "if (-not $procs) { exit 5 }; "
        "$procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; exit 0"
    )
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=15,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode == 0:
            return True, f"{name} chiuso."
        return False, f"Non riesco a individuare con sicurezza il processo di {name}; non ho chiuso nulla."
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Non sono riuscito a chiudere {name}: {exc}."


def wake_transcription(text: str) -> bool:
    tokens = re.findall(r"[a-zà-öø-ÿ]+", text.casefold())
    return tuple(tokens) in WAKE_TRANSCRIPTIONS


def wake_command_tail(text: str) -> str | None:
    """Return the words spoken after a recognized wake phrase, if present."""
    tokens = tuple(re.findall(r"[a-zà-öø-ÿ]+", text.casefold()))
    for phrase in sorted(WAKE_TRANSCRIPTIONS, key=len, reverse=True):
        if tokens[:len(phrase)] == phrase:
            return " ".join(tokens[len(phrase):])
    return None


def timer_control_intent(text: str) -> str | None:
    """Identify timer commands; cancellation wins if both intents are spoken."""
    words = set(re.findall(r"[a-zà-öø-ÿ]+", text.casefold()))
    if words & {"interrompi", "annulla", "ferma", "cancella", "stop"}:
        return "cancel"
    if words & {"pausa", "pause", "pausare"}:
        return "pause"
    if words & {"riprendi", "continua", "resume"}:
        return "resume"
    return None


def is_direct_timer_control(text: str) -> bool:
    words = set(re.findall(r"[a-zà-öø-ÿ]+", text.casefold()))
    return bool(words & {"timer", "temporizzatore"}) and timer_control_intent(text) is not None


def is_error_cue_echo(text: str) -> bool:
    """Recognize the short spoken error cue so it cannot become a fake command."""
    tokens = re.findall(r"[a-zà-öø-ÿ]+", text.casefold())
    return len(tokens) <= 5 and "capito" in tokens and ("non" in tokens or "ho" in tokens)


def phrase_in_tokens(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    return any(
        tuple(tokens[index : index + len(phrase)]) == phrase
        for index in range(len(tokens) - len(phrase) + 1)
    )


def load_folder_targets() -> dict[tuple[str, ...], str]:
    screenshot_folder = str(ROOT / "Screenshot")
    targets = {
        ("desktop",): "shell:Desktop",
        ("documenti",): "shell:Personal",
        ("download",): "shell:Downloads",
        ("downloads",): "shell:Downloads",
        ("lavoro",): str(Path.home() / "Desktop" / "Lavoro"),
        ("screenshot",): screenshot_folder,
        ("screenshots",): screenshot_folder,
        ("screen",): screenshot_folder,
        ("screens",): screenshot_folder,
        ("cartella", "screenshot"): screenshot_folder,
        ("cartella", "screenshots"): screenshot_folder,
        ("cartella", "screen"): screenshot_folder,
    }
    config_path = ROOT / "Azioni" / "cartelle.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for alias, folder_path in config.get("cartelle", {}).items():
            alias_tokens = tuple(re.findall(r"[a-zà-öø-ÿ0-9]+", alias.casefold()))
            if alias_tokens and isinstance(folder_path, str):
                targets[alias_tokens] = folder_path
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Configurazione cartelle non leggibile: {exc}", file=sys.stderr)
    return targets


def launch_app(app_name: str) -> tuple[bool, str]:
    if activate_open_app(app_name):
        return True, f"{app_name.title()} era già aperto; l'ho portato in primo piano."
    app_id = APP_IDS[app_name]
    try:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], close_fds=True)
        return True, f"{app_name.title()} avviato."
    except OSError as exc:
        return False, f"Non sono riuscito ad avviare {app_name.title()}: {exc}."


def open_folder(target: str, display_name: str) -> tuple[bool, str]:
    if not target.startswith("shell:") and not os.path.isdir(os.path.expandvars(os.path.expanduser(target))):
        return False, f"Cartella non trovata: {target}."
    try:
        folder = os.path.expandvars(os.path.expanduser(target))
        subprocess.Popen(["explorer.exe", folder], close_fds=True)
        return True, f"Cartella {display_name} aperta."
    except OSError as exc:
        return False, f"Non sono riuscito ad aprire {display_name}: {exc}."


def tap_windows_key(key_code: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(key_code, 0, 0, 0)
    user32.keybd_event(key_code, 0, KEYEVENTF_KEYUP, 0)


def tap_windows_shortcut(*key_codes: int) -> None:
    """Invia una scorciatoia premendo i tasti insieme e rilasciandoli al contrario."""
    user32 = ctypes.windll.user32
    for key_code in key_codes:
        user32.keybd_event(key_code, 0, 0, 0)
    for key_code in reversed(key_codes):
        user32.keybd_event(key_code, 0, KEYEVENTF_KEYUP, 0)


def parse_timer_seconds(text: str) -> int | None:
    number_pattern = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
    match = re.search(
        rf"\b(?P<value>\d+|{number_pattern})\b\s*(?P<unit>second[io]|sec|minut[io]|min|or[ae]|h)?\b",
        text.casefold(),
    )
    if not match:
        return None
    value_token = match.group("value")
    value = int(value_token) if value_token.isdigit() else NUMBER_WORDS[value_token]
    unit = match.group("unit") or "minuti"
    if unit.startswith("sec"):
        multiplier = 1
    elif unit in ("ora", "ore", "h"):
        multiplier = 3600
    else:
        multiplier = 60
    total = value * multiplier
    return total if 0 < total <= 24 * 3600 else None


def is_direct_timer_command(text: str) -> bool:
    """Accept an explicit timer request even if Vosk missed the wake phrase."""
    words = set(re.findall(r"[a-zà-öø-ÿ]+", text.casefold()))
    return bool(words & {"timer", "temporizzatore"}) and parse_timer_seconds(text) is not None


def is_stop_command(text: str) -> bool:
    return tuple(re.findall(r"[a-zà-öø-ÿ]+", text.casefold())) == ("niente",)


def is_alarm_stop_command(text: str) -> bool:
    words = set(re.findall(r"[a-zà-öø-ÿ]+", text.casefold()))
    return bool(words & {"stop", "zitto", "zitta"}) or (
        bool(words & {"timer", "temporizzatore"})
        and bool(words & {"interrompi", "annulla", "ferma", "cancella"})
    )


def write_timer_control(action: str, timer_id: str | None = None) -> bool:
    if timer_id and not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", timer_id):
        return False
    file_name = f"onyx-timer-control-{timer_id}.txt" if timer_id else "onyx-timer-control.txt"
    control_path = ROOT / "logs" / file_name
    try:
        control_path.parent.mkdir(parents=True, exist_ok=True)
        control_path.write_text(action, encoding="utf-8")
        return True
    except OSError as exc:
        print(f"Impossibile controllare il timer: {exc}", file=sys.stderr, flush=True)
        return False


def set_timer_phase(timer_state: dict[str, str] | None, timer_id: str, phase: str) -> None:
    if timer_state is None:
        return
    timer_state[f"timer:{timer_id}"] = phase
    if timer_state.get("id") == timer_id:
        timer_state["phase"] = phase


def select_recent_active_timer(timer_state: dict[str, str]) -> None:
    active = [(key[6:], phase) for key, phase in timer_state.items() if key.startswith("timer:") and phase != "idle"]
    if active:
        timer_id, phase = active[-1]
        timer_state["id"] = timer_id
        timer_state["phase"] = phase
    else:
        timer_state["id"] = ""
        timer_state["phase"] = "idle"


def play_timer_alarm(stop_event: threading.Event, control_path: Path) -> bool:
    """Play the supplied MP3 until it ends or the user interrupts the alarm."""
    alarm = Path(__file__).resolve().parent.parent / "Suoni" / "allarme timer.mp3"
    if not alarm.is_file():
        print(f"Suono allarme non trovato: {alarm}", file=sys.stderr, flush=True)
        return False
    winmm = ctypes.WinDLL("winmm")
    send = winmm.mciSendStringW
    send.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
    send.restype = ctypes.c_uint
    alias = f"onyx_timer_{control_path.stem[-18:]}"
    command = ctypes.create_unicode_buffer(256)
    result = send(f'open "{alarm}" type mpegvideo alias {alias}', command, len(command), None)
    if result:
        print(f"Impossibile aprire l'allarme MP3 (MCI {result}).", file=sys.stderr, flush=True)
        return False
    try:
        if stop_event.is_set():
            return False
        result = send(f"play {alias}", command, len(command), None)
        if result:
            print(f"Impossibile avviare l'allarme MP3 (MCI {result}).", file=sys.stderr, flush=True)
            return False
        while not stop_event.is_set():
            try:
                action = control_path.read_text(encoding="utf-8").strip()
            except OSError:
                action = ""
            if action == "stop-alarm":
                stop_event.set()
                try:
                    control_path.unlink(missing_ok=True)
                except OSError:
                    pass
                break

            mode = ctypes.create_unicode_buffer(32)
            status = send(f"status {alias} mode", mode, len(mode), None)
            if status or mode.value.casefold() != "playing":
                break
            stop_event.wait(0.08)
    finally:
        send(f"stop {alias}", command, len(command), None)
        send(f"close {alias}", command, len(command), None)
    return not stop_event.is_set()


def execute_command(
    text: str,
    timers: list[threading.Timer],
    folder_targets: dict[tuple[str, ...], str],
    app_catalog: list[tuple[str, str]] | None = None,
    ui_events: queue.Queue[tuple[str, str | None]] | None = None,
    alarm_events: list[threading.Event] | None = None,
    timer_state: dict[str, str] | None = None,
    timer_id: str | None = None,
) -> tuple[bool, str]:
    normalized = text.casefold()
    tokens = re.findall(r"[a-zà-öø-ÿ]+", normalized)
    words = set(tokens)
    volume_up_words = {"alza", "alzare", "aumenta", "aumentare", "incrementa", "incrementare", "su", "più", "piu"}
    volume_down_words = {
        "abbassa", "abbasso", "abbassare", "bassa", "basso", "riduci", "riduce",
        "ridurre", "diminuisci", "diminuisce", "giù", "giu", "meno",
    }
    # Vosk in questa installazione ha trascritto “abbassa il volume” come
    # “abbassa la velocità”; conserva il comando quando la direzione è chiara.
    if words & {"velocità", "velocita"} and words & volume_down_words:
        words.add("volume")

    chat_mention = bool(words & {"chat", "chatgpt", "gpt", "gpd"})
    chat_open_request = chat_mention and (
        bool(words & LAUNCH_VERBS)
        or len(tokens) == 1
        or bool(words & {"mostra", "mostrami", "visualizza", "vedi"})
    )
    if chat_open_request:
        return open_chatgpt(app_catalog)

    # Il cronometro vive nell'interfaccia del notch. Gestire prima questi
    # comandi evita che "pausa cronometro" venga confuso con il timer.
    if "cronometro" in words or "cronometri" in words:
        if ui_events is None:
            return False, "Interfaccia del cronometro non disponibile."
        if words & {"giro", "giri", "lap", "parziale"}:
            ui_events.put(("stopwatch-lap", None))
            return True, "Giro registrato."
        if words & {"azzera", "azzerare", "reset", "ripristina"}:
            ui_events.put(("stopwatch-reset", None))
            return True, "Cronometro azzerato."
        if words & {"pausa", "pausare", "ferma", "fermare", "stop"}:
            ui_events.put(("stopwatch-pause", None))
            return True, "Cronometro in pausa."
        if words & {"riprendi", "riprendere", "continua", "continuare", "avvia", "avviare", "inizia", "iniziare", "start"}:
            ui_events.put(("stopwatch-resume", None))
            return True, "Cronometro avviato."
        ui_events.put(("stopwatch-open", None))
        return True, "Cronometro aperto."

    volume_direction = bool(words & (volume_up_words | volume_down_words))
    volume_subject = bool(words & {"volume", "volumi", "audio", "suono"})
    misheard_volume = bool(words & {"velocità", "velocita"}) and bool(words & volume_down_words)
    if volume_direction and (volume_subject or misheard_volume):
        steps = parse_spoken_number(tokens)
        steps = max(1, min(steps, 50)) if steps is not None else VOLUME_STEPS
        key = VK_VOLUME_UP if words & volume_up_words else VK_VOLUME_DOWN
        for _ in range(steps):
            tap_windows_key(key)
            time.sleep(0.05)
        return True, "Volume aumentato." if key == VK_VOLUME_UP else "Volume ridotto."

    timer_reference = bool(words & {"timer", "temporizzatore"})
    current_timer_id = timer_state.get("id", "") if timer_state is not None else ""
    timer_phase = timer_state.get(f"timer:{current_timer_id}", timer_state.get("phase", "idle")) if timer_state is not None else "idle"
    media_target = bool(words & {"musica", "spotify", "video", "riproduzione", "app", "applicazione"})
    control_action = timer_control_intent(text)

    if control_action and (timer_reference or (timer_phase != "idle" and not media_target)):
        if timer_phase == "idle":
            return False, "Non c’è un timer attivo."
        if control_action == "pause":
            if timer_phase == "alarm":
                return False, "Il timer è terminato; dì ‘stop’ o ‘zitto’ per fermare l’allarme."
            if timer_phase == "paused":
                if ui_events is not None:
                    ui_events.put(("timer-pause", timer_state.get("id")))
                return True, "Timer già in pausa."
            if not write_timer_control("pause", current_timer_id or None):
                return False, "Non sono riuscito a mettere in pausa il timer."
            set_timer_phase(timer_state, current_timer_id, "paused")
            if ui_events is not None:
                ui_events.put(("timer-pause", timer_state.get("id")))
            return True, "Timer in pausa."
        if control_action == "resume":
            if timer_phase == "alarm":
                return False, "Il timer è già terminato."
            if timer_phase == "running":
                if ui_events is not None:
                    ui_events.put(("timer-resume", timer_state.get("id")))
                return True, "Timer già attivo."
            if not write_timer_control("resume", current_timer_id or None):
                return False, "Non sono riuscito a riprendere il timer."
            set_timer_phase(timer_state, current_timer_id, "running")
            if ui_events is not None:
                ui_events.put(("timer-resume", timer_state.get("id")))
            return True, "Timer ripreso."

        if timer_phase == "alarm":
            if alarm_events is not None:
                for alarm_event in list(alarm_events):
                    alarm_event.set()
                alarm_events.clear()
            if timer_state is not None:
                for key in list(timer_state):
                    if key.startswith("timer:") and timer_state[key] == "alarm":
                        del timer_state[key]
                select_recent_active_timer(timer_state)
            write_timer_control("stop-alarm")
            if ui_events is not None:
                ui_events.put(("alarm-stop", None))
            return True, "Allarme timer interrotto."
        if not write_timer_control("cancel", current_timer_id or None):
            return False, "Non sono riuscito a interrompere il timer."
        if timer_state is not None:
            timer_state.pop(f"timer:{current_timer_id}", None)
            select_recent_active_timer(timer_state)
        if ui_events is not None:
            ui_events.put(("timer-cancel", current_timer_id or None))
        return True, "Timer interrotto."

    action_words = {
        "alza", "aumenta", "incrementa", "su", "abbassa", "riduci", "riduce",
        "diminuisci", "giu", "giù", "muto", "silenzia", "mute", "pausa",
        "riprendi", "riproduci", "play", "stop",
    }
    if "desktop" in words and words & {"mostra", "visualizza", "vai"}:
        ctypes.windll.user32.keybd_event(0x5B, 0, 0, 0)
        ctypes.windll.user32.keybd_event(ord("D"), 0, 0, 0)
        ctypes.windll.user32.keybd_event(ord("D"), 0, KEYEVENTF_KEYUP, 0)
        ctypes.windll.user32.keybd_event(0x5B, 0, KEYEVENTF_KEYUP, 0)
        return True, "Desktop mostrato."
    show_all_verbs = {"mostra", "mostrami", "mostrare", "visualizza", "visualizzare", "vedi", "apri", "elenca", "elencami"}
    asks_for_all = bool(words & {"tutto", "tutti", "tutta", "tutte"})
    asks_for_activities = bool(words & {"attivita", "attività"})
    if words & show_all_verbs and (asks_for_all or asks_for_activities):
        tap_windows_shortcut(VK_LWIN, VK_TAB)
        return True, "Vista attività di Windows aperta."
    if "fullscreen" in words or {"full", "screen"}.issubset(words) or {"schermo", "intero"}.issubset(words):
        tap_windows_key(VK_F11)
        return True, "Comando schermo intero inviato alla finestra attiva."
    if words & {"pausa", "pause", "pausare", "riprendi", "riproduci", "play", "stop"}:
        tap_windows_key(VK_MEDIA_PLAY_PAUSE)
        return True, "Comando di pausa o riproduzione inviato al lettore multimediale."
    if "cerca" in words and "chrome" in words:
        start = tokens.index("cerca") + 1
        if start < len(tokens) and tokens[start] in {"su", "in", "con"}:
            start += 1
        if start < len(tokens) and tokens[start] == "chrome":
            start += 1
        return chrome_search(" ".join(tokens[start:]))
    if "sito" in words and words & {"vai", "apri", "apre", "aprire", "avvia"}:
        start = tokens.index("sito") + 1
        while start < len(tokens) and tokens[start] in {"il", "lo", "la", "al", "al", "per", "web"}:
            start += 1
        return open_website(" ".join(tokens[start:]))
    screenshot_words = {"screenshot", "schermata", "cattura", "screen", "screens"}
    screenshot_action_verbs = {"fai", "fare", "scatta", "scattare", "cattura", "catturare", "salva"}
    explicit_screenshot_action = bool(words & screenshot_words) and (
        bool(words & screenshot_action_verbs) or ("fammi" in words and "vedere" not in words)
    )
    folder_match = next(
        ((alias, target) for alias, target in folder_targets.items() if phrase_in_tokens(tokens, alias)),
        None,
    )
    if folder_match:
        alias, folder_target = folder_match
        bare_screenshot_command = len(tokens) == 1 and tokens[0] in {"screenshot", "schermata", "cattura", "screen", "screens"}
        asks_for_folder = bool(words & FOLDER_OPEN_VERBS) or bool(words & FOLDER_NOUNS) or tuple(tokens) == alias or {"fammi", "vedere"}.issubset(words)
        if asks_for_folder and not bare_screenshot_command and not explicit_screenshot_action:
            if words & CLOSE_VERBS:
                return False, "Per ora Onyx può aprire cartelle, ma non chiuderle."
            display_alias = alias[1:] if alias and alias[0] in FOLDER_NOUNS else alias
            display_name = " ".join(display_alias).title()
            if folder_target == "shell:Downloads":
                display_name = "Download"
            elif folder_target == "shell:Personal":
                display_name = "Documenti"
            elif folder_target == str(ROOT / "Screenshot"):
                display_name = "Screenshot"
            return open_folder(folder_target, display_name)
    if words & screenshot_words and (
        words & {"copia", "copiami", "copiare", "copialo"}
        or (words & {"appunti", "clipboard"} and words & {"ultimo", "ultima", "ultimi", "ultime"})
    ):
        return copy_latest_screenshot()
    bare_screenshot_request = len(tokens) == 1 and tokens[0] in screenshot_words
    if explicit_screenshot_action or bare_screenshot_request:
        window_only = bool(words & {"finestra", "window"})
        return take_screenshot(window_only=window_only)
    if words & {"sospensione", "sospendi", "sospendere", "sospeso", "dormi"} or ("sospensione" in normalized):
        return suspend_computer()

    on_words = {
        "accendi", "accendere", "accendilo", "accenderlo", "acendi", "attiva", "attivare",
        "attivalo", "abilita", "abilitare", "riattiva", "riattivare", "on", "acceso", "accesa",
    }
    off_words = {
        "spegni", "spegne", "spegno", "spegnere", "spenge", "spengere", "spegnerlo", "spegnilo",
        "spegnerla", "disattiva", "disattivare", "disattivalo", "disabilita", "disabilitare",
        "off", "spento", "spenta", "sveglia", "spend",
    }
    radio_on = bool(words & on_words) or "incendio" in words
    radio_off = bool(words & off_words)
    show_words = {"mostra", "mostrami", "vedi", "visualizza", "elenca", "apri"}

    # Correzioni contestuali alle frasi viste nei log Vosk: “spend breve tour”
    # è una resa fonetica ricorrente di “spegni Bluetooth”.
    if {"spend", "breve", "tour"}.issubset(words):
        words.add("bluetooth")
        radio_off = True

    airplane_words = {"aereo", "aeroplano", "volo", "airplane"}
    airplane_requested = (
        bool(words & airplane_words)
        and bool(words & {"modalità", "modalita", "aereo", "aeroplano", "volo", "airplane"})
    ) or ("beirut" in words and (radio_on or radio_off))
    if airplane_requested:
        mode = "on" if radio_on else "off" if radio_off else "toggle"
        return set_airplane_mode(mode)

    is_wifi = bool(words & {"wifi", "wireless", "reti", "rete"}) or "wi fi" in normalized or {"wi", "fi"}.issubset(words)
    if is_wifi:
        if words & (show_words | {"cerca"}) or words & {"reti", "rete"} and not (radio_on or radio_off):
            return open_settings("ms-settings:network-wifi", "Ho aperto le reti Wi-Fi disponibili.")
        if radio_off:
            return set_wifi_enabled(False)
        if radio_on:
            return set_wifi_enabled(True)
    is_bluetooth = bool(words & {"bluetooth", "bluetooths"}) or {"blue", "tooth"}.issubset(words)
    asks_for_devices = bool(words & {"dispositivi", "dispositivo", "device", "devices"}) and bool(words & show_words)
    if asks_for_devices and not is_wifi:
        is_bluetooth = True
    if is_bluetooth:
        if asks_for_devices or words & (show_words | {"dispositivi", "dispositivo", "device", "devices"}):
            return open_settings("ms-settings:bluetooth", "Ho aperto i dispositivi Bluetooth.")
        if radio_off:
            return set_bluetooth_enabled(False)
        if radio_on:
            return set_bluetooth_enabled(True)
    brightness_subject = {"luminosità", "luminosita", "luminoso", "schermo", "monitor", "display"}
    brighter_words = {"alza", "alzare", "aumenta", "aumentare", "incrementa", "incrementare", "illumina", "su", "più", "piu"}
    dimmer_words = volume_down_words | {"scurisci", "scurire"}
    if words & brightness_subject and words & (brighter_words | dimmer_words):
        direction = "aumenta" if words & brighter_words else "diminuisci"
        amount = parse_spoken_number(tokens) or 10
        amount = max(1, min(amount, 100))
        delta = amount if direction == "aumenta" else -amount
        script = "$m=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1; $c=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1; if(-not $m -or -not $c){exit 2}; $v=[Math]::Max(0,[Math]::Min(100,$c.CurrentBrightness+" + str(delta) + ")); $m | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{Timeout=1;Brightness=$v} | Out-Null"
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], check=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True, f"Luminosità {direction} di {amount} punti."
        except (OSError, subprocess.SubprocessError):
            return False, "Non riesco a modificare la luminosità tramite il controllo schermo Windows."
    window_intent = bool(words & ({"ingrandisci", "massimizza", "chiudi", "davanti", "mostra", "porta", "metti", "nome", "attiva"} | MINIMIZE_VERBS | ICON_WORDS))
    window_intent = window_intent and not bool(words & {"volume", "luminosità", "luminosita", "schermo"})
    if window_intent:
        if words & {"nome"}:
            return operate_window("name")
        if words & {"ingrandisci", "massimizza"}:
            action = "maximize"
        elif words & (MINIMIZE_VERBS | ICON_WORDS):
            action = "minimize"
        elif words & CLOSE_VERBS:
            action = "close"
        else:
            action = "foreground"
        target_tokens = [t for t in tokens if t not in WINDOW_VERBS and t not in {"a", "al", "alla", "alle", "allo", "ai", "agli", "l", "la", "il", "le", "li", "lo", "un", "una", "questa", "questo", "di", "del", "della", "delle", "dei", "degli", "finestra", "app", "applicazione", "in", "primo", "piano"}]
        # Vosk a volte trascrive “icona” come “coda”; in una richiesta di riduzione
        # senza altro nome si riferisce comunque alla finestra in primo piano.
        if action == "minimize" and target_tokens == ["coda"]:
            target_tokens.clear()
        target = " ".join(target_tokens)
        # Il solo verbo applica sempre l'azione alla finestra attualmente attiva.
        result = operate_window(action, target)
        if not result[0] and action == "close" and target:
            matched_app = match_start_app(target, app_catalog or [])
            if isinstance(matched_app, tuple):
                return close_app_id(matched_app[1], matched_app[0])
        return result
    if words & {"successivo", "precedente", "prossimo"} and words & {"brano", "canzone", "traccia", "musica"}:
        tap_windows_key(VK_MEDIA_PREV_TRACK if "precedente" in words else VK_MEDIA_NEXT_TRACK)
        return True, "Brano precedente." if "precedente" in words else "Brano successivo."
    if "blocca" in words and words & {"pc", "computer", "schermo"}:
        ctypes.windll.user32.LockWorkStation()
        return True, "Blocco il computer."
    if "grazie" in words and not (words & action_words):
        return True, "Prego."

    if words & (LAUNCH_VERBS | CLOSE_VERBS):
        closing = bool(words & CLOSE_VERBS)
        # Include pronunce e abbreviazioni comuni che Vosk produce per Chrome.
        if any(phrase_in_tokens(tokens, alias) for alias in (("chrome",), ("google", "chrome"), ("crome",), ("crom" ,))):
            if closing:
                return close_process_names(("chrome",), "Google Chrome")
            chrome = next(((n, i) for n, i in (app_catalog or []) if i.casefold() == "chrome" or normalize_app_name(n) == "google chrome"), None)
            if chrome:
                return start_app_id(chrome[1], chrome[0])
        for app_name, aliases in APP_ALIASES.items():
            if any(phrase_in_tokens(tokens, alias) for alias in aliases):
                if closing:
                    return close_app_id(APP_IDS[app_name], app_name.title())
                return launch_app(app_name)
        verb_tokens = CLOSE_VERBS if closing else LAUNCH_VERBS
        spoken_name = " ".join(token for token in tokens if token not in verb_tokens)
        match = match_start_app(spoken_name, app_catalog or [])
        if isinstance(match, str):
            return False, match
        if match:
            name, app_id = match
            if closing:
                return close_app_id(app_id, name)
            return start_app_id(app_id, name)
        return False, "Non ho trovato un'app corrispondente nel menu Start."

    has_duration_unit = re.search(
        r"\b(?:second[io]|sec|minut[io]|min|or[ae]|h)\b", normalized
    ) is not None
    if "timer" in words or "temporizzatore" in words or has_duration_unit:
        duration = parse_timer_seconds(normalized)
        if duration is None:
            return False, "Non ho capito la durata. Riprova, per esempio: ‘timer cinque minuti’."

        timer_id = timer_id or uuid.uuid4().hex[:12]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", timer_id):
            return False, "Identificativo timer non valido."
        control_path = ROOT / "logs" / f"onyx-timer-control-{timer_id}.txt"
        if ui_events is not None:
            ui_events.put(("timer", json.dumps({"id": timer_id, "durationSeconds": duration})))
        alarm_stop = threading.Event()

        def timer_finished() -> None:
            print("\nTimer terminato.", flush=True)
            set_timer_phase(timer_state, timer_id, "alarm")
            if alarm_events is not None:
                alarm_events.append(alarm_stop)
            if ui_events is not None:
                ui_events.put(("timer-end", timer_id))
            try:
                while not alarm_stop.is_set():
                    if not play_timer_alarm(alarm_stop, control_path):
                        break
                    if alarm_stop.wait(0.35):
                        break
            finally:
                if alarm_stop.is_set():
                    if timer_state is not None:
                        timer_state.pop(f"timer:{timer_id}", None)
                        if timer_state.get("id") == timer_id:
                            select_recent_active_timer(timer_state)
                    if ui_events is not None:
                        ui_events.put(("alarm-stop", timer_id))
                if alarm_stop.is_set() and alarm_events is not None:
                    try:
                        alarm_events.remove(alarm_stop)
                    except ValueError:
                        pass

        def countdown() -> None:
            remaining = duration
            while remaining > 0:
                try:
                    action = control_path.read_text(encoding="utf-8").strip()
                except OSError:
                    action = ""
                if action in {"cancel", "stop-alarm"}:
                    control_path.unlink(missing_ok=True)
                    if timer_state is not None:
                        timer_state.pop(f"timer:{timer_id}", None)
                        if timer_state.get("id") == timer_id:
                            select_recent_active_timer(timer_state)
                    if ui_events is not None:
                        ui_events.put(("timer-cancel", timer_id))
                    return
                if action == "pause":
                    set_timer_phase(timer_state, timer_id, "paused")
                    time.sleep(0.15)
                    continue
                if action == "resume":
                    set_timer_phase(timer_state, timer_id, "running")
                    try:
                        control_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                time.sleep(1)
                remaining -= 1
            set_timer_phase(timer_state, timer_id, "alarm")
            timer_finished()

        timer = threading.Thread(target=countdown, daemon=True)
        timer.daemon = True
        if timer_state is not None:
            timer_state["id"] = timer_id
        set_timer_phase(timer_state, timer_id, "running")
        timer.start()
        timers.append(timer)
        minutes, seconds = divmod(duration, 60)
        if seconds:
            duration_text = f"{minutes} minuti e {seconds} secondi" if minutes else f"{seconds} secondi"
        else:
            duration_text = f"{minutes} minuti"
        return True, f"Timer avviato: {duration_text}."

    if words & {"volume", "volumi", "audio", "suono"}:
        steps = parse_spoken_number(tokens)
        steps = max(1, min(steps, 50)) if steps is not None else VOLUME_STEPS
        if words & volume_up_words:
            for _ in range(steps):
                tap_windows_key(VK_VOLUME_UP)
                time.sleep(0.05)
            return True, "Volume aumentato."
        if words & volume_down_words:
            for _ in range(steps):
                tap_windows_key(VK_VOLUME_DOWN)
                time.sleep(0.05)
            return True, "Volume ridotto."
        if words & {"muto", "silenzia", "mute"}:
            tap_windows_key(VK_VOLUME_MUTE)
            return True, "Audio attivato o silenziato."
        return False, "Comando volume non chiaro: dì alza, abbassa o silenzia il volume."


    # Se la frase è solo il nome di un'app, avviala o riporta davanti la sua finestra.
    if 1 <= len(tokens) <= 4:
        match = match_start_app(normalized, app_catalog or [])
        if isinstance(match, tuple):
            name, app_id = match
            return start_app_id(app_id, name)

    return False, "Non ho capito il comando. Riprova oppure dì ‘niente’ per uscire."


def run_listener(model_path: Path, ui_events: queue.Queue[tuple[str, str | None]]) -> None:
    SetLogLevel(-1)
    audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=128)
    dropped_audio_blocks = 0
    last_drop_warning = 0
    recognized_utterances = 0
    wake_activations = 0
    recognized_commands = 0
    command_mode = False
    last_partial = ""
    wake_cooldown_until = 0.0
    last_control_poll = 0.0
    error_cue_echo_guard_until = 0.0
    timers: list[threading.Timer] = []
    active_alarm_events: list[threading.Event] = []
    timer_state = {"phase": "idle"}
    timer_control_path = ROOT / "logs" / "onyx-timer-control.txt"
    timer_start_path = ROOT / "logs" / "onyx-timer-start.txt"
    folder_targets = load_folder_targets()
    app_catalog = start_menu_apps()
    print(f"Catalogo menu Start: {len(app_catalog)} applicazioni.", flush=True)

    def stop_active_alarms() -> bool:
        alarms = [event for event in active_alarm_events if not event.is_set()]
        if not alarms:
            return False
        for event in alarms:
            event.set()
        active_alarm_events[:] = [event for event in active_alarm_events if not event.is_set()]
        for key in list(timer_state):
            if key.startswith("timer:") and timer_state[key] == "alarm":
                del timer_state[key]
        select_recent_active_timer(timer_state)
        try:
            timer_control_path.unlink(missing_ok=True)
        except OSError:
            pass
        ui_events.put(("alarm-stop", None))
        print("Allarme timer interrotto.", flush=True)
        return True

    def process_alarm_control() -> None:
        if not any(not event.is_set() for event in active_alarm_events):
            return
        try:
            action = timer_control_path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if action == "stop-alarm":
            stop_active_alarms()

    def process_ui_timer_start() -> None:
        requests = sorted(ROOT.glob("logs/onyx-timer-start-*.txt"))
        # Read the legacy single-request file once for installations upgraded in place.
        if timer_start_path.is_file():
            requests.append(timer_start_path)
        for request_path in requests:
            try:
                raw_seconds = request_path.read_text(encoding="utf-8").strip()
                request_id = request_path.stem.removeprefix("onyx-timer-start-")
                request_path.unlink(missing_ok=True)
            except OSError:
                continue
            timer_id = request_id if request_id != "onyx-timer-start" else uuid.uuid4().hex[:12]
            try:
                requested_seconds = int(raw_seconds)
            except ValueError:
                continue
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", timer_id) or not 0 < requested_seconds <= 24 * 60 * 60:
                continue
            succeeded, response = execute_command(
                f"timer {requested_seconds} secondi", timers, folder_targets, app_catalog,
                ui_events, active_alarm_events, timer_state, timer_id,
            )
            print(response, flush=True)
            if not succeeded:
                ui_events.put(("error", response))

    def dispatch_command(text: str) -> bool:
        nonlocal recognized_commands, error_cue_echo_guard_until
        recognized_commands += 1
        print(f"Comando ascoltato: {text}", flush=True)
        ui_events.put(("processing", text))
        succeeded, response = execute_command(
            text, timers, folder_targets, app_catalog, ui_events, active_alarm_events, timer_state
        )
        print(f"{response}\n", flush=True)
        if succeeded:
            # Timer controls keep their own persistent notch instead of showing a toast.
            if not response.startswith(("Timer ", "Allarme timer")):
                ui_events.put(("success", response))
            return True
        ui_events.put(("error", f"Non ho capito: {text}"))
        error_cue_echo_guard_until = time.monotonic() + ERROR_CUE_ECHO_GUARD_SECONDS
        return False

    def on_audio(indata, frames, time_info, status) -> None:
        nonlocal dropped_audio_blocks
        if status:
            print(f"\nAudio: {status}", file=sys.stderr)
        try:
            audio_queue.put_nowait(bytes(indata))
        except queue.Full:
            try:
                audio_queue.get_nowait()
                dropped_audio_blocks += 1
                audio_queue.put_nowait(bytes(indata))
            except queue.Empty:
                pass
            except queue.Full:
                dropped_audio_blocks += 1

    try:
        print(f"Carico il modello Vosk: {model_path}")
        model = Model(str(model_path))
        recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        wake_model = WakeModel(wakeword_models=[str(WAKE_MODEL_PATH)], inference_framework="onnx")
        print("Onyx pronto e in ascolto. Pronuncia ‘Onyx’.\n", flush=True)

        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype="int16",
            channels=1,
            callback=on_audio,
        ):
            while True:
                audio = audio_queue.get()
                now = time.monotonic()
                if now - last_control_poll >= CONTROL_POLL_SECONDS:
                    last_control_poll = now
                    process_alarm_control()
                    process_ui_timer_start()
                if not command_mode and now >= wake_cooldown_until:
                    scores = wake_model.predict(np.frombuffer(audio, dtype=np.int16))
                    if scores and max(scores.values()) >= WAKE_THRESHOLD:
                        wake_model.reset()
                        wake_cooldown_until = now + WAKE_COOLDOWN_SECONDS
                        wake_activations += 1
                        command_mode = True
                        last_partial = ""
                        recognizer.Reset()
                        ui_events.put(("wake", None))
                        print("Onyx rilevato. Ascolto comando attivo; dì ‘niente’ per annullare.\n", flush=True)
                        continue
                complete_utterance = recognizer.AcceptWaveform(audio)
                if dropped_audio_blocks and (
                    last_drop_warning == 0 or dropped_audio_blocks - last_drop_warning >= 10
                ):
                    print(
                        f"Avviso: il modello è in ritardo; blocchi audio persi: {dropped_audio_blocks}.",
                        file=sys.stderr,
                        flush=True,
                    )
                    last_drop_warning = dropped_audio_blocks
                if command_mode and not complete_utterance:
                    partial_text = json.loads(recognizer.PartialResult()).get("partial", "").strip()
                    if (
                        time.monotonic() < error_cue_echo_guard_until
                        and is_error_cue_echo(partial_text)
                    ):
                        continue
                    if partial_text and partial_text != last_partial:
                        last_partial = partial_text
                        ui_events.put(("partial", partial_text))
                    continue
                if complete_utterance:
                    text = json.loads(recognizer.Result()).get("text", "").strip()
                    last_partial = ""
                    if not text:
                        if command_mode:
                            ui_events.put(("error", "Non ho capito, riprova"))
                            error_cue_echo_guard_until = (
                                time.monotonic() + ERROR_CUE_ECHO_GUARD_SECONDS
                            )
                        continue
                    if (
                        command_mode
                        and time.monotonic() < error_cue_echo_guard_until
                        and is_error_cue_echo(text)
                    ):
                        print("Ignoro l'eco audio di ‘Non ho capito’.", flush=True)
                        last_partial = ""
                        continue
                    recognized_utterances += 1
                    stamp = datetime.now().astimezone().strftime("%H:%M:%S")
                    print(f"[{stamp}] Ho sentito: {text}", flush=True)
                    wake_tail = wake_command_tail(text)
                    if wake_tail is not None:
                        if not wake_tail:
                            continue
                        text = wake_tail
                    if any(not event.is_set() for event in active_alarm_events):
                        if is_alarm_stop_command(text):
                            stop_active_alarms()
                            command_mode = False
                            continue
                        if command_mode:
                            if is_stop_command(text):
                                command_mode = False
                                ui_events.put(("hide", None))
                                continue
                            if dispatch_command(text):
                                command_mode = False
                        else:
                            print("Allarme attivo: dì ‘Onyx’ per un comando, oppure ‘stop’/‘zitto’ per interromperlo.", flush=True)
                        continue
                    if command_mode:
                        if is_stop_command(text):
                            command_mode = False
                            ui_events.put(("hide", None))
                            print("Sessione comandi chiusa; torno ad aspettare ‘Onyx’.\n", flush=True)
                            continue
                        if dispatch_command(text):
                            command_mode = False
                    elif timer_state["phase"] != "idle" and is_direct_timer_control(text):
                        dispatch_command(text)
                    elif is_direct_timer_command(text):
                        print(f"Comando timer diretto riconosciuto: {text}", flush=True)
                        dispatch_command(text)
    except sd.PortAudioError as exc:
        print(f"Errore del microfono: {exc}", file=sys.stderr)
        print("Controlla che Windows consenta a Python di usare il microfono.", file=sys.stderr)
    except Exception as exc:
        print(f"Errore: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rileva la chiamata di Onyx con Vosk.")
    parser.add_argument(
        "--modello",
        type=Path,
        default=MODEL_PATH,
        help="cartella del modello Vosk completo",
    )
    args = parser.parse_args()
    model_path = args.modello
    if not model_path.is_absolute():
        model_path = ROOT / model_path

    def is_model_directory(path: Path) -> bool:
        return all((path / folder).is_dir() for folder in ("am", "conf", "graph"))

    if model_path.is_dir() and not is_model_directory(model_path):
        nested_models = [
            child
            for child in model_path.iterdir()
            if child.is_dir() and is_model_directory(child)
        ]
        if len(nested_models) == 1:
            model_path = nested_models[0]
            print(f"Modello trovato nella cartella interna: {model_path}")

    if not is_model_directory(model_path):
        print(f"Modello Vosk non trovato o incompleto: {model_path}", file=sys.stderr)
        if not WAKE_MODEL_PATH.is_file():
            print(f"Modello wake word non trovato: {WAKE_MODEL_PATH}", file=sys.stderr)
        return 1
        print("La cartella deve contenere le sottocartelle am, conf e graph.", file=sys.stderr)
        return 1

    ui_events: queue.Queue[tuple[str, str | None]] = queue.Queue()
    orb = OverlayClient(ui_events)
    listener = threading.Thread(
        target=run_listener,
        args=(model_path, ui_events),
        name="onyx-listener",
        daemon=True,
    )
    listener.start()
    orb.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
