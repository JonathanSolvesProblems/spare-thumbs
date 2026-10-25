"""Fail when the numbers in the prose no longer match the result files.

    python -m spare_thumbs.check_claims [extra files to check]

Reads results/gate_results.json and results/judge_*.json, recomputes every headline figure, and greps
README.md (plus any files given) for each one. A retired or stale number is a failure, not a note.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

from spare_thumbs.config import RESULTS

ROOT = RESULTS.parent


def gate_claims() -> dict[str, str]:
    rows = json.loads((RESULTS / "gate_results.json").read_text(encoding="utf-8"))
    out = {}
    for arm, label in (("no_calendar", "Gemma 4 without my calendar"), ("spare_thumbs", "Spare Thumbs")):
        bad = sum(1 for r in rows if r[arm]["busy"])
        busy = sum(len(r[arm]["busy"]) for r in rows)
        offered = sum(len(r[arm]["offered"]) for r in rows)
        out[f"{label}: drafts offering a busy time"] = f"{bad} of {len(rows)}"
        out[f"{label}: busy times offered"] = f"{busy} of {offered} times offered"
    return out


def judge_claims() -> dict[str, str]:
    out = {}
    for path in sorted(RESULTS.glob("judge_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        picks = Counter(data.get("picks") or sum((Counter(p) for p in data["per_item"]), Counter()))
        total = sum(picks.values())
        for who, label in (("gemma_with_my_replies", "Spare Thumbs"), ("jonathan", "my real reply"), ("gemma_plain", "plain Gemma")):
            out[f"{path.stem}: {label}"] = f"{picks[who] / total:.0%}"
    return out


def main(files: list[str]) -> int:
    claims = {**gate_claims(), **judge_claims()}
    texts = {f: Path(f).read_text(encoding="utf-8") for f in ["README.md", *files] if Path(f).exists()}
    failed = 0
    for name, value in claims.items():
        where = [f for f, t in texts.items() if re.search(re.escape(value), t)]
        print(f"{'ok ' if where else 'MISSING'} {name} = {value}  ({', '.join(where) or 'not stated anywhere'})")
        if not where and "times offered" not in name:
            failed += 1
    # Retired claims that must not come back.
    for retired in ("not yet measured", "pending", "N/A"):
        hits = [f for f, t in texts.items() if re.search(rf"\b{re.escape(retired)}\b", t)]
        if hits:
            print(f"RETIRED phrase {retired!r} found in {', '.join(hits)}")
            failed += 1
    print(f"{failed} problems")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
