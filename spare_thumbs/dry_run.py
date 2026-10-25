"""One reschedule, end to end, against an in-memory calendar. No Google account needed."""
import sys
from datetime import datetime

from spare_thumbs.agent import MemoryCalendar, Run, run_agent
from spare_thumbs.config import TZ


def at(day: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=TZ)


def main() -> None:
    cal = MemoryCalendar([
        {"id": "ev-sam", "summary": "Sam / site review", "start": at(27, 10), "end": at(27, 11), "attendees": ["sam@example.com"]},
        {"id": "ev-assessor", "summary": "Insurance assessor (flood)", "start": at(27, 12, 30), "end": at(27, 14, 30), "attendees": []},
        {"id": "ev-sync", "summary": "Weekly sync", "start": at(28, 9), "end": at(28, 10), "attendees": []},
    ])
    text = sys.argv[1] if len(sys.argv) > 1 else "Hi Jon, something came up tomorrow morning, could we move our 10h to the afternoon? 13h maybe?"
    thread = [{"from": "sam@example.com", "from_name": "Sam Tremblay", "when": "2026-10-26T23:04", "text": text}]
    run = run_agent(Run(sender="sam@example.com", sender_name="Sam Tremblay", thread=thread, calendar=cal, now=at(26, 23, 4)))
    print("\nDRAFT:", run.draft, "\nOFFERED:", run.offered, "\nMOVED:", run.moved, "\nHANDED OFF:", run.handed_off, "\nREFUSED:", run.refused)


if __name__ == "__main__":
    main()
