#!/usr/bin/env python3
"""Curate 20 benchmark images from MIT Indoor Scenes for the thesis VLM eval.

Picks N images from monitoring-relevant categories with a fixed seed for
reproducibility. Outputs to scripts/benchmark_images/<category>_<idx>.jpg.

Usage:
    python scripts/curate_benchmark_images.py
    python scripts/curate_benchmark_images.py --source datasets/Images --out scripts/benchmark_images
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

# Monitoring-relevant indoor scenes. Counts sum to 20.
CATEGORIES: dict[str, int] = {
    "office": 4,
    "meeting_room": 3,
    "computerroom": 3,
    "corridor": 3,
    "library": 2,
    "kitchen": 2,
    "livingroom": 2,
    "lobby": 1,
}

SEED = 20260519  # fixed seed for reproducibility


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--source",
        type=Path,
        default=Path("datasets/Images"),
        help="MIT Indoor Scenes Images/ directory (default: datasets/Images)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("scripts/benchmark_images"),
        help="Output directory (default: scripts/benchmark_images)",
    )
    ap.add_argument(
        "--seed", type=int, default=SEED, help=f"Random seed (default: {SEED})"
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)

    if not args.source.is_dir():
        print(f"[ERROR] Source not found: {args.source}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)

    total = 0
    missing: list[str] = []
    manifest: list[str] = []

    for category, n in CATEGORIES.items():
        cat_dir = args.source / category
        if not cat_dir.is_dir():
            missing.append(category)
            continue

        images = sorted(
            p
            for p in cat_dir.iterdir()
            if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        if len(images) < n:
            print(
                f"[WARN] {category}: only {len(images)} images, requested {n}",
                file=sys.stderr,
            )
            n = len(images)

        picks = rng.sample(images, n)
        for idx, src in enumerate(picks, start=1):
            dst = args.out / f"{category}_{idx:02d}{src.suffix.lower()}"
            shutil.copy2(src, dst)
            manifest.append(f"{dst.name}\t{src.relative_to(args.source.parent)}")
            total += 1
            print(f"  {category}_{idx:02d}: {src.name}")

    if missing:
        print(f"\n[ERROR] Missing categories: {missing}", file=sys.stderr)
        print(
            f"Available: {sorted(p.name for p in args.source.iterdir() if p.is_dir())}",
            file=sys.stderr,
        )
        return 1

    manifest_path = args.out / "MANIFEST.tsv"
    manifest_path.write_text(
        "image\tsource\n" + "\n".join(manifest) + "\n", encoding="utf-8"
    )

    print(f"\nDone. {total} images copied to {args.out}/")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
