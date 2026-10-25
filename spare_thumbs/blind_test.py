"""The blind test: people who know me pick which of three replies I actually wrote.

    python -m spare_thumbs.blind_test build     # generate replies, write blind_items.json
    python -m spare_thumbs.blind_test form      # publish them as a Google Form, print the link
    python -m spare_thumbs.blind_test results   # tally the answers

Each held-out message gets: my real reply; Gemma 4 with my most similar real replies as examples
(the held-out reply itself excluded); and Gemma 4 with no examples. The order is shuffled per item.
"""
import json
import random
import re
import sys
from collections import Counter

import requests

from spare_thumbs import voice
from spare_thumbs.agent import voice_guide
from spare_thumbs.config import CHAT_MODEL, DATA_DIR, OLLAMA

ITEMS = DATA_DIR / "blind_items.json"
SHOWN_NAME = "Sam"  # every [NAME] is shown as the same name, so names cannot give the real reply away
PRIVATE = re.compile(r"\[(SECRET|LINK|COMPANY|EMAIL|PHONE)\]")


def write_reply(message: str, use_examples: bool, exclude: str | None, card: str | None = None) -> str:
    system = "You are Jonathan, a freelance developer in Montreal, replying to a message from a client or collaborator. Reply with the message text only." \
             + voice_guide(message, use_examples, exclude=exclude, keep_placeholder=True, card=card)
    r = requests.post(f"{OLLAMA}/api/chat", json={"model": CHAT_MODEL, "stream": False, "options": {"temperature": 0.4},
                                                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": message}]}, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def shown(text: str) -> str:
    return text.replace("[NAME]", SHOWN_NAME)


def build() -> None:
    # Voice only: scheduling replies depend on my calendar, which this test does not give Gemma.
    pool = [p for p in voice.load_pairs() if p["them"] and p.get("source") != "discord"
            and not PRIVATE.search(p["them"] + p["me"]) and len(p["me"]) >= 12]
    # Saved after every item, so a crash resumes where it stopped instead of starting over.
    items = json.loads(ITEMS.read_text(encoding="utf-8")) if ITEMS.exists() else []
    done = {it["message"] for it in items}
    # Two halves: each half's style card is written without seeing that half's real replies.
    halves = [{p["me"] for p in pool[0::2]}, {p["me"] for p in pool[1::2]}]
    cards = [voice.style_card(without=h, name=f"style_card_blind_{k}") for k, h in enumerate(halves)]
    for i, p in enumerate(pool):
        if shown(p["them"]) in done:
            continue
        replies = {"jonathan": p["me"], "gemma_with_my_replies": write_reply(p["them"], True, p["me"], cards[i % 2]),
                   "gemma_plain": write_reply(p["them"], False, None)}
        order = list(replies)
        random.Random(f"{i}-{p['when']}").shuffle(order)
        items.append({"message": shown(p["them"]), "options": [{"who": w, "text": shown(replies[w])} for w in order]})
        ITEMS.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{len(items)}/{len(pool)}", file=sys.stderr)
    print(f"{len(items)} items -> {ITEMS}")


def form() -> None:
    from spare_thumbs import google_api
    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    f = google_api.forms().forms().create(body={"info": {"title": "Which one did Jonathan write?"}}).execute()
    requests_ = [{"updateFormInfo": {"info": {"description":
        "Each message below got three replies. One is the reply Jonathan actually sent. Two were written by an AI. "
        "Pick the one you think Jonathan wrote. Names are replaced with 'Sam'. Go with your gut; it takes about 5 minutes."},
        "updateMask": "description"}}]
    for i, it in enumerate(items):
        requests_.append({"createItem": {"location": {"index": i}, "item": {
            "title": f"{i + 1}. The message", "description": it["message"],
            "questionItem": {"question": {"required": True, "choiceQuestion": {"type": "RADIO",
                # Form options cannot hold line breaks, so multi-line replies are joined with " / ".
                "options": [{"value": f"{'ABC'[j]}: " + " / ".join(l for l in o["text"].splitlines() if l.strip())} for j, o in enumerate(it["options"])]}}}}}})
    google_api.forms().forms().batchUpdate(formId=f["formId"], body={"requests": requests_}).execute()
    (DATA_DIR / "blind_form.json").write_text(json.dumps({"formId": f["formId"], "url": f["responderUri"]}), encoding="utf-8")
    print(f["responderUri"])


def results() -> None:
    from spare_thumbs import google_api
    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    form_id = json.loads((DATA_DIR / "blind_form.json").read_text())["formId"]
    f = google_api.forms().forms().get(formId=form_id).execute()
    qid = {it["questionItem"]["question"]["questionId"]: i for i, it in enumerate(f["items"])}
    res = google_api.forms().forms().responses().list(formId=form_id).execute().get("responses", [])
    picks = Counter()
    for r in res:
        for q, a in r.get("answers", {}).items():
            letter = a["textAnswers"]["answers"][0]["value"][0]
            picks[items[qid[q]]["options"]["ABC".index(letter)]["who"]] += 1
    total = sum(picks.values())
    print(f"{len(res)} people, {total} picks")
    for who in ("jonathan", "gemma_with_my_replies", "gemma_plain"):
        print(f"  picked {who} as Jonathan: {picks[who]} ({picks[who] / total:.0%})" if total else f"  {who}: 0")
    (DATA_DIR / "blind_results.json").write_text(json.dumps({"people": len(res), "picks": dict(picks)}), encoding="utf-8")


if __name__ == "__main__":
    {"build": build, "form": form, "results": results}[sys.argv[1]]()
