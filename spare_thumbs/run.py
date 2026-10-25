"""Watch my Gmail. When an allowed client writes, let Gemma answer from my calendar, as a draft.

    python -m spare_thumbs.run           # poll every 20 seconds
    python -m spare_thumbs.run --once    # one pass, then exit
"""
import json
import sys
import time
from datetime import datetime

from spare_thumbs import google_api, voice
from spare_thumbs.agent import GoogleCalendar, Run, run_agent
from spare_thumbs.config import ALLOWED_SENDERS, CLIENT_NAMES, DATA_DIR, ME, OWNER, TZ

STATE = DATA_DIR / "state.json"


def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(state: dict) -> None:
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def learn_from_sent(thread: list[dict], st: dict) -> None:
    """Once I send a reply in a thread Gemma drafted, my sent text becomes a voice example."""
    if not st.get("draft_at") or st.get("learned_upto", "") >= st["draft_at"]:
        return
    for prev, m in zip(thread, thread[1:]):
        if m["from"] == ME and m["when"] >= st["draft_at"] and prev["from"] != ME:
            voice.learn(prev["text"], m["text"], m["when"])
            st["learned_upto"] = m["when"]
            print(f"  learned: my sent reply in '{m['subject']}' is now a voice example")


def poll(state: dict, calendar: GoogleCalendar) -> None:
    for thread in google_api.recent_threads(ALLOWED_SENDERS):
        for m in thread:
            m["from_name"] = CLIENT_NAMES.get(m["from"], m["from_name"])
        latest = thread[-1]
        st = state.setdefault(latest["thread_id"], {})
        learn_from_sent(thread, st)
        if latest["from"] not in ALLOWED_SENDERS or st.get("answered") == latest["id"]:
            continue
        first_line = next((l for l in latest["text"].splitlines() if l.strip()), "")
        print(f"\n[{datetime.now(TZ):%H:%M:%S}] {latest['from_name'] or latest['from']}: {first_line[:160]}")
        run = Run(sender=latest["from"], sender_name=latest["from_name"], thread=thread, calendar=calendar,
                  now=datetime.now(TZ), pending=st.get("pending", {}),
                  send=lambda text: google_api.create_draft(latest, text))
        run_agent(run)
        st["answered"] = latest["id"]
        st["pending"] = run.pending
        if run.draft:
            st["draft_at"] = datetime.now(TZ).isoformat(timespec="minutes")
            print("  saved as a draft in the Gmail thread")
        if run.moved:
            print(f"  moved in Google Calendar: {run.moved['from']} -> {run.moved['to']}")
        if not (run.draft or run.handed_off):
            print(f"  NO OUTCOME: Gemma ended without a draft or a hand-off; leaving this one for {OWNER}")
        save_state(state)


def main() -> None:
    state, calendar = load_state(), GoogleCalendar()
    print(f"Spare Thumbs watching {ME} for {', '.join(ALLOWED_SENDERS)}")
    while True:
        poll(state, calendar)
        save_state(state)
        if "--once" in sys.argv:
            break
        time.sleep(20)


if __name__ == "__main__":
    main()
