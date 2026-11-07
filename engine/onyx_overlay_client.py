"""Bridge locale tra il motore vocale Python e l'interfaccia Bloom di Onyx."""
from __future__ import annotations

import base64
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class OverlayClient:
    def __init__(self, events: queue.Queue[tuple[str, str | None]]) -> None:
        self.events = events
        self.process: subprocess.Popen[str] | None = None
        self.sequence = 0
        self.state_path = ROOT / "logs" / "onyx-ui-state.json"
        self.control_path = ROOT / "logs" / "onyx-system-control.json"
        self.control_worker_active = False

    @staticmethod
    def _run_helper(script_name: str, *arguments: str) -> dict[str, object]:
        helper = ROOT / "PowerShell" / script_name
        powershell = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
        )
        if not helper.is_file():
            return {"Ok": False, "Messaggio": f"File di supporto mancante: {script_name}."}
        try:
            result = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-STA",
                 "-ExecutionPolicy", "Bypass", "-File", str(helper), *arguments],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"Ok": False, "Messaggio": f"Non riesco a eseguire l'azione di Windows: {exc}."}
        for line in reversed(result.stdout.splitlines()):
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(response, dict) and "Ok" in response:
                return response
        detail = (result.stderr or result.stdout).strip().splitlines()
        return {"Ok": False, "Messaggio": detail[-1] if detail else f"Windows ha restituito il codice {result.returncode}."}

    def _read_system_status(self) -> tuple[bool, str, dict[str, object]]:
        radios = self._run_helper("Gestisci-Radio.ps1", "status")
        screen = self._run_helper("Gestisci-Schermo.ps1", "status")
        state = {
            "wifi": radios.get("WiFi"),
            "bluetooth": radios.get("Bluetooth"),
            "airplane": radios.get("Airplane"),
            "brightness": screen.get("Brightness"),
        }
        ok = bool(radios.get("Ok")) and bool(screen.get("Ok"))
        message = "Stato dei controlli aggiornato." if ok else str(
            radios.get("Messaggio") if not radios.get("Ok") else screen.get("Messaggio")
        )
        return ok, message, state

    def _apply_system_action(self, request: dict[str, object]) -> dict[str, object]:
        action = str(request.get("action", ""))
        if action == "status":
            ok, message, state = self._read_system_status()
            return {"ok": ok, "message": message, "state": state}

        if action == "brightness-set":
            value = max(0, min(100, int(request.get("value", 50))))
            response = self._run_helper("Gestisci-Schermo.ps1", "set", str(value))
        elif action in {"volume-up", "volume-down"}:
            key = 0xAF if action == "volume-up" else 0xAE
            try:
                ctypes.windll.user32.keybd_event(key, 0, 0, 0)
                ctypes.windll.user32.keybd_event(key, 0, 0x0002, 0)
                response = {"Ok": True, "Messaggio": "Volume aumentato." if action == "volume-up" else "Volume ridotto."}
            except (AttributeError, OSError) as exc:
                response = {"Ok": False, "Messaggio": f"Non riesco a modificare il volume: {exc}."}
        elif action in {"wifi-toggle", "bluetooth-toggle"}:
            radios = self._run_helper("Gestisci-Radio.ps1", "status")
            key = "WiFi" if action == "wifi-toggle" else "Bluetooth"
            if not radios.get("Ok") or not isinstance(radios.get(key), bool):
                response = {"Ok": False, "Messaggio": str(radios.get("Messaggio", "Stato radio non disponibile."))}
            else:
                radio_name = "wifi" if action == "wifi-toggle" else "bluetooth"
                target = "off" if radios[key] else "on"
                response = self._run_helper("Gestisci-Radio.ps1", f"{radio_name}-{target}")
        elif action == "airplane-toggle":
            response = self._run_helper("Gestisci-Radio.ps1", "airplane-toggle")
        else:
            response = {"Ok": False, "Messaggio": "Azione del pannello non riconosciuta."}

        ok = bool(response.get("Ok"))
        message = str(response.get("Messaggio", "Modifica non riuscita."))
        _, _, state = self._read_system_status()
        return {"ok": ok, "message": message, "state": state}

    def _process_control_file(self, claimed_path: Path) -> None:
        try:
            request = json.loads(claimed_path.read_text(encoding="utf-8"))
            result = self._apply_system_action(request if isinstance(request, dict) else {})
        except (OSError, ValueError, TypeError) as exc:
            result = {"ok": False, "message": f"Comando del pannello non leggibile: {exc}.", "state": {}}
        finally:
            claimed_path.unlink(missing_ok=True)
            self.control_worker_active = False
        self.events.put(("system-result", json.dumps(result, ensure_ascii=False)))

    def _start_control_worker(self) -> None:
        if self.control_worker_active or not self.control_path.is_file():
            return
        claimed_path = self.control_path.with_name(f"onyx-system-control.{os.getpid()}.working")
        try:
            os.replace(self.control_path, claimed_path)
        except OSError:
            return
        self.control_worker_active = True
        threading.Thread(target=self._process_control_file, args=(claimed_path,), daemon=True).start()

    def publish_snapshot(self, state: str, message: str | None) -> None:
        """Persist the latest UI event so Bloom can recover it if IPC misses it."""
        snapshot = {
            "sequence": self.sequence,
            "state": state,
            "message": message or "",
        }
        temporary_path = self.state_path.with_name(
            f"{self.state_path.name}.{os.getpid()}.tmp"
        )
        try:
            temporary_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary_path, self.state_path)
        except OSError as exc:
            print(f"Impossibile salvare lo stato UI di Onyx: {exc}", file=sys.stderr, flush=True)

    def run(self) -> None:
        interface = ROOT / "UI" / "BloomSource" / "src-tauri" / "target" / "onyx-ui-build-v5" / "release" / "onyx-ui.exe"
        errors = ROOT / "logs" / "onyx-overlay-error.log"
        errors.parent.mkdir(parents=True, exist_ok=True)
        if not interface.is_file():
            print(
                f"Interfaccia Bloom di Onyx non compilata: {interface}. "
                "Esegui Compila-Interfaccia-Onyx.ps1.",
                file=sys.stderr,
                flush=True,
            )
            return
        self.publish_snapshot("hide", None)
        try:
            error_stream = errors.open("w", encoding="utf-8")
            self.process = subprocess.Popen(
                [str(interface)],
                cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=error_stream, text=True, encoding="utf-8", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            print(f"Impossibile avviare l'interfaccia Bloom: {exc}", file=sys.stderr, flush=True)
            return

        try:
            while self.process.poll() is None:
                self._start_control_worker()
                try:
                    state, message = self.events.get(timeout=0.08)
                except queue.Empty:
                    continue
                self.sequence += 1
                self.publish_snapshot(state, message)
                payload = base64.b64encode((message or "").encode("utf-8")).decode("ascii")
                try:
                    assert self.process.stdin is not None
                    self.process.stdin.write(f"{self.sequence}|{state}|{payload}\n")
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    break
        finally:
            if self.process.poll() is None:
                try:
                    assert self.process.stdin is not None
                    self.process.stdin.write("QUIT\n")
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
            if self.process.stdin:
                self.process.stdin.close()
