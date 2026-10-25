"""My past replies, found by EmbeddingGemma, as examples of how I write."""
import json
import math
import re

import requests

from spare_thumbs.config import DATA_DIR, EMBED_MODEL, OLLAMA

PAIRS = [DATA_DIR / "pairs.jsonl", DATA_DIR / "learned_pairs.jsonl"]
INDEX = DATA_DIR / "voice_index.json"


def embed(texts: list[str]) -> list[list[float]]:
    r = requests.post(f"{OLLAMA}/api/embed", json={"model": EMBED_MODEL, "input": texts}, timeout=600)
    r.raise_for_status()
    return r.json()["embeddings"]


def load_pairs() -> list[dict]:
    out = []
    for path in PAIRS:
        if path.exists():
            out += [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [p for p in out if not p.get("polished")]


def key(p: dict) -> str:
    # Match on what they said; when I started the conversation, match on what I said.
    return p["them"] or p["me"]


def index() -> list[dict]:
    """Embeddings are cached by text, so only new pairs (e.g. replies I just sent) get embedded."""
    cache = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    pairs = load_pairs()
    missing = [key(p) for p in pairs if key(p) not in cache]
    if missing:
        cache.update(zip(missing, embed(missing)))
        INDEX.write_text(json.dumps(cache), encoding="utf-8")
    return [dict(p, vec=cache[key(p)]) for p in pairs]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


FRENCH = {"pas", "ça", "marche", "pour", "moi", "merci", "salut", "oui", "après-midi", "lundi", "mardi", "mercredi", "jeudi", "vendredi",
          "je", "c'est", "parfait", "bonne", "semaine", "demain", "capte", "avec", "mais", "très", "vous", "est", "une", "les", "nous", "bien",
          "que", "tu", "le", "la", "du", "et", "un", "j'ai", "au", "en", "te", "ton", "ta", "ce", "cette", "des", "aussi", "toi", "fait",
          "faire", "peux", "peut", "stp", "svp", "désolé", "desole", "bonjour", "bonsoir", "à", "là", "rencontre", "réunion", "reunion"}


def french_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w'-]+", text.lower()) if w in FRENCH}


def language(text: str) -> str:
    return "fr" if len(french_words(text)) >= 2 else "en"


def examples(message: str, k: int = 5, exclude: str | None = None) -> list[dict]:
    """The k replies I wrote to the messages most like this one, in the message's language. `exclude` holds one pair out for testing."""
    pool = [p for p in index() if p["me"] != exclude]
    # A French example under an English message is how French leaked into English drafts; keep to one language when there is enough.
    same = [p for p in pool if language(p["me"]) == language(message)]
    pool = same if len(same) >= k else pool
    if not pool:
        return []
    q = embed([message])[0]
    return sorted(pool, key=lambda p: cosine(q, p["vec"]), reverse=True)[:k]


def style_card(refresh: bool = False, without: set[str] | None = None, name: str = "style_card") -> str:
    """Gemma 4 reads my real replies once and writes down how I write. Cached until refreshed.

    `without` leaves replies out, so the blind test never shows Gemma a card built from the replies it is tested on.
    """
    path = DATA_DIR / f"{name}.txt"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    from spare_thumbs.config import CHAT_MODEL, OWNER
    kept = [p["me"] for p in load_pairs() if p["me"] not in (without or set())]
    if not kept:
        return ""  # nothing to describe yet; voice_guide says so instead of asking Gemma to invent a style
    replies = "\n---\n".join(kept)
    prompt = (f"Below are real messages written by one person, {OWNER}, separated by ---. Describe HOW he writes, not what he writes about, "
              "as 6 to 8 short bullet points another writer could follow to sound exactly like him: typical length, greetings and sign-offs, "
              "capitalisation, accents and spelling in French, typos and how he corrects them, abbreviations, punctuation and emoji, tone. "
              # Short fragments only, so the card describes style without carrying whole held-out replies into the blind test.
              "Quote short fragments of his words as examples (at most 3 words each), never a whole message. Bullets only.\n\n" + replies)
    r = requests.post(f"{OLLAMA}/api/chat", json={"model": CHAT_MODEL, "stream": False, "options": {"temperature": 0.2, "num_ctx": 8192},
                                                  "messages": [{"role": "user", "content": prompt}]}, timeout=600)
    r.raise_for_status()
    card = r.json()["message"]["content"].strip()
    path.write_text(card, encoding="utf-8")
    return card


def learn(them: str, me: str, when: str) -> None:
    """A reply I actually sent becomes an example for next time."""
    with (DATA_DIR / "learned_pairs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"them": them, "me": me, "when": when, "source": "gmail-sent", "polished": False}, ensure_ascii=False) + "\n")
