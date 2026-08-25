"""Step 3 - denoise, contrast isolation and synthetic chromatic mapping.

The public MTAK copy of the codex is a low-resolution monochrome microfilm scan, so colour is
not recoverable information: it is synthesised. Rather than replacing the leaf with generated
parchment, the scan's own luminance is mapped onto a parchment-to-ink colour ramp, so every
fibre, stain and stroke edge in the photograph survives into the colour version.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import pathlib

import cv2
import numpy as np

# Duotone ramp, shadows first: oxidised iron-gall ink -> warm mid-tones -> parchment highlight.
PARCHMENT_RAMP = ("#2A211F", "#3B2F2F", "#6E5A48", "#A78F70", "#D3BE9B", "#EBDBBE", "#F4E8D6")
LEATHER_RAMP = ("#0E0B09", "#2A1D14", "#4A3527", "#8A6C4C", "#D8C4A4")  # binding and cover shots
BACKDROP_HEX = "#151312"  # photographic studio backdrop around the folio


def hex_to_bgr(value: str) -> np.ndarray:
    value = value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return np.array([b, g, r], dtype=np.float32)


def denoise(gray: np.ndarray) -> np.ndarray:
    """Step A - Non-Local Means denoising, kept light so parchment texture is not smeared away."""
    return cv2.fastNlMeansDenoising(gray, None, h=4, templateWindowSize=7, searchWindowSize=21)


def isolate(gray: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Step B - flatten uneven illumination, CLAHE, then stretch the leaf's own tonal range."""
    blur_radius = max(31, (min(gray.shape[:2]) // 10) | 1)
    background = cv2.GaussianBlur(gray, (blur_radius, blur_radius), 0)
    flattened = cv2.divide(gray, background, scale=200)

    clahe = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(8, 8))
    equalized = clahe.apply(flattened).astype(np.float32)

    sample = equalized[mask > 0.5] if mask is not None and (mask > 0.5).any() else equalized
    low, high = np.percentile(sample, (1.0, 99.0))
    if high - low < 1.0:
        high = low + 1.0
    return np.clip((equalized - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)


def folio_mask(gray: np.ndarray) -> np.ndarray:
    """Soft mask of the folio itself, separating it from the dark photographic backdrop."""
    smoothed = cv2.GaussianBlur(gray, (0, 0), sigmaX=max(gray.shape[1] / 120.0, 1.0))
    _, binary = cv2.threshold(smoothed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    keep = np.zeros_like(binary)
    if count > 1:
        largest = stats[1:, cv2.CC_STAT_AREA].max()
        for label in range(1, count):
            if stats[label, cv2.CC_STAT_AREA] >= 0.25 * largest:  # keeps both leaves of a spread
                keep[labels == label] = 255

    if keep.any():
        # Fill interior holes so dark glyphs are never mistaken for backdrop.
        contours, _ = cv2.findContours(keep, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(keep, contours, -1, 255, thickness=cv2.FILLED)
    else:
        keep[:] = 255

    return cv2.GaussianBlur(keep.astype(np.float32) / 255.0, (0, 0), sigmaX=2.0)


def is_binding(gray: np.ndarray, folio: np.ndarray) -> bool:
    """Covers and spine shots are dark leather, not parchment, so they need a different ramp."""
    coverage = float(folio.mean())
    interior = gray[folio > 0.5]
    brightness = float(np.median(interior)) if interior.size else 0.0
    return coverage < 0.35 or brightness < 90.0


def tone_map(gray: np.ndarray, ramp: tuple[str, ...]) -> np.ndarray:
    """Step C - map luminance onto a colour ramp, preserving the photograph's tonal structure."""
    stops = np.stack([hex_to_bgr(value) for value in ramp])  # (n, 3) in BGR
    positions = np.linspace(0.0, 255.0, len(stops))
    lut = np.stack([np.interp(np.arange(256), positions, stops[:, channel]) for channel in range(3)], axis=1).astype(
        np.uint8
    )
    return lut[gray]


def upsample(gray: np.ndarray, scale: float) -> np.ndarray:
    """Lanczos resample plus a light unsharp mask, so strokes stay crisp at the output DPI."""
    if scale == 1.0:
        return gray
    height, width = gray.shape
    resized = cv2.resize(gray, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_LANCZOS4)

    blurred = cv2.GaussianBlur(resized, (0, 0), sigmaX=0.8 * scale)
    sharpened = cv2.addWeighted(resized.astype(np.float32), 1.25, blurred.astype(np.float32), -0.25, 0.0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def compose(page: np.ndarray, gray: np.ndarray, folio: np.ndarray) -> np.ndarray:
    """Keep the surround a neutral dark, so nothing outside the leaf is invented."""
    backdrop = np.broadcast_to(hex_to_bgr(BACKDROP_HEX), page.shape).astype(np.float32)
    backdrop = backdrop + 46.0 * (gray.astype(np.float32) / 255.0)[:, :, None]  # retain the mount's shading

    mask = folio[:, :, None]
    return np.clip(page.astype(np.float32) * mask + backdrop * (1.0 - mask), 0, 255).astype(np.uint8)


def process_page(source: pathlib.Path, destination: pathlib.Path, scale: float = 3.0) -> pathlib.Path:
    source_gray = cv2.imread(str(source), cv2.IMREAD_GRAYSCALE)
    if source_gray is None:
        raise RuntimeError(f"unreadable page image: {source}")

    cleaned = denoise(source_gray)
    folio = folio_mask(cleaned)
    size = (round(source_gray.shape[1] * scale), round(source_gray.shape[0] * scale))

    if is_binding(cleaned, folio):
        colorized = tone_map(upsample(cleaned, scale), LEATHER_RAMP)
    else:
        equalized = upsample(isolate(cleaned, folio), scale)
        colorized = compose(
            tone_map(equalized, PARCHMENT_RAMP),
            cv2.resize(cleaned, size, interpolation=cv2.INTER_LANCZOS4),
            cv2.resize(folio, size, interpolation=cv2.INTER_LINEAR),
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(destination), colorized, [cv2.IMWRITE_PNG_COMPRESSION, 6])
    return destination


async def process_all(
    pages: list[pathlib.Path], out_dir: pathlib.Path, workers: int, scale: float = 3.0
) -> list[pathlib.Path]:
    """Run the CPU-bound page loop asynchronously across a process pool."""
    loop = asyncio.get_running_loop()
    done = 0
    results: list[pathlib.Path] = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [loop.run_in_executor(pool, process_page, page, out_dir / page.name, scale) for page in pages]
        for future in asyncio.as_completed(futures):
            results.append(await future)
            done += 1
            if done % 10 == 0 or done == len(pages):
                print(f"  processed {done}/{len(pages)} pages", flush=True)

    return sorted(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=pathlib.Path, default=pathlib.Path("data/pages"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("data/processed"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--scale", type=float, default=3.0, help="output upsample factor (100 DPI scan -> 300 DPI)")
    args = parser.parse_args()

    pages = sorted(args.pages.glob("*.png"))
    if not pages:
        raise SystemExit(f"no page images found in {args.pages}")
    asyncio.run(process_all(pages, args.out, args.workers, args.scale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
