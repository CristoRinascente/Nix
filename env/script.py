import sys
import importlib.util
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENGINE_DIR = BASE_DIR / "engine"
ACTION_FILE = ENGINE_DIR / "action.py"

if not ACTION_FILE.is_file():
    raise SystemExit(f"File non trovato: {ACTION_FILE}")

sys.path.insert(0, str(ENGINE_DIR))

spec = importlib.util.spec_from_file_location("action", ACTION_FILE)
action = importlib.util.module_from_spec(spec)
spec.loader.exec_module(action)

if __name__ == "__main__":
    raise SystemExit(action.main())