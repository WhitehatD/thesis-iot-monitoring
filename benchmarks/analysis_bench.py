"""
Vision Analysis Benchmark Runner

Fetches the latest 10 images from GET /api/images, then calls
POST /api/benchmark/analyze for each (image, model) pair.

Usage:
  python benchmarks/analysis_bench.py --server http://localhost:8000 --models claude-haiku,claude-sonnet,gemini-3
  python benchmarks/analysis_bench.py --server http://89.167.11.147 --models claude-haiku,gemini-3

Output:
  benchmarks/results/analysis_bench_<ISO_DATE>_<RUN_ID>.json
  Summary table printed to stdout.
"""

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Scoring helpers ──────────────────────────────────────────────────────────


def _score(result: dict) -> dict:
    """Compute auto-metrics from a /api/benchmark/analyze response."""
    r = result.get("result") or {}
    analysis_text = r.get("findings", "") or r.get("analysis", "") or ""
    recommendation_text = r.get("recommendation", "") or ""
    confidence = r.get("confidence")

    return {
        "success": result.get("success", False),
        "latency_ms": round(result.get("latency_ms", 0), 1),
        "analysis_length_chars": len(analysis_text),
        "recommendation_length_chars": len(recommendation_text),
        "confidence": confidence,
        "analysis": analysis_text,
        "recommendation": recommendation_text,
        "error": result.get("error"),
        "manual_score": None,   # int 1-5, fill in after manual review
        "manual_notes": None,   # str, fill in after manual review
    }


# ── Main ─────────────────────────────────────────────────────────────────────


def run_benchmark(server: str, models: list[str], request_delay: float = 0.5) -> dict:
    server = server.rstrip("/")
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc).isoformat()

    print(f"\n=== Vision Analysis Benchmark ===")
    print(f"Server  : {server}")
    print(f"Models  : {', '.join(models)}")
    print(f"Run ID  : {run_id}")
    print(f"Started : {started_at}\n")

    # ── Fetch image list ──────────────────────────────────────────────────────
    print("Fetching image list from server...")
    try:
        resp = requests.get(f"{server}/api/images", timeout=30)
        resp.raise_for_status()
        images_data = resp.json()
    except Exception as e:
        print(f"ERROR: could not fetch image list: {e}", file=sys.stderr)
        sys.exit(1)

    all_images = images_data.get("images", [])
    if not all_images:
        print("ERROR: No images found on server. Upload some images first.", file=sys.stderr)
        sys.exit(1)

    # Take the newest 10
    images = all_images[:10]
    print(f"Found {len(all_images)} images total; benchmarking the newest {len(images)}.\n")

    image_results = []

    for ii, img in enumerate(images, 1):
        # Build the server-side absolute path from the image_path if stored,
        # or reconstruct it from the URL + server upload_dir convention.
        # The server returns "url": "/api/images/YYYY-MM-DD/filename.jpg".
        # /api/benchmark/analyze accepts image_path as a server-side FS path.
        # We pass the URL-relative path; the server resolves it internally.
        # For robustness we also try the analysis.image_path if present.
        image_path = None
        if img.get("analysis") and img["analysis"].get("image_path"):
            image_path = img["analysis"]["image_path"]
        # Fallback: reconstruct upload path from date + filename
        if not image_path:
            date = img.get("date", "")
            filename = img.get("filename", "")
            if date and filename:
                # Server default upload_dir is ./data/uploads
                image_path = f"./data/uploads/{date}/{filename}"

        if not image_path:
            print(f"  [{ii:02d}] Skipping — cannot determine image_path for: {img.get('filename')}")
            continue

        objective = "General visual inspection"
        if img.get("analysis") and img["analysis"].get("objective"):
            objective = img["analysis"]["objective"]

        per_model: dict[str, dict] = {}
        print(f"[{ii:02d}/{len(images)}] {img.get('filename', 'unknown')} (task #{img.get('task_id')})")

        for model in models:
            try:
                resp = requests.post(
                    f"{server}/api/benchmark/analyze",
                    json={
                        "image_path": image_path,
                        "model_key": model,
                        "objective": objective,
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                raw = resp.json()
            except requests.exceptions.Timeout:
                raw = {"success": False, "error": "HTTP timeout (120s)", "latency_ms": 120000, "result": None}
            except Exception as e:
                raw = {"success": False, "error": str(e), "latency_ms": 0, "result": None}

            scored = _score(raw)
            per_model[model] = scored
            status = "OK" if scored["success"] else "FAIL"
            print(
                f"    {model:<40}  {status}  {scored['latency_ms']:7.0f}ms  "
                f"chars={scored['analysis_length_chars']}"
            )

            if request_delay > 0:
                time.sleep(request_delay)

        image_results.append({
            "filename": img.get("filename"),
            "date": img.get("date"),
            "task_id": img.get("task_id"),
            "image_path": image_path,
            "objective": objective,
            "results": per_model,
        })

    # ── Per-model summary ─────────────────────────────────────────────────────
    summary: dict[str, dict] = {}
    for model in models:
        all_rows = [ir["results"][model] for ir in image_results if model in ir["results"]]
        n = len(all_rows)
        success_count = sum(1 for r in all_rows if r["success"])
        latencies = [r["latency_ms"] for r in all_rows if r["latency_ms"] > 0]
        mean_lat = sum(latencies) / len(latencies) if latencies else 0
        lengths = [r["analysis_length_chars"] for r in all_rows if r["success"]]
        mean_len = sum(lengths) / len(lengths) if lengths else 0

        summary[model] = {
            "n": n,
            "success": success_count,
            "success_rate": round(success_count / n, 3) if n else 0,
            "mean_latency_ms": round(mean_lat, 1),
            "mean_analysis_length_chars": round(mean_len, 1),
        }

    output = {
        "run_id": run_id,
        "started_at": started_at,
        "server": server,
        "models": models,
        "images": image_results,
        "summary": {"per_model": summary},
    }

    return output


def _print_summary_table(output: dict):
    print("\n" + "=" * 75)
    print("SUMMARY")
    print("=" * 75)
    header = f"{'Model':<40} {'Success%':>9} {'Lat(ms)':>9} {'Chars':>8}"
    print(header)
    print("-" * 75)
    for model, stats in output["summary"]["per_model"].items():
        print(
            f"{model:<40} {stats['success_rate']*100:8.1f}%  "
            f"{stats['mean_latency_ms']:8.0f}  "
            f"{stats['mean_analysis_length_chars']:7.0f}"
        )
    print("=" * 75 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Vision analysis benchmark runner")
    parser.add_argument("--server", default="http://localhost:8000", help="Base URL of the API server")
    parser.add_argument(
        "--models",
        default="claude-haiku,claude-sonnet,gemini-3",
        help="Comma-separated list of model keys",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between requests (default 0.5; use 0 to disable)",
    )
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        print("ERROR: --models must specify at least one model", file=sys.stderr)
        sys.exit(1)

    output = run_benchmark(args.server, models, request_delay=args.delay)

    _print_summary_table(output)

    # Write results file
    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    out_path = results_dir / f"analysis_bench_{date_str}_{output['run_id']}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Results written to: {out_path}")


if __name__ == "__main__":
    main()
