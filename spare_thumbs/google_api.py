"""Gmail and Google Calendar for one account. Credentials and tokens stay in the private data folder."""
import base64
import re
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from spare_thumbs.config import DATA_DIR, TZ

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/forms.body",  # the blind test form
    "https://www.googleapis.com/auth/forms.responses.readonly",
]
_services = {}


def _creds() -> Credentials:
    token = DATA_DIR / "token.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        creds = InstalledAppFlow.from_client_secrets_file(str(DATA_DIR / "credentials.json"), SCOPES).run_local_server(port=0)
    token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def gmail():
    if "gmail" not in _services:
        _services["gmail"] = build("gmail", "v1", credentials=_creds())
    return _services["gmail"]


def calendar():
    if "cal" not in _services:
        _services["cal"] = build("calendar", "v3", credentials=_creds())
    return _services["cal"]


def forms():
    if "forms" not in _services:
        _services["forms"] = build("forms", "v1", credentials=_creds())
    return _services["forms"]


# ---- Gmail ----

def _header(msg: dict, name: str) -> str:
    return next((h["value"] for h in msg["payload"].get("headers", []) if h["name"].lower() == name.lower()), "")


def _plain(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "replace")
    for part in payload.get("parts", []):
        text = _plain(part)
        if text:
            return text
    return ""


QUOTE_START = re.compile(r"^(On .+wrote:|Le .+a écrit\s?:|From: .+|De : .+|_{10,}|-----Original Message-----)", re.M)


def strip_quote(text: str) -> str:
    """Only the new part of an email, without the thread quoted under it."""
    m = QUOTE_START.search(text)
    text = text[: m.start()] if m else text
    return "\n".join(l for l in text.splitlines() if not l.startswith(">")).strip()


def simplify(msg: dict) -> dict:
    return {
        "id": msg["id"],
        "thread_id": msg["threadId"],
        "from": parseaddr(_header(msg, "From"))[1].lower(),
        "from_name": parseaddr(_header(msg, "From"))[0],
        "subject": _header(msg, "Subject"),
        "message_id": _header(msg, "Message-ID"),
        "when": datetime.fromtimestamp(int(msg["internalDate"]) / 1000, TZ).isoformat(timespec="minutes"),
        "text": strip_quote(_plain(msg["payload"])),
        "labels": msg.get("labelIds", []),
    }


def recent_threads(senders: list[str], days: int = 3) -> list[list[dict]]:
    # Only threads with these senders are fetched in full; fetching the whole inbox runs into Gmail's per-minute quota.
    res = gmail().users().threads().list(userId="me", q=f"in:inbox newer_than:{days}d from:({' OR '.join(senders)})").execute()
    out = []
    for t in res.get("threads", []):
        full = gmail().users().threads().get(userId="me", id=t["id"], format="full").execute()
        out.append([simplify(m) for m in full["messages"] if "DRAFT" not in m.get("labelIds", [])])
    return out


def thread(thread_id: str) -> list[dict]:
    full = gmail().users().threads().get(userId="me", id=thread_id, format="full").execute()
    return [simplify(m) for m in full["messages"] if "DRAFT" not in m.get("labelIds", [])]


def create_draft(reply_to: dict, body: str) -> str:
    msg = EmailMessage()
    msg["To"] = reply_to["from"]
    subject = reply_to["subject"]
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    if reply_to["message_id"]:
        msg["In-Reply-To"] = reply_to["message_id"]
        msg["References"] = reply_to["message_id"]
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = gmail().users().drafts().create(userId="me", body={"message": {"raw": raw, "threadId": reply_to["thread_id"]}}).execute()
    return draft["id"]


def draft_exists(draft_id: str) -> bool:
    try:
        gmail().users().drafts().get(userId="me", id=draft_id, format="minimal").execute()
        return True
    except Exception:
        return False


# ---- Calendar ----

def events_between(start: datetime, end: datetime) -> list[dict]:
    res = calendar().events().list(
        calendarId="primary", timeMin=start.isoformat(), timeMax=end.isoformat(), singleEvents=True, orderBy="startTime"
    ).execute()
    out = []
    for e in res.get("items", []):
        if "dateTime" not in e.get("start", {}) or e.get("transparency") == "transparent":
            continue  # all-day markers and "free" events do not block time
        out.append({
            "id": e["id"],
            "summary": e.get("summary", "(busy)"),
            "start": datetime.fromisoformat(e["start"]["dateTime"]).astimezone(TZ),
            "end": datetime.fromisoformat(e["end"]["dateTime"]).astimezone(TZ),
            "attendees": [a.get("email", "").lower() for a in e.get("attendees", [])],
        })
    return out


def move_event(event_id: str, new_start: datetime, new_end: datetime) -> dict:
    body = {"start": {"dateTime": new_start.isoformat()}, "end": {"dateTime": new_end.isoformat()}}
    return calendar().events().patch(calendarId="primary", eventId=event_id, body=body, sendUpdates="all").execute()


def create_event(summary: str, start: datetime, minutes: int, attendee: str | None = None) -> dict:
    body = {"summary": summary, "start": {"dateTime": start.isoformat()}, "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()}}
    if attendee:
        body["attendees"] = [{"email": attendee}]
    return calendar().events().insert(calendarId="primary", body=body, sendUpdates="all").execute()
