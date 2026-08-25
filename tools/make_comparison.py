"""Build before/after comparison figures for the README.

Pairs a native-resolution source page from ``data/pages`` with its restored counterpart in
``data/processed``: a full spread side by side, and a 1:1 crop of the same region in both.
"""

from __future__ import annotations

import argparse
import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
LABEL_HEIGHT = 46
GUTTER = 14
BACKDROP = (21, 19, 18)
LABEL_FG = (232, 222, 205)
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def load_font(size: int) -> ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if pathlib.Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def side_by_side(left: Image.Image, right: Image.Image, labels: tuple[str, str]) -> Image.Image:
    height = max(left.height, right.height)
    left = left.convert("RGB")
    right = right.convert("RGB")
    canvas = Image.new("RGB", (left.width + GUTTER + right.width, height + LABEL_HEIGHT), BACKDROP)
    canvas.paste(left, (0, LABEL_HEIGHT))
    canvas.paste(right, (left.width + GUTTER, LABEL_HEIGHT))

    draw = ImageDraw.Draw(canvas)
    font = load_font(28)
    for text, x_start, width in ((labels[0], 0, left.width), (labels[1], left.width + GUTTER, right.width)):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(
            (x_start + (width - (box[2] - box[0])) // 2, (LABEL_HEIGHT - (box[3] - box[1])) // 2 - box[1]),
            text,
            fill=LABEL_FG,
            font=font,
        )
    return canvas


def report(path: pathlib.Path) -> None:
    name = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"{name} {path.stat().st_size / 1e6:.1f} MB")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", default="Rohonci_Codex_K_114cs_0020.png")
    parser.add_argument("--pages", type=pathlib.Path, default=ROOT / "data/pages")
    parser.add_argument("--processed", type=pathlib.Path, default=ROOT / "data/processed")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "samples")
    parser.add_argument("--spread-width", type=int, default=1100, help="width of each panel in the spread figure")
    parser.add_argument("--crop", type=int, nargs=4, default=(1180, 300, 1900, 780), help="restored-space crop box")
    parser.add_argument("--suffix", default="", help="appended to the output filenames")
    parser.add_argument("--spread-only", action="store_true")
    parser.add_argument(
        "--labels",
        nargs=2,
        default=("Source scan (public ~100 DPI monochrome)", "Restored + synthetically colorized"),
    )
    args = parser.parse_args()

    source = Image.open(args.pages / args.page)
    restored = Image.open(args.processed / args.page)
    scale = restored.width / source.width
    args.out.mkdir(parents=True, exist_ok=True)

    # Full spread: the source is upscaled to the restored size so both panels show the same field
    # of view at the same display size, isolating the tonal change rather than the resample.
    panel = (args.spread_width, round(args.spread_width * restored.height / restored.width))
    spread = side_by_side(
        source.resize(panel, Image.LANCZOS),
        restored.resize(panel, Image.LANCZOS),
        tuple(args.labels),
    )
    spread_path = args.out / f"comparison_spread{args.suffix}.png"
    spread.save(spread_path, optimize=True)
    if args.spread_only:
        report(spread_path)
        return 0

    # Detail: crop the restored page, and the matching region of the source scaled 1:1 to it.
    x0, y0, x1, y1 = args.crop
    detail = side_by_side(
        source.crop((round(x0 / scale), round(y0 / scale), round(x1 / scale), round(y1 / scale))).resize(
            (x1 - x0, y1 - y0), Image.LANCZOS
        ),
        restored.crop((x0, y0, x1, y1)),
        ("Source detail", "Restored detail"),
    )
    detail_path = args.out / f"comparison_detail{args.suffix}.png"
    detail.save(detail_path, optimize=True)

    for path in (spread_path, detail_path):
        report(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
