"""Does the reply ever offer a time I am already booked? Same requests, with and without my calendar.

    python -m spare_thumbs.gate_test

Each request is answered twice by Gemma 4 with my voice examples on: once as Spare Thumbs (calendar
tools plus the gate), once with no calendar. Every time the draft offers or accepts is then checked
against the calendar. The calendar is the grader: a time either overlaps an event or it does not.
"""
import json
import sys
from datetime import datetime

from spare_thumbs.agent import MemoryCalendar, Run, conflicts, meeting_minutes, parse_time, run_agent
from spare_thumbs.config import RESULTS, TZ

CLIENT, NAME = "sam@example.com", "Sam Tremblay"
NOW = datetime(2026, 10, 25, 22, 0, tzinfo=TZ)  # Sunday night


def at(day: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def week() -> MemoryCalendar:
    return MemoryCalendar([
        {"id": "ev-sam", "summary": "Sam / site review", "start": at(26, 10), "end": at(26, 11), "attendees": [CLIENT]},
        {"id": "ev-assessor", "summary": "Insurance assessor (flood)", "start": at(26, 12, 30), "end": at(26, 14, 30), "attendees": []},
        {"id": "ev-dentist", "summary": "Dentist", "start": at(26, 16), "end": at(26, 17), "attendees": []},
        {"id": "ev-workshop", "summary": "Client workshop", "start": at(27, 9), "end": at(27, 12), "attendees": []},
        {"id": "ev-call", "summary": "Client call", "start": at(27, 14), "end": at(27, 15), "attendees": []},
        {"id": "ev-onsite", "summary": "On site, Laval", "start": at(28, 13), "end": at(28, 17), "attendees": []},
        {"id": "ev-sync", "summary": "Team sync", "start": at(29, 9), "end": at(29, 10), "attendees": []},
        {"id": "ev-accountant", "summary": "Accountant", "start": at(30, 11), "end": at(30, 12), "attendees": []},
    ])


REQUESTS = [
    "Hi Jon, something came up tomorrow morning, could we move our 10h to 13h?",
    "Hey, can we do Tuesday morning instead for the site review?",
    "Would Wednesday 14h work instead of Monday?",
    "Could we push the review to Saturday morning? Easier for me",
    "Can we move it to Thursday 9h30?",
    "Friday 11h works for me, does it for you?",
    "Can we do tomorrow 19h after work instead?",
    "Can we do Monday 15h instead of 10h?",
    "Tuesday 15h maybe?",
    "Any chance we can do Wednesday afternoon instead?",
]


def answer(text: str, use_calendar: bool) -> dict:
    cal = week()
    thread = [{"from": CLIENT, "from_name": NAME, "when": "2026-10-25T22:00", "text": text}]
    run = run_agent(Run(sender=CLIENT, sender_name=NAME, thread=thread, calendar=cal, now=NOW, use_calendar=use_calendar,
                        pending={"meeting": {"event_id": "ev-sam", "minutes": 60}}), log=lambda s: None)
    # Graded against a fresh copy of the week, with Sam's own meeting ignored (moving it there is fine).
    grader = Run(sender=CLIENT, sender_name=NAME, thread=thread, calendar=week(), now=NOW)
    busy = {t: conflicts(grader, parse_time(t), meeting_minutes(run), "ev-sam") for t in run.offered}
    return {"draft": run.draft, "offered": run.offered, "busy": {t: p for t, p in busy.items() if p},
            "blocked_busy": sum(len(r.get("times", {})) for r in run.refused),
            "blocked_unchecked": sum(len(r.get("unchecked", [])) for r in run.refused),
            "blocked_language": sum(1 for r in run.refused if "language" in r), "handed_off": run.handed_off}


def main() -> None:
    rows = []
    for text in REQUESTS:
        row = {"request": text, "spare_thumbs": answer(text, True), "no_calendar": answer(text, False)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), file=sys.stderr)
    for arm in ("spare_thumbs", "no_calendar"):
        offered = sum(len(r[arm]["offered"]) for r in rows)
        busy = sum(len(r[arm]["busy"]) for r in rows)
        bad = sum(1 for r in rows if r[arm]["busy"])
        print(f"{arm}: {bad}/{len(rows)} drafts offer a time I am booked ({busy} of {offered} times offered); "
              f"drafts written {sum(1 for r in rows if r[arm]['draft'])}/{len(rows)}")
    for arm in ("spare_thumbs", "no_calendar"):
        print(f"{arm} gate blocks before the draft: " + ", ".join(
            f"{k.removeprefix('blocked_')} {sum(r[arm][k] for r in rows)}" for k in ("blocked_busy", "blocked_unchecked", "blocked_language")))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "gate_results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
