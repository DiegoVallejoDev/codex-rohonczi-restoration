"""Step 4 - recompile the processed pages into a single sequential PDF."""

from __future__ import annotations

import argparse
import io
import pathlib

import img2pdf
from PIL import Image

TITLE = "Codex Rohonczi - restored and synthetically colorized"


def encode(path: pathlib.Path, colors: int, jpeg_quality: int | None, scale: float = 1.0) -> bytes:
    """Re-encode one page for embedding.

    With ``jpeg_quality=None`` the pixel data stays lossless: palette reduction is a close fit
    for the synthesised two-tone artwork and compresses far better than full RGB. Passing a
    JPEG quality builds the smaller distribution copy instead.
    """
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        if scale != 1.0:
            rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.LANCZOS)
        buffer = io.BytesIO()
        if jpeg_quality is not None:
            rgb.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True, progressive=True)
        else:
            # The duotone pages hold few distinct colours, so an undithered palette is a near
            # exact fit and compresses far better than RGB; dithering would only add noise.
            payload = rgb.quantize(colors=colors, method=Image.MEDIANCUT, dither=Image.NONE) if colors else rgb
            payload.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def compile_pdf(
    pages: list[pathlib.Path],
    destination: pathlib.Path,
    dpi: int,
    colors: int,
    jpeg_quality: int | None = None,
    scale: float = 1.0,
) -> pathlib.Path:
    layout = img2pdf.get_layout_fun(fit=img2pdf.FitMode.into)
    payloads = []
    for index, page in enumerate(pages, start=1):
        payloads.append(encode(page, colors, jpeg_quality, scale))
        if index % 25 == 0 or index == len(pages):
            print(f"  prepared {index}/{len(pages)} pages", flush=True)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        img2pdf.convert(payloads, outputstream=handle, layout_fun=layout, title=TITLE, dpi=dpi)
    print(f"  wrote {destination} ({destination.stat().st_size / 1e6:.1f} MB, {len(pages)} pages)")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed", type=pathlib.Path, default=pathlib.Path("data/processed"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("Codex_Rohonczi_Restored.pdf"))
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--colors", type=int, default=32, help="palette size; 0 keeps full RGB")
    parser.add_argument("--jpeg-quality", type=int, default=None, help="build a lossy distribution copy instead")
    parser.add_argument("--scale", type=float, default=1.0, help="resample pages before embedding")
    args = parser.parse_args()

    pages = sorted(args.processed.glob("*.png"))
    if not pages:
        raise SystemExit(f"no processed pages found in {args.processed}")
    compile_pdf(pages, args.out, round(args.dpi * args.scale), args.colors, args.jpeg_quality, args.scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
