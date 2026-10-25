"""Turn WhatsApp chat exports into (their message, my reply) pairs, redacted.

Raw exports stay in the private data folder. Only redacted pairs come out of here.
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from spare_thumbs.config import DATA_DIR

LINE = re.compile(r"^\[(\d{1,2}/\d{1,2}/\d{2}), (\d{1,2}:\d{2}:\d{2}\s?[AP]M)\] ([^:]+): (.*)$")
MEDIA = re.compile(r"<[^>]*omitted>\s*")
SKIP = ("This message was deleted", "end-to-end encrypted", "[Call]")
NEW_TOPIC_HOURS = 3  # a reply this late is me starting something, not answering

# Redaction runs on every text that can reach a prompt, a draft or the repo.
REDACT = [
    (re.compile(r"(?i)(mot(s)? de passe|password|login|identifiant)\s*:?\s*\S+"), r"\1: [SECRET]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"https?://\S+"), "[LINK]"),
    (re.compile(r"\+?\d[\d ()-]{8,}\d"), "[PHONE]"),
    # Long tokens mixing letters, digits and symbols are passwords in this data.
    (re.compile(r"\b(?=\S*\d)(?=\S*[^\w\s])\S{8,}"), "[SECRET]"),
]


def load_list(name: str) -> list[str]:
    """People and company names live in the private folder, so the repo never names them."""
    path = DATA_DIR / name
    return [n.strip() for n in path.read_text(encoding="utf-8").splitlines() if n.strip()] if path.exists() else []


def redact(text: str, names: list[str], companies: list[str]) -> str:
    for pattern, repl in REDACT:
        text = pattern.sub(repl, text)
    for words, tag in ((companies, "[COMPANY]"), (names, "[NAME]")):
        for w in words:
            text = re.sub(rf"\b{re.escape(w)}\b", tag, text, flags=re.I)
    return text


def parse(path: Path) -> list[dict]:
    """Messages as {who, when, text}; continuation lines are joined to the message above."""
    messages = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.replace("‎", "")
        m = LINE.match(raw)
        if m:
            when = datetime.strptime(f"{m[1]} {m[2].replace(chr(8239), ' ')}", "%m/%d/%y %I:%M:%S %p")
            messages.append({"who": "me" if m[3] == "You" else "them", "when": when, "text": MEDIA.sub("", m[4])})
        elif messages:
            messages[-1]["text"] += "\n" + raw
    return [m for m in messages if not any(s in m["text"] for s in SKIP) and m["text"].strip()]


def pairs(messages: list[dict]) -> list[dict]:
    """Group runs by speaker, then pair each run of mine with the run of theirs just before it."""
    runs = []
    for m in messages:
        if runs and runs[-1]["who"] == m["who"] and (m["when"] - runs[-1]["end"]).total_seconds() < 600:
            runs[-1]["text"] += "\n" + m["text"]
            runs[-1]["end"] = m["when"]
        else:
            runs.append({"who": m["who"], "text": m["text"], "end": m["when"]})
    out = []
    for prev, cur in zip([None] + runs, runs):
        if cur["who"] != "me":
            continue
        answering = prev and prev["who"] == "them" and (cur["end"] - prev["end"]).total_seconds() < NEW_TOPIC_HOURS * 3600
        out.append({"them": prev["text"] if answering else "", "me": cur["text"], "when": cur["end"].isoformat()})
    return out


def has_words(text: str) -> bool:
    return bool(re.search(r"[A-Za-zÀ-ÿ]{2,}", re.sub(r"\[[A-Z]+\]", "", text)))


def main() -> None:
    names, companies = load_list("names.txt"), load_list("companies.txt")
    out = []
    found = [dict(p, source="whatsapp") for chat in sorted((DATA_DIR / "raw").glob("*/chat.txt")) for p in pairs(parse(chat))]
    manual = DATA_DIR / "manual_pairs.jsonl"  # typed from screenshots (Discord)
    if manual.exists():
        found += [json.loads(line) for line in manual.read_text(encoding="utf-8").splitlines() if line.strip()]
    for p in found:
        p = {k: redact(v, names, companies) if k in ("them", "me") else v for k, v in p.items()}
        if not has_words(p["me"]):
            continue
        # Long structured messages were written with help; they are not my texting voice.
        p["polished"] = len(p["me"]) > 350
        out.append(p)
    dest = DATA_DIR / "pairs.jsonl"
    dest.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in out) + "\n", encoding="utf-8")
    print(f"{len(out)} pairs ({sum(not p['polished'] for p in out)} in my texting voice) -> {dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
