"""Graphic templates, drawn with Pillow.

Everything on the canvas is generated: type, colour, geometry. We do not
composite match photography or club crests, because that imagery is licensed
and reposting it is how accounts get struck. If you later license a photo
library, add it as an optional background layer here.

Three templates, matching how the big accounts actually structure a feed:
  score_card    -- a result, numbers dominant
  transfer_card -- a move, player name dominant, status strip
  quote_card    -- a talking point, text-led
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import ROOT, load, out_dir
from ..models import Post, Story, Tier

log = logging.getLogger(__name__)

_font_warned = False


def render(post: Post, *, size: str = "story") -> Path:
    """Draw the post's template and return the PNG path."""
    brand = load("brand")
    w, h = brand["canvas"][size]

    img = Image.new("RGB", (w, h), _rgb(brand["palette"]["bg"]))
    draw = ImageDraw.Draw(img)

    _backdrop(draw, w, h, brand)

    template = {
        "score_card": _score_card,
        "transfer_card": _transfer_card,
        "quote_card": _quote_card,
    }.get(post.template, _transfer_card)

    template(draw, w, h, brand, post)
    _footer(draw, w, h, brand, post.story)

    path = out_dir() / f"{post.story.fingerprint}_{size}.png"
    img.save(path, "PNG", optimize=True)
    log.info("rendered %s -> %s", post.template, path.name)
    return path


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------

def _score_card(draw, w, h, brand, post: Post) -> None:
    pal = brand["palette"]
    d = post.story.data
    cy = int(h * 0.42)

    _text(draw, w // 2, int(h * 0.18), d.get("competition", "FULL TIME").upper(),
          _font(brand, "bold", 34), _rgb(pal["accent"]), anchor="mm", tracking=6)

    score = f"{d.get('home_goals', 0)} - {d.get('away_goals', 0)}"
    _text(draw, w // 2, cy, score, _font(brand, "heavy", 190),
          _rgb(pal["ink"]), anchor="mm")

    _text(draw, w // 2, cy - 150, _upper(d.get("home", "")),
          _font(brand, "bold", 58), _rgb(pal["ink"]), anchor="mm")
    _text(draw, w // 2, cy + 150, _upper(d.get("away", "")),
          _font(brand, "bold", 58), _rgb(pal["ink"]), anchor="mm")

    _wrapped(draw, w // 2, int(h * 0.70), post.story.data.get("headline", ""),
             _font(brand, "regular", 40), _rgb(pal["ink_muted"]),
             max_width=int(w * 0.8), anchor="ma")


def _transfer_card(draw, w, h, brand, post: Post) -> None:
    """Headline block, accent rule, subhead -- vertically centred as a group.

    Centring the group rather than pinning each element to a fixed fraction
    keeps a two-line headline and a five-line headline both looking composed
    instead of leaving a hole at the bottom of the shorter one.
    """
    pal = brand["palette"]
    copy = post.story.data
    x, max_w = int(w * 0.08), int(w * 0.84)

    _status_strip(draw, w, h, brand, post.story)

    head_font = _font(brand, "heavy", 96)
    sub_font = _font(brand, "regular", 44)
    gap, rule_h, rule_gap = 14, 8, 44

    head_lines = _wrap_lines(
        draw, copy.get("headline", post.story.title).upper(), head_font, max_w
    )
    sub_lines = _wrap_lines(draw, copy.get("subhead", ""), sub_font, max_w)

    head_lh = _line_height(draw, head_font) + gap
    sub_lh = _line_height(draw, sub_font) + 10

    block_h = (
        len(head_lines) * head_lh
        + rule_gap + rule_h + rule_gap
        + len(sub_lines) * sub_lh
    )
    # Bias slightly above true centre -- the status pill occupies the top and
    # the handle sits at the bottom, so optical centre is higher than 50%.
    y = max(int(h * 0.26), (h - block_h) // 2 - int(h * 0.04))

    y = _draw_lines(draw, x, y, head_lines, head_font, _rgb(pal["ink"]), head_lh)

    y += rule_gap
    draw.rectangle([x, y, x + 140, y + rule_h], fill=_rgb(pal["accent"]))
    y += rule_h + rule_gap

    _draw_lines(draw, x, y, sub_lines, sub_font, _rgb(pal["ink_muted"]), sub_lh)


def _quote_card(draw, w, h, brand, post: Post) -> None:
    pal = brand["palette"]
    copy = post.story.data

    _text(draw, int(w * 0.08), int(h * 0.20), "“",
          _font(brand, "heavy", 220), _rgb(pal["accent"]), anchor="la")

    _wrapped(draw, int(w * 0.08), int(h * 0.36),
             copy.get("headline", post.story.title),
             _font(brand, "bold", 78), _rgb(pal["ink"]),
             max_width=int(w * 0.84), anchor="la", line_gap=16)

    _wrapped(draw, int(w * 0.08), int(h * 0.70), copy.get("subhead", ""),
             _font(brand, "regular", 40), _rgb(pal["ink_muted"]),
             max_width=int(w * 0.84), anchor="la")


# --------------------------------------------------------------------------
# Shared furniture
# --------------------------------------------------------------------------

def _backdrop(draw, w, h, brand) -> None:
    """Vertical wash plus a corner block -- cheap depth, no assets needed."""
    pal = brand["palette"]
    top, bottom = _rgb(pal["bg"]), _rgb(pal["bg_alt"])

    for y in range(h):
        t = y / max(1, h - 1)
        draw.line(
            [(0, y), (w, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
        )

    draw.polygon(
        [(w, 0), (w, int(h * 0.22)), (int(w * 0.55), 0)],
        fill=_rgb(pal["rail"]),
    )


def _status_strip(draw, w, h, brand, story: Story) -> None:
    """The word at the top that sets expectations: CONFIRMED vs RUMOUR."""
    pal = brand["palette"]
    label, colour = {
        Tier.CONFIRMED: ("CONFIRMED", pal["accent"]),
        Tier.STRONG: ("REPORTED", pal["ink_muted"]),
        Tier.SPECULATIVE: ("RUMOUR", pal["accent_alt"]),
    }[Tier(story.tier)]

    x, y = int(w * 0.08), int(h * 0.14)
    font = _font(brand, "bold", 34)
    tracking = 4
    # Measure with tracking included, or the pill clips its final letter.
    tw = _tracked_width(draw, label, font, tracking)

    draw.rounded_rectangle(
        [x, y, x + tw + 56, y + 66], radius=33, fill=_rgb(colour)
    )
    _text(draw, x + 28, y + 14, label, font, _rgb(pal["bg"]), anchor="la",
          tracking=tracking)


def _footer(draw, w, h, brand, story: Story) -> None:
    pal = brand["palette"]
    _text(draw, int(w * 0.08), int(h * 0.90), brand["handle"],
          _font(brand, "bold", 34), _rgb(pal["ink"]), anchor="la")
    _text(draw, int(w * 0.92), int(h * 0.90), f"via {story.source}",
          _font(brand, "regular", 28), _rgb(pal["ink_muted"]), anchor="ra")


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

# Scalable fallbacks, in preference order. PIL's built-in default is a small
# bitmap face -- at 190px it renders as unusable mush, so we reach for any
# system TTF before accepting it.
_SYSTEM_FONTS = {
    "heavy": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


def _font(brand: dict, weight: str, size: int) -> ImageFont.ImageFont:
    global _font_warned

    rel = brand["fonts"].get(weight)
    if rel and (ROOT / rel).exists():
        return ImageFont.truetype(str(ROOT / rel), size)

    if not _font_warned:
        log.warning(
            "brand fonts missing (looked for %s). Falling back to a system "
            "face -- legible but off-brand. Drop TTFs into assets/fonts/ "
            "before publishing.", rel,
        )
        _font_warned = True

    for candidate in _SYSTEM_FONTS.get(weight, []):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has no size argument
        return ImageFont.load_default()


def _text(draw, x, y, text, font, fill, *, anchor="la", tracking=0) -> None:
    """Draw a single line, optionally letter-spaced.

    Pillow has no tracking support, so wide-set label text is drawn glyph by
    glyph. Only used on short strings -- it is too slow for body copy.
    """
    if not text:
        return

    if not tracking:
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)
        return

    total = sum(_width(draw, ch, font) + tracking for ch in text) - tracking
    if anchor[0] == "m":
        x -= total // 2
    elif anchor[0] == "r":
        x -= total

    vertical = anchor[1] if len(anchor) > 1 else "a"
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill, anchor=f"l{vertical}")
        x += _width(draw, ch, font) + tracking


def _wrap_lines(draw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap. Pillow has no width-aware multiline layout."""
    if not text:
        return []

    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if _width(draw, trial, font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_lines(draw, x, y, lines, font, fill, line_h, anchor="la") -> int:
    """Draw pre-wrapped lines; return the y just past the last one."""
    for i, line in enumerate(lines):
        draw.text((x, y + i * line_h), line, font=font, fill=fill, anchor=anchor)
    return y + len(lines) * line_h


def _wrapped(draw, x, y, text, font, fill, *, max_width, anchor="la",
             line_gap=10) -> None:
    lines = _wrap_lines(draw, text, font, max_width)
    _draw_lines(draw, x, y, lines, font, fill,
                _line_height(draw, font) + line_gap, anchor)


def _width(draw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _tracked_width(draw, text: str, font, tracking: int) -> int:
    if not text:
        return 0
    return sum(_width(draw, ch, font) + tracking for ch in text) - tracking


def _line_height(draw, font) -> int:
    """Height of a line with ascenders and descenders, independent of content.

    Measuring the actual string makes lines without descenders sit tighter
    than lines with them, which reads as uneven leading.
    """
    box = draw.textbbox((0, 0), "AgjQy", font=font)
    return box[3] - box[1]


def _upper(text: str) -> str:
    return (text or "").upper()


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
