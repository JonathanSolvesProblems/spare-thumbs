import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

# Private data (raw chats, OAuth tokens, voice examples, state) lives outside the repo and outside OneDrive.
DATA_DIR = Path(os.environ.get("SPARE_THUMBS_DATA", Path.home() / "hf26-private-data"))

RESULTS = Path(__file__).resolve().parent.parent / "results"  # the numbers in the README come from here

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
CHAT_MODEL = os.environ.get("SPARE_THUMBS_MODEL", "gemma4:e4b")
EMBED_MODEL = "embeddinggemma"

TZ = ZoneInfo("America/Toronto")
WORK_START, WORK_END = 9, 18  # hours I take meetings
# Addresses are personal, so they come from the environment or from settings.json in the private folder, never from the repo.
_SETTINGS = json.loads((DATA_DIR / "settings.json").read_text(encoding="utf-8")) if (DATA_DIR / "settings.json").exists() else {}

ME = os.environ.get("SPARE_THUMBS_ME", _SETTINGS.get("me", ""))
OWNER = os.environ.get("SPARE_THUMBS_NAME", "Jonathan")  # whose voice and calendar this is
BIO = os.environ.get("SPARE_THUMBS_BIO", "a freelance developer in Montreal")

# Only mail from these senders is answered. Everything else is left alone.
ALLOWED_SENDERS = [s.strip().lower() for s in os.environ.get("SPARE_THUMBS_ALLOW", ",".join(_SETTINGS.get("allow", []))).split(",") if s.strip()]

# Display-name overrides: in the demo my own second address plays the client, and its display name is mine.
CLIENT_NAMES = _SETTINGS.get("client_names", {})
