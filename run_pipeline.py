"""End-to-end driver: acquire -> extract -> restore/colorize -> recompile."""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import time

from pipeline import acquire, compile_pdf, extract, restore

ROOT = pathlib.Path(__file__).parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--scale", type=float, default=3.0, help="100 DPI scan -> 300 DPI output")
    parser.add_argument("--colors", type=int, default=64, help="PDF palette size; 0 keeps full RGB")
    parser.add_argument("--out", type=pathlib.Path, default=ROOT / "Codex_Rohonczi_Restored.pdf")
    parser.add_argument("--skip-download", action="store_true")
    args = parser.parse_args()

    raw, pages, processed = ROOT / "data/raw", ROOT / "data/pages", ROOT / "data/processed"
    started = time.time()

    print("[1/4] acquisition")
    if args.skip_download and any(raw.glob("*.pdf")):
        print("  reusing existing downloads")
    else:
        for document in acquire.describe_documents():
            print(f"  repository document: {document['filename']} [{document['security']}] {document['description']}")
        for url in acquire.discover_pdf_links():
            acquire.download(url, raw)

    print("[2/4] page extraction")
    for pdf in sorted(raw.glob("*.pdf")):
        extract.extract(pdf, pages, dpi=None, prefix=pdf.stem)

    print("[3/4] denoise / isolate / colorize")
    page_files = sorted(pages.glob("*.png"))
    asyncio.run(restore.process_all(page_files, processed, args.workers, args.scale))

    print("[4/4] recompilation")
    compile_pdf.compile_pdf(sorted(processed.glob("*.png")), args.out, dpi=round(100 * args.scale), colors=args.colors)

    print(f"done in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
