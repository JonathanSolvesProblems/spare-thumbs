"""Gallery previews for the submission: 8 images at 3:2, one caption each, 140 max.

    python scripts/preview.py

Stills come from the redacted b-roll (broll/_stills), letterboxed to 3:2 in their own background
colour. The hero card is drawn here. The character count is printed to the terminal only, never
written next to a caption.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "broll" / "preview"
STILLS = ROOT / "broll" / "_stills"
W, H = 1500, 1000
BG, ACCENT, TEXT, TEXT2 = "#15120E", "#E8A64A", "#F4EFE7", "#9C9388"
FONTS = "C:/Windows/Fonts/"

# Story order follows the demo video. ("hero", None) is drawn below; the rest are still names.
SHOTS = [
    ("1-spare-thumbs", None),
    ("2-gemma-decides", "term_decision"),
    ("3-draft-in-gmail", "gmail_draft"),
    ("4-my-own-replies", "term_voice"),
    ("5-client-confirms", "term_move"),
    ("6-calendar-moved", "cal_friday"),
    ("7-the-gate", "term_block_take1"),
    ("8-seven-of-ten", "results"),
]

CAPTIONS = {
    "1-spare-thumbs": "Spare Thumbs: Gemma 4 on my laptop answers \"can we move the meeting?\" in my words, from my real Google Calendar.",
    "2-gemma-decides": "Live run: Gemma 4 finds the meeting, checks Friday, sees 10h is booked, and offers 11h or 14h, which are actually free.",
    "3-draft-in-gmail": "The reply lands as a draft in my Gmail thread, written the way I write. Nothing reaches the client until I press send.",
    "4-my-own-replies": "EmbeddingGemma pulls my own replies to the most similar messages, including one I sent through it earlier. No fine-tune.",
    "5-client-confirms": "Sam says 11h works. Gemma 4 calls move_event on its own, then drafts the confirmation.",
    "6-calendar-moved": "My real Google Calendar after the run: the website review now sits on Friday at 11h, moved there by Gemma 4.",
    "7-the-gate": "The gate: Gemma offered 9h, the code saw it overlaps a real 9:30 event, blocked the draft and sent it back to retry.",
    "8-seven-of-ten": "Ten requests on a busy week: Gemma 4 without my calendar offered a booked time in 7 drafts. Spare Thumbs: 0.",
}

# The first take's terminal frame predates the clip redaction, so its address line is pixelated here.
PIXELATE = {"term_block_take1": [(478, 40, 556, 50), (1118, 40, 500, 50)]}


def font(size, name="segoeuib.ttf"):
    return ImageFont.truetype(FONTS + name, size)


def centered(d, y, text, f, fill):
    w = d.textbbox((0, 0), text, font=f)[2]
    d.text(((W - w) // 2, y), text, font=f, fill=fill)
    return y + d.textbbox((0, 0), text, font=f)[3]


def hero() -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    y = centered(d, 250, "Spare Thumbs", font(150), TEXT)
    d.rectangle(((W - 220) // 2, y + 40, (W + 220) // 2, y + 47), fill=ACCENT)
    y = centered(d, y + 90, "Clients move meetings at night.", font(54, "segoeui.ttf"), TEXT)
    y = centered(d, y + 18, "Gemma 4 answers in my words, from my real calendar,", font(44, "segoeui.ttf"), TEXT2)
    y = centered(d, y + 12, "and never offers a time I'm already booked.", font(44, "segoeui.ttf"), TEXT2)
    centered(d, y + 90, "Gemma 4  +  EmbeddingGemma, running locally on Ollama", font(34, "segoeui.ttf"), ACCENT)
    return im


def letterbox(name: str) -> Image.Image:
    im = Image.open(STILLS / f"{name}.png").convert("RGB")
    for x, y, w, h in PIXELATE.get(name, []):
        box = im.crop((x, y, x + w, y + h))
        im.paste(box.resize((w // 14, max(2, h // 14))).resize((w, h), Image.NEAREST), (x, y))
    bg = im.getpixel((2, im.height - 3))
    target_h = im.width * 2 // 3
    canvas = Image.new("RGB", (im.width, target_h), bg)
    canvas.paste(im, (0, (target_h - im.height) // 2))
    return canvas


for k, c in CAPTIONS.items():
    assert len(c) <= 140, f"{k}: {len(c)} characters, limit is 140"
assert [n for n, _ in SHOTS] == list(CAPTIONS)
assert len(SHOTS) <= 8

OUT.mkdir(parents=True, exist_ok=True)
for name, src in SHOTS:
    (hero() if src is None else letterbox(src)).save(OUT / f"{name}.png")

lines = ["# Image gallery, upload in this order", "", "One caption per image. Copy the block contents only.", ""]
for name, _ in SHOTS:
    lines += [f"## {name}.png", "", "```", CAPTIONS[name], "```", ""]
(OUT / "captions.md").write_text("\n".join(lines), encoding="utf-8")

for name, _ in SHOTS:
    f = OUT / f"{name}.png"
    im = Image.open(f)
    ok = "ok " if abs(im.width / im.height - 1.5) < 0.01 and f.stat().st_size < 5_000_000 else "BAD"
    print(f"  {ok} {f.name:<26} {im.width}x{im.height}  {f.stat().st_size // 1024:>4} KB   caption {len(CAPTIONS[name]):>3}/140")
print(f"\n{len(SHOTS)} images + captions.md in {OUT.relative_to(ROOT)}")

sheet = Image.new("RGB", (960 * 2, 640 * 4), "#000")
for i, (name, _) in enumerate(SHOTS):
    sheet.paste(Image.open(OUT / f"{name}.png").resize((960, 640)), ((i % 2) * 960, (i // 2) * 640))
sheet.save(ROOT / "tmp" / "preview_sheet.png")
