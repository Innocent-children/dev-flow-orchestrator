"""Generate the README walkthrough GIF.

This is a documentation-only helper. Install Pillow in a development
environment, then run ``python docs/assets/generate_demo.py``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1200
HEIGHT = 675
BACKGROUND = "#0b1020"
PANEL = "#121a2f"
PANEL_ALT = "#18233d"
TEXT = "#edf2ff"
MUTED = "#9ba9c7"
BLUE = "#68a7ff"
GREEN = "#53d39b"
AMBER = "#f4bf75"
BORDER = "#2b3b62"


def _font(size: int, *, mono: bool = False, bold: bool = False) -> ImageFont.FreeTypeFont:
    windows = Path("C:/Windows/Fonts")
    candidates = (
        ([windows / "CascadiaMono.ttf", windows / "consola.ttf"] if mono else [])
        + ([windows / "segoeuib.ttf"] if bold else [windows / "segoeui.ttf"])
        + [
            Path("/System/Library/Fonts/SFNSMono.ttf") if mono else Path("/System/Library/Fonts/SFNS.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")
            if mono
            else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


TITLE = _font(34, bold=True)
BODY = _font(22)
SMALL = _font(17)
MONO = _font(20, mono=True)
MONO_SMALL = _font(16, mono=True)


STEPS = [
    ("1", "Start", "Bind one requirement to API + Web"),
    ("2", "Contract", "Keep acceptance criteria explicit"),
    ("3", "Implement", "Advance one authoritative action"),
    ("4", "Interrupt", "Close Codex without losing state"),
    ("5", "Resume", "Continue by task ID in a new session"),
    ("6", "Verify", "Prove both repositories + integration"),
    ("7", "Deliver", "Generate the final Delivery Dossier"),
]


TERMINAL = [
    [
        ("$ ", MUTED),
        ("Use $follow-dev-flow for profile editing", TEXT),
        ("  repositories: ./api, ./web", MUTED),
    ],
    [
        ("task  7f3a9c", BLUE),
        ("flow  feature", MUTED),
        ("C1    Users can update display name", TEXT),
        ("C2    Invalid names are rejected", TEXT),
        ("repos api + web (immutable set)", MUTED),
    ],
    [
        ("current action  implementation.record", BLUE),
        ("api  PATCH /profile + validation", TEXT),
        ("web  profile form + error state", TEXT),
        ("state saved outside both repositories", GREEN),
    ],
    [
        ("Codex session closed", AMBER),
        ("", TEXT),
        ("Task 7f3a9c remains ACTIVE", TEXT),
        ("contract, decisions and evidence preserved", MUTED),
    ],
    [
        ("$ ", MUTED),
        ("Use $follow-dev-flow to resume 7f3a9c", TEXT),
        ("", TEXT),
        ("restored  contract revision 1", GREEN),
        ("next      verification.record", BLUE),
    ],
    [
        ("api tests          PASS", GREEN),
        ("web tests          PASS", GREEN),
        ("integration        PASS", GREEN),
        ("C1 proven | C2 proven", TEXT),
        ("independent review APPROVED", GREEN),
    ],
    [
        ("status  DONE", GREEN),
        ("", TEXT),
        ("Delivery Dossier 0.2.0", BLUE),
        ("criteria 2/2 | repositories 2/2", TEXT),
        ("handoff: ready for operator-owned PR", MUTED),
    ],
]


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill: str, radius: int = 16) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=BORDER, width=2)


def _frame(active: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image)

    draw.text((54, 35), "Dev Flow keeps Codex delivery on track", font=TITLE, fill=TEXT)
    draw.text((55, 82), "Two repositories. Two Codex sessions. One verifiable task.", font=BODY, fill=MUTED)

    _rounded(draw, (48, 132, 382, 613), PANEL)
    draw.text((75, 158), "RESUMABLE WORKFLOW", font=SMALL, fill=BLUE)
    y = 205
    for index, (_number, label, description) in enumerate(STEPS):
        is_done = index < active
        is_active = index == active
        color = GREEN if is_done else BLUE if is_active else MUTED
        fill = "#1c3151" if is_active else PANEL
        draw.rounded_rectangle((70, y - 8, 359, y + 44), radius=10, fill=fill)
        draw.ellipse((77, y, 101, y + 24), fill=color)
        mark = "ok" if is_done else str(index + 1)
        mark_box = draw.textbbox((0, 0), mark, font=MONO_SMALL)
        draw.text((89 - (mark_box[2] - mark_box[0]) / 2, y + 2), mark, font=MONO_SMALL, fill=BACKGROUND)
        draw.text((113, y - 2), label, font=SMALL, fill=TEXT if (is_done or is_active) else MUTED)
        draw.text((113, y + 20), description, font=_font(12), fill=MUTED)
        if index < len(STEPS) - 1:
            draw.line((89, y + 25, 89, y + 53), fill=GREEN if is_done else BORDER, width=2)
        y += 56

    _rounded(draw, (414, 132, 1152, 500), PANEL)
    draw.rounded_rectangle((414, 132, 1152, 177), radius=16, fill=PANEL_ALT)
    draw.rectangle((414, 160, 1152, 177), fill=PANEL_ALT)
    for x, color in ((439, "#ff6b6b"), (465, AMBER), (491, GREEN)):
        draw.ellipse((x, 149, x + 13, 162), fill=color)
    draw.text((535, 145), "codex / dev-flow", font=MONO_SMALL, fill=MUTED)

    y = 208
    for line, color in TERMINAL[active]:
        draw.text((448, y), line, font=MONO, fill=color)
        y += 47

    _rounded(draw, (414, 526, 1152, 613), PANEL)
    repo_states = (
        ("api", GREEN if active >= 2 else BLUE),
        ("web", GREEN if active >= 2 else BLUE),
        ("task 7f3a9c", AMBER if active == 3 else GREEN if active >= 4 else BLUE),
    )
    x = 447
    for label, color in repo_states:
        width = int(draw.textlength(label, font=MONO_SMALL)) + 42
        draw.rounded_rectangle((x, 550, x + width, 586), radius=18, fill=PANEL_ALT, outline=color, width=2)
        draw.ellipse((x + 13, 563, x + 23, 573), fill=color)
        draw.text((x + 29, 558), label, font=MONO_SMALL, fill=TEXT)
        x += width + 18
    draw.text((900, 557), f"{active + 1} / {len(STEPS)}", font=MONO_SMALL, fill=MUTED)
    return image


def main() -> None:
    frames = [_frame(index) for index in range(len(STEPS))]
    output = Path(__file__).with_name("demo.gif")
    frames[0].save(
        output,
        save_all=True,
        append_images=frames[1:],
        duration=[1400, 1500, 1700, 1700, 1700, 1700, 2500],
        loop=0,
        optimize=True,
    )
    print(output)


if __name__ == "__main__":
    main()
