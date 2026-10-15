"""One-time script: generates the three persona icons into web/icons/. Not needed at runtime by any other script."""

from pathlib import Path

from PIL import Image, ImageDraw

ICONS_DIR = Path(__file__).resolve().parent.parent / "web" / "icons"
SIZE = 128


def _blank(bg):
    return Image.new("RGB", (SIZE, SIZE), bg)


def draw_technical():
    img = _blank((16, 42, 58))
    draw = ImageDraw.Draw(img)
    bars = [(20, 90, 32, 40), (44, 90, 56, 60), (68, 90, 80, 25), (92, 90, 104, 70)]
    for x0, y0, x1, y1 in bars:
        draw.rectangle([x0, y1, x1, y0], fill=(64, 196, 212))
    draw.line([(16, 100), (40, 55), (64, 70), (88, 20), (112, 35)], fill=(255, 255, 255), width=4)
    return img


def draw_fundamental():
    img = _blank((30, 46, 24))
    draw = ImageDraw.Draw(img)
    gold = (212, 175, 55)
    draw.line([(64, 20), (64, 50)], fill=gold, width=5)
    draw.line([(24, 50), (104, 50)], fill=gold, width=5)
    draw.line([(24, 50), (12, 90)], fill=gold, width=4)
    draw.line([(24, 50), (36, 90)], fill=gold, width=4)
    draw.arc([4, 70, 44, 100], start=0, end=180, fill=gold, width=4)
    draw.line([(104, 50), (92, 90)], fill=gold, width=4)
    draw.line([(104, 50), (116, 90)], fill=gold, width=4)
    draw.arc([84, 70, 124, 100], start=0, end=180, fill=gold, width=4)
    draw.polygon([(54, 108), (74, 108), (64, 118)], fill=gold)
    return img


def draw_retail():
    img = _blank((58, 20, 16))
    draw = ImageDraw.Draw(img)
    orange = (255, 140, 60)
    draw.rounded_rectangle([16, 24, 112, 84], radius=16, outline=orange, width=5)
    draw.polygon([(36, 84), (36, 104), (56, 84)], fill=orange)
    draw.polygon(
        [(78, 40), (70, 64), (82, 60), (74, 92), (96, 56), (84, 58)],
        fill=(255, 196, 80),
    )
    return img


def main():
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    draw_technical().save(ICONS_DIR / "technical.png")
    draw_fundamental().save(ICONS_DIR / "fundamental.png")
    draw_retail().save(ICONS_DIR / "retail.png")
    print(f"Wrote 3 icons to {ICONS_DIR}")


if __name__ == "__main__":
    main()
