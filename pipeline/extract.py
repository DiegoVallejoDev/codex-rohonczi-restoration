"""Step 2 - render every page of the acquired PDFs to lossless PNG."""

from __future__ import annotations

import argparse
import pathlib

import pymupdf


def native_dpi(page: pymupdf.Page) -> float | None:
    """Effective DPI of the largest image embedded in a page, if any."""
    best = None
    for image in page.get_images(full=True):
        width, height = image[2], image[3]
        if page.rect.width and page.rect.height:
            dpi = max(width / (page.rect.width / 72.0), height / (page.rect.height / 72.0))
            best = dpi if best is None else max(best, dpi)
    return best


def extract(pdf_path: pathlib.Path, out_dir: pathlib.Path, dpi: int | None, prefix: str) -> list[pathlib.Path]:
    """Render pages to PNG. ``dpi=None`` keeps the native scan resolution of each page.

    The public MTAK copy is a ~100 DPI microfilm scan, so rendering it at 300 DPI adds no
    detail and blurs strokes before denoising. Native extraction keeps the cleanup honest;
    the 300 DPI upsample happens once, on the isolated ink mask, in ``restore.py``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open(pdf_path)
    written: list[pathlib.Path] = []

    for index, page in enumerate(document, start=1):
        page_dpi = dpi or round(native_dpi(page) or 300)
        pixmap = page.get_pixmap(dpi=page_dpi, colorspace=pymupdf.csGRAY)
        destination = out_dir / f"{prefix}_{index:04d}.png"
        pixmap.save(destination)
        written.append(destination)
    print(f"  {pdf_path.name}: {len(written)} page(s) -> {out_dir} (native ~{native_dpi(document[0]):.0f} DPI)")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=pathlib.Path, default=pathlib.Path("data/raw"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/pages"))
    parser.add_argument("--dpi", type=int, default=0, help="0 = native scan resolution")
    args = parser.parse_args()

    pdfs = sorted(args.raw.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"no PDFs found in {args.raw}")

    for pdf in pdfs:
        extract(pdf, args.out, args.dpi or None, prefix=pdf.stem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
