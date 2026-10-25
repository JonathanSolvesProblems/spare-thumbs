"""The loop: Gemma 4 reads a client's message, looks at my calendar, and decides what to do.

Gemma chooses every step through native function calling. Code only runs the tools and
refuses any reply or move that would put a meeting on top of something already in my calendar.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import requests

from spare_thumbs import voice
from spare_thumbs.config import BIO, CHAT_MODEL, OLLAMA, OWNER, TZ, WORK_END, WORK_START

MAX_STEPS = 12  # safety net only; the loop ends when Gemma stops calling tools


# ---- calendars: the real one, or an in-memory one for tests and the eval ----

class GoogleCalendar:
    def __init__(self):
        from spare_thumbs import google_api
        self.g = google_api

    def events(self, start, end):
        return self.g.events_between(start, end)

    def move(self, event_id, start, end):
        self.g.move_event(event_id, start, end)


class MemoryCalendar:
    def __init__(self, events: list[dict]):
        self.items = events

    def events(self, start, end):
        return [e for e in self.items if e["end"] > start and e["start"] < end]

    def move(self, event_id, start, end):
        e = next(e for e in self.items if e["id"] == event_id)
        e["start"], e["end"] = start, end


# ---- what one run did ----

@dataclass
class Run:
    sender: str
    sender_name: str
    thread: list[dict]
    calendar: object
    now: datetime
    pending: dict = field(default_factory=dict)  # what I offered earlier in this thread
    use_calendar: bool = True
    use_examples: bool = True
    send: callable = None  # writes the draft into Gmail; None means dry run
    steps: list = field(default_factory=list)
    draft: str | None = None
    offered: list = field(default_factory=list)
    moved: dict | None = None
    handed_off: str | None = None
    refused: list = field(default_factory=list)


def parse_time(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    return t.replace(tzinfo=TZ) if t.tzinfo is None else t.astimezone(TZ)


def day_view(run: Run, day: str) -> dict:
    d = datetime.fromisoformat(day).replace(tzinfo=TZ)
    start, end = d.replace(hour=WORK_START), d.replace(hour=WORK_END)
    busy = run.calendar.events(d, d + timedelta(days=1))
    view = {"date": day, "weekday": d.strftime("%A"), "busy": [
        {"from": e["start"].strftime("%H:%M"), "to": e["end"].strftime("%H:%M"), "what": e["summary"], "event_id": e["id"]} for e in busy]}
    if d.weekday() >= 5:
        view["note"] = f"Weekend: {OWNER} does not take meetings."
        view["free"] = []
        return view
    free, cursor = [], max(start, run.now)
    for e in sorted(busy, key=lambda e: e["start"]):
        if e["start"] - cursor >= timedelta(minutes=30) and cursor < end:
            free.append(f"{cursor:%H:%M}-{min(e['start'], end):%H:%M}")
        cursor = max(cursor, e["end"])
    if end - cursor >= timedelta(minutes=30):
        free.append(f"{cursor:%H:%M}-{end:%H:%M}")
    view["free"] = free
    return view


def conflicts(run: Run, start: datetime, minutes: int, ignore: str | None) -> list[str]:
    """Every reason a meeting at `start` cannot happen. Empty means the slot is really free."""
    end = start + timedelta(minutes=minutes)
    why = []
    if start < run.now:
        why.append(f"{start:%a %d %b %H:%M} is in the past")
    if start.weekday() >= 5:
        why.append(f"{start:%a %d %b} is a weekend")
    if start.hour < WORK_START or end > start.replace(hour=WORK_END, minute=0):
        why.append(f"{start:%H:%M}-{end:%H:%M} is outside {WORK_START}h-{WORK_END}h")
    for e in run.calendar.events(start, end):
        if e["id"] != ignore:
            why.append(f"overlaps '{e['summary']}' {e['start']:%H:%M}-{e['end']:%H:%M} on {e['start']:%a %d %b}")
    return why


TIME_H = re.compile(r"\b([01]?\d|2[0-3])\s?h\s?([0-5]\d)?\b")  # 13h, 15h30, 9h
TIME_COLON = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")  # 14:30
TIME_AMPM = re.compile(r"\b(1[0-2]|0?[1-9])(?::([0-5]\d))?\s?([ap])\.?m\b", re.I)  # 3pm, 3:30 pm
french_words = voice.french_words


def mentioned_times(text: str) -> set[str]:
    """Every clock time written in a message, as HH:MM."""
    out = {f"{int(h) % 12 + (12 if ap.lower() == 'p' else 0):02d}:{m or '00'}" for h, m, ap in TIME_AMPM.findall(text)}
    rest = TIME_AMPM.sub(" ", text)  # so "3:30 pm" is not read a second time as 03:30
    return out | {f"{int(h):02d}:{m or '00'}" for h, m in TIME_H.findall(rest) + TIME_COLON.findall(rest)}


def unchecked(run: Run, text: str, times: list[str]) -> list[str]:
    """Times the reply writes out but did not pass to the gate. Echoing the client's own time ("13h is booked") is fine."""
    allowed = {parse_time(t).strftime("%H:%M") for t in times} | mentioned_times(run.thread[-1]["text"]) | {f"{WORK_END}:00"}
    return sorted(mentioned_times(text) - allowed)


def meeting_minutes(run: Run) -> int:
    m = run.pending.get("meeting")
    return int(m["minutes"]) if m else 60


# ---- tools ----

def find_meetings(run: Run) -> dict:
    events = run.calendar.events(run.now, run.now + timedelta(days=21))
    first = run.sender_name.split()[0].lower() if run.sender_name else "~"
    mine = [e for e in events if run.sender in e.get("attendees", []) or first in e["summary"].lower()]
    return {"meetings": [{"event_id": e["id"], "what": e["summary"], "start": e["start"].strftime("%Y-%m-%dT%H:%M"),
                          "weekday": e["start"].strftime("%A"), "minutes": int((e["end"] - e["start"]).total_seconds() // 60)} for e in mine]}


def check_calendar(run: Run, date: str) -> dict:
    return day_view(run, date)


def draft_reply(run: Run, text: str, offered_times: list[str] | None = None, accepted_time: str | None = None, event_id: str | None = None) -> dict:
    if event_id:
        found = next((m for m in find_meetings(run)["meetings"] if m["event_id"] == event_id), None)
        if found:
            run.pending["meeting"] = found
    times = list(offered_times or []) + ([accepted_time] if accepted_time else [])
    leaked = french_words(text) if len(french_words(run.thread[-1]["text"])) < 2 else set()
    if leaked:
        run.refused.append({"tool": "draft_reply", "language": sorted(leaked)})
        return {"error": f"not drafted: the client wrote in English but the reply has French words: {', '.join(sorted(leaked))}",
                "retryable": True, "hint": "rewrite the whole reply in English"}
    if run.use_calendar and (loose := unchecked(run, text, times)):
        run.refused.append({"tool": "draft_reply", "unchecked": loose})
        return {"error": f"not drafted: the reply mentions {', '.join(loose)} but offered_times does not list it, so it was never checked",
                "retryable": True, "hint": "put every time you propose in offered_times as YYYY-MM-DDTHH:MM"}
    if run.use_calendar:
        ignore = (run.pending.get("meeting") or {}).get("event_id")
        problems = {t: conflicts(run, parse_time(t), meeting_minutes(run), ignore) for t in times}
        problems = {t: p for t, p in problems.items() if p}
        if problems:
            run.refused.append({"tool": "draft_reply", "times": problems})
            return {"error": "not drafted: some times are not free", "conflicts": problems, "retryable": True,
                    "hint": "call check_calendar for that day and offer only times listed under free"}
    run.draft, run.offered = text, times
    run.pending["offered"] = times
    if run.send:
        run.pending["draft_id"] = run.send(text)
    return {"ok": True, "drafted": True}


def move_event(run: Run, event_id: str, new_start: str) -> dict:
    meeting = next((m for m in find_meetings(run)["meetings"] if m["event_id"] == event_id), None)
    if not meeting:
        return {"error": f"no upcoming meeting with this client has id {event_id}", "retryable": True, "hint": "call find_meetings"}
    start = parse_time(new_start)
    problems = conflicts(run, start, meeting["minutes"], event_id)
    if problems:
        run.refused.append({"tool": "move_event", "times": {new_start: problems}})
        return {"error": "not moved: that time is not free", "conflicts": problems, "retryable": True}
    run.calendar.move(event_id, start, start + timedelta(minutes=meeting["minutes"]))
    run.moved = {"event_id": event_id, "from": meeting["start"], "to": new_start}
    return {"ok": True, "moved_to": new_start}


def hand_off(run: Run, reason: str) -> dict:
    run.handed_off = reason
    return {"ok": True}


TOOLS = {
    "find_meetings": (find_meetings, "List my upcoming meetings with this client (next 3 weeks), with event ids.", {}),
    "check_calendar": (check_calendar, "My calendar for one day: what is booked and which times are free.",
                       {"date": {"type": "string", "description": "YYYY-MM-DD"}}),
    "draft_reply": (draft_reply, "Write the reply to the client as a draft in my email. Use offered_times for times you propose, accepted_time when you agree to their time. The draft is refused if any of those times is not free.",
                    {"text": {"type": "string", "description": "the whole reply, written the way I write"},
                     "offered_times": {"type": "array", "items": {"type": "string"}, "description": "times you propose, YYYY-MM-DDTHH:MM"},
                     "accepted_time": {"type": "string", "description": "the client's time you agree to, YYYY-MM-DDTHH:MM"},
                     "event_id": {"type": "string", "description": "the meeting this is about, from find_meetings"}}),
    "move_event": (move_event, "Move a meeting in my calendar. Only after the client has agreed to the new time.",
                   {"event_id": {"type": "string"}, "new_start": {"type": "string", "description": "YYYY-MM-DDTHH:MM"}}),
    "hand_off": (hand_off, "Leave this message for me to answer myself: it is not about scheduling, or it needs something only I know.",
                 {"reason": {"type": "string"}}),
}
REQUIRED = {"check_calendar": ["date"], "draft_reply": ["text"], "move_event": ["event_id", "new_start"], "hand_off": ["reason"]}


def tool_specs(run: Run) -> list[dict]:
    names = [n for n in TOOLS if run.use_calendar or n not in ("find_meetings", "check_calendar", "move_event")]
    return [{"type": "function", "function": {"name": n, "description": TOOLS[n][1],
             "parameters": {"type": "object", "properties": TOOLS[n][2], "required": REQUIRED.get(n, [])}}} for n in names]


# ---- prompt ----

def system_prompt(run: Run, latest: str) -> str:
    days = "\n".join(f"- {(run.now + timedelta(days=i)):%A %Y-%m-%d}" + (" (today)" if i == 0 else " (tomorrow)" if i == 1 else "") for i in range(10))
    lines = [
        f"You answer messages for {OWNER}, as {OWNER}. He is {BIO}. It is now {run.now:%A %Y-%m-%d %H:%M}.",
        f"He takes meetings on weekdays between {WORK_START}h and {WORK_END}h. The next days are:\n{days}",
        "",
        "Decide what to do with the client's newest message:",
        "- They want to move, book or confirm a meeting: call find_meetings, call check_calendar for each day involved, then draft_reply. Accept their time if it is free; if not, offer two times that check_calendar lists as free (one if only one is), so they have a choice.",
        "- They agree to a time you offered earlier: call move_event, then draft_reply to confirm.",
        "- You need one detail before you can act (which meeting, which day): draft_reply asking only that.",
        "- Anything else: hand_off.",
        "You may give a short reason in the reply (\"I have another meeting then\"), but never names or details of other events.",
    ]
    if not run.use_calendar:
        lines = [l for l in lines if "check_calendar" not in l and "move_event" not in l and "find_meetings" not in l]
        lines.insert(4, "- They want to move, book or confirm a meeting: draft_reply with a time that works.")
    if run.pending.get("offered"):
        m = run.pending.get("meeting") or {}
        lines.append(f"\nEarlier in this thread you offered: {', '.join(run.pending['offered'])}" + (f" for '{m.get('what')}' (event_id {m.get('event_id')})." if m else "."))
    lines.append(voice_guide(latest, run.use_examples))
    return "\n".join(lines)


def voice_guide(latest: str, use_examples: bool, exclude: str | None = None, keep_placeholder: bool = False, card: str | None = None) -> str:
    """How the owner writes: the instruction, plus his style card and most similar real replies when examples are on."""
    lines = [f"\nWrite exactly like {OWNER}. Rules:",
             "- Reply only in the language of the message. Never mix French into an English reply, or English into a French one.",
             "- At most one emoji, and often none.",
             "- Never add facts, plans or excuses that are not in the message or a tool result.",
             "- If the reply mentions a time, write it like 13h or 15h30."]
    if use_examples:
        card = card or voice.style_card()
        examples = voice.examples(latest, exclude=exclude)
        if not card and not examples:
            # No voice data yet (a fresh clone): say so instead of pretending, and keep it short.
            lines.append(f"There are no examples of how {OWNER} writes yet. Write short, plain and friendly, two sentences at most.")
            return "\n".join(lines)
        lines.append(f"How {OWNER} writes (notes Gemma made from his real messages):\n" + card)
        name_rule = "keep writing [NAME] for it" if keep_placeholder else "use the client's real first name"
        lines.append(f"These are real replies he wrote. [NAME] stands for the other person's first name; {name_rule}.\n")
        for ex in examples:
            lines.append(f"Them: {ex['them'] or '(he wrote first)'}\n{OWNER}: {ex['me']}\n")
    return "\n".join(lines)


def conversation(run: Run) -> str:
    out = []
    for m in run.thread[-6:]:
        who = OWNER if m["from"] != run.sender else (m.get("from_name") or "Client")
        out.append(f"{who} ({m['when']}):\n{m['text']}")
    return "\n\n".join(out)


# ---- the terminal log: one readable line per decision, because it is on screen in the demo ----

RED, GREEN, DIM, OFF = "\033[31m", "\033[32m", "\033[2m", "\033[0m"


def hhmm(t: str) -> str:
    return parse_time(t).strftime("%a %d %b %H:%M")


def describe(name: str, args: dict, result: dict) -> str:
    if "error" in result:
        c = result.get("conflicts") or [result["error"].removeprefix("not drafted: ")]  # draft_reply: {time: [reasons]}, move_event: [reasons]
        why = "; ".join(sum(c.values(), []) if isinstance(c, dict) else c)
        tried = f"\n     {DIM}{args['text']}{OFF}" if name == "draft_reply" and args.get("text") else ""
        return f"  gemma -> {name}{tried}\n  {RED}BLOCKED: {why}{OFF}\n  {DIM}(sent back to Gemma to try again){OFF}"
    if name == "find_meetings":
        found = ", ".join(f"{m['what']} {hhmm(m['start'])}" for m in result["meetings"]) or "none"
        return f"  gemma -> find_meetings        {DIM}{found}{OFF}"
    if name == "check_calendar":
        busy = ", ".join(f"{b['from']}-{b['to']}" for b in result["busy"]) or "nothing"
        free = ", ".join(result["free"]) or result.get("note", "nothing")
        return f"  gemma -> check_calendar {result['weekday'][:3]} {args['date']}   {DIM}busy {busy} | free {free}{OFF}"
    if name == "draft_reply":
        times = ", ".join(hhmm(t) for t in (args.get("offered_times") or []) + ([args["accepted_time"]] if args.get("accepted_time") else []))
        return f"  gemma -> draft_reply" + (f"  ({times})" if times else "") + f"\n  {GREEN}DRAFT:{OFF} {args['text']}"
    if name == "move_event":
        return f"  gemma -> move_event  {GREEN}MOVED to {hhmm(args['new_start'])}{OFF}"
    if name == "hand_off":
        return f"  gemma -> hand_off  {DIM}left for {OWNER}: {args.get('reason', '')}{OFF}"
    return f"  gemma -> {name}({json.dumps(args, ensure_ascii=False)})"


# ---- the loop ----

def chat(messages: list[dict], tools: list[dict]) -> dict:
    r = requests.post(f"{OLLAMA}/api/chat", json={"model": CHAT_MODEL, "messages": messages, "tools": tools, "stream": False,
                                                  "options": {"temperature": 0.4, "num_ctx": 8192}}, timeout=600)
    r.raise_for_status()
    return r.json()


def run_agent(run: Run, log=print) -> Run:
    latest = run.thread[-1]["text"]
    messages = [{"role": "system", "content": system_prompt(run, latest)},
                {"role": "user", "content": f"The email thread (newest last):\n\n{conversation(run)}"}]
    tools = tool_specs(run)
    reminded = False
    for _ in range(MAX_STEPS):
        res = chat(messages, tools)
        msg = res["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            if res.get("done_reason") == "length":
                raise RuntimeError("Gemma's turn was cut off (done_reason=length); not treating it as finished")
            if not (run.draft or run.handed_off or reminded):
                # A turn that ends with no draft and no hand-off leaves the client unanswered; say so once.
                reminded = True
                messages.append({"role": "user", "content": "Nothing was drafted or handed off yet. Call draft_reply or hand_off."})
                continue
            break  # end of turn: Gemma has nothing left to do
        for call in calls:
            name, args = call["function"]["name"], call["function"].get("arguments") or {}
            if isinstance(args, str):
                args = json.loads(args)
            fn = TOOLS.get(name, (None,))[0]
            try:
                result = fn(run, **args) if fn else {"error": f"unknown tool {name}", "retryable": True}
            except TypeError as e:
                result = {"error": f"bad arguments for {name}: {e}", "retryable": True}
            run.steps.append({"tool": name, "args": args, "result": result})
            log(describe(name, args, result))
            messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False, default=str)})
    return run
