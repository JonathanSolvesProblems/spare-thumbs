"""The blind test without a form: a model from another family plays the friend who knows how I write.

    python -m spare_thumbs.judge                 # qwen3.5:4b
    python -m spare_thumbs.judge qwen2.5vl:7b    # a second judge

The judge is not Gemma, so it has no taste for Gemma's own phrasing. It reads 8 of my real replies
(never the one being tested), then the message and the three replies from blind_items.json, and
picks the one I wrote. Every item is asked in all 6 orders, so a judge that favours "A" gains nothing.
"""
import json
import random
import sys
from collections import Counter
from itertools import permutations

import requests

from spare_thumbs import voice
from spare_thumbs.blind_test import ITEMS, shown
from spare_thumbs.config import OLLAMA, RESULTS

REFERENCES = 8


def ask(model: str, refs: list[str], message: str, options: list[str]) -> str:
    prompt = ("Here are real messages written by Jonathan, separated by ---:\n\n" + "\n---\n".join(refs) +
              f"\n\nSomeone sent Jonathan this message:\n{message}\n\n"
              "Below are three replies. Exactly one is the reply Jonathan actually sent; the other two were written by an AI. "
              "Which one did Jonathan write?\n\n" + "\n\n".join(f"{'ABC'[i]}: {o}" for i, o in enumerate(options)))
    r = requests.post(f"{OLLAMA}/api/chat", json={
        "model": model, "stream": False, "think": False, "options": {"temperature": 0},
        "format": {"type": "object", "properties": {"pick": {"type": "string", "enum": ["A", "B", "C"]}}, "required": ["pick"]},
        "messages": [{"role": "user", "content": prompt}]}, timeout=600)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])["pick"]


def main(model: str) -> None:
    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    mine = [shown(p["me"]) for p in voice.load_pairs()]
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"judge_{model.replace(':', '_').replace('/', '_')}.json"
    # Saved after every item, so a crash resumes where it stopped.
    per_item = json.loads(out.read_text(encoding="utf-8"))["per_item"] if out.exists() else []
    for i, it in enumerate(items[len(per_item):], start=len(per_item)):
        real = next(o["text"] for o in it["options"] if o["who"] == "jonathan")
        refs = random.Random(i).sample([m for m in mine if m != real], REFERENCES)
        item = Counter()
        for order in permutations(it["options"]):
            who = order["ABC".index(ask(model, refs, it["message"], [o["text"] for o in order]))]["who"]
            item[who] += 1
        per_item.append(dict(item))
        out.write_text(json.dumps({"model": model, "items": len(per_item), "per_item": per_item}, indent=2), encoding="utf-8")
        print(f"{i + 1}/{len(items)} {dict(item)}", file=sys.stderr)
    picks = sum((Counter(p) for p in per_item), Counter())
    total = sum(picks.values())
    print(f"judge {model}: {len(items)} messages x 6 orders = {total} picks")
    for who in ("jonathan", "gemma_with_my_replies", "gemma_plain"):
        print(f"  picked {who} as Jonathan: {picks[who]} ({picks[who] / total:.0%})")
    out.write_text(json.dumps({"model": model, "items": len(per_item), "picks": dict(picks), "per_item": per_item}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "qwen3.5:4b")
