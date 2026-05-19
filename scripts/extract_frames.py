#!/usr/bin/env python3
"""
Extract N evenly-spaced frames from a video file for the thesis benchmark.

Requires: ffmpeg on PATH.

Usage:
    python scripts/extract_frames.py path/to/video.mp4
    python scripts/extract_frames.py path/to/video.mp4 --n 20 --out scripts/benchmark_images
    python scripts/extract_frames.py path/to/video.mp4 --n 20 --width 1280

Output:
    N JPEG frames saved to --out directory, named frame_001.jpg … frame_N.jpg
    Prints frame timestamps so you can verify coverage.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def get_duration(video: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ffprobe error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def extract_frames(video: Path, n: int, out_dir: Path, width: int | None) -> None:
    """Extract n evenly-spaced frames from video into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = get_duration(video)
    print(f"Video duration: {duration:.1f}s  →  {n} frames every {duration/n:.1f}s")

    # Build vf filter: select evenly-spaced frames, optionally resize
    # expr: select frame closest to each target timestamp
    # fps=N/duration selects exactly N frames from the full clip
    fps_val = n / duration

    vf_parts = [f"fps={fps_val:.6f}"]
    if width:
        vf_parts.append(f"scale={width}:-2")  # maintain aspect ratio

    vf = ",".join(vf_parts)

    out_pattern = str(out_dir / "frame_%03d.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", vf,
        "-q:v", "2",            # JPEG quality (2 = ~95%, highest practical)
        "-frames:v", str(n),
        out_pattern,
    ]

    print(f"Running: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ffmpeg error:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    frames = sorted(out_dir.glob("frame_*.jpg"))
    print(f"\nExtracted {len(frames)} frames → {out_dir}/")
    for i, f in enumerate(frames):
        ts = (i + 0.5) * (duration / n)
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name}  @ {ts:6.1f}s  ({size_kb} KB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path, help="Input video file")
    parser.add_argument("--n", type=int, default=20, help="Number of frames to extract (default: 20)")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "benchmark_images",
        help="Output directory (default: scripts/benchmark_images/)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Resize width in pixels (height auto, e.g. --width 1280). Omit to keep original.",
    )
    args = parser.parse_args()

    if not args.video.exists():
        print(f"ERROR: video file not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    # Check ffmpeg is available
    if subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode != 0:
        print("ERROR: ffmpeg not found on PATH. Install via: winget install ffmpeg", file=sys.stderr)
        sys.exit(1)

    extract_frames(args.video, args.n, args.out, args.width)


if __name__ == "__main__":
    main()
