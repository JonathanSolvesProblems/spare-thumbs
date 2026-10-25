# Results

The numbers in the main README come from these files.

- `gate_results.json`: `python -m spare_thumbs.gate_test`, run on 2026-10-24. Ten reschedule requests against an in-memory busy week, each answered by Gemma 4 with my voice examples on, once with the calendar tools and the gate (Spare Thumbs) and once without. `busy` lists every offered time that overlaps the calendar. The test client's first name in the saved drafts was replaced with Sam after the run; nothing else changed.
- `judge_qwen3.5_4b.json`: `python -m spare_thumbs.judge`. Qwen 3.5 4B picks which of three replies I wrote, 15 held-out messages, each asked in all 6 option orders. Picks: Spare Thumbs 50, my real reply 30, plain Gemma 10.
- `judge_qwen2.5vl_7b.json`: the same test with Qwen 2.5 7B as the judge. Picks: plain Gemma 48, Spare Thumbs 32, my real reply 10. It prefers the AI reply over my own, so it cannot recognise my writing; reported for completeness.

The blind items themselves (my messages and replies) are private and not in the repo.
