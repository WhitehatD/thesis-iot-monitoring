"""
Latency Report Generator

Fetches CaptureLatency rows from GET /api/benchmark/latency?limit=500,
computes per-stage and per-model statistics, prints a Markdown table to
stdout, and writes a CSV to benchmarks/results/.

Usage:
  python benchmarks/latency_report.py --server http://localhost:8000
  python benchmarks/latency_report.py --server http://89.167.11.147 --limit 1000

Output:
  Markdown table to stdout
  benchmarks/results/latency_report_<ISO_DATE>.csv
"""

import argparse
import csv
import math
import sys
from datetime import datetime
from pathlib import Path

import requests

# ── Stage definitions ─────────────────────────────────────────────────────────
# Each stage is (label, from_field, to_field).
# If a field is None the stage requires two explicit timestamps.

STAGES = [
    ("planning",         "t_plan_start",    "t_plan_end"),
    ("mqtt_to_upload",   "t_mqtt_sent",     "t_upload_received"),
    ("jpeg_conversion",  "t_upload_received", "t_jpeg_converted"),
    ("analysis",         "t_analysis_start", "t_analysis_end"),
    ("end_to_end",       "t_request",       "t_sse_delivered"),
]


# ── Statistics ────────────────────────────────────────────────────────────────

def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear interpolation percentile over a sorted list."""
    if not sorted_values:
        return float("nan")
    n = len(sorted_values)
    idx = (p / 100) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _stats(values: list[float]) -> dict:
    """Compute count, mean, median, p95, p99, max over a list of ms values."""
    if not values:
        return {"n": 0, "mean": float("nan"), "median": float("nan"),
                "p95": float("nan"), "p99": float("nan"), "max": float("nan")}
    s = sorted(values)
    n = len(s)
    mean = sum(s) / n
    return {
        "n": n,
        "mean": round(mean, 1),
        "median": round(_percentile(s, 50), 1),
        "p95": round(_percentile(s, 95), 1),
        "p99": round(_percentile(s, 99), 1),
        "max": round(max(s), 1),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def compute_report(rows: list[dict]) -> dict:
    """Compute stage stats overall and per model_key."""
    all_models = sorted({r.get("model_key") or "unknown" for r in rows})

    def _extract_stage_values(subset: list[dict], t_from: str, t_to: str) -> list[float]:
        out = []
        for r in subset:
            v_from = r.get(t_from)
            v_to = r.get(t_to)
            if v_from is not None and v_to is not None and v_to > v_from:
                out.append((v_to - v_from) * 1000)  # → ms
        return out

    def _stage_stats(subset: list[dict]) -> dict:
        return {
            label: _stats(_extract_stage_values(subset, t_from, t_to))
            for label, t_from, t_to in STAGES
        }

    overall = _stage_stats(rows)

    per_model: dict[str, dict] = {}
    for model in all_models:
        model_rows = [r for r in rows if (r.get("model_key") or "unknown") == model]
        per_model[model] = _stage_stats(model_rows)

    return {
        "total_rows": len(rows),
        "models": all_models,
        "overall": overall,
        "per_model": per_model,
    }


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.1f}"


def _print_markdown_table(report: dict):
    print(f"\n# Capture Pipeline Latency Report\n")
    print(f"Total rows: {report['total_rows']}  |  Models: {', '.join(report['models'])}\n")

    col_labels = ["Stage", "N", "Mean(ms)", "Median", "P95", "P99", "Max"]
    row_fmt = "| {:<22} | {:>5} | {:>10} | {:>8} | {:>8} | {:>8} | {:>8} |"
    sep = "|" + "|".join(["-" * (w + 2) for w in [22, 5, 10, 8, 8, 8, 8]]) + "|"

    def _print_section(title: str, stage_stats: dict):
        print(f"## {title}\n")
        print(row_fmt.format(*col_labels))
        print(sep)
        for label, _, _ in STAGES:
            s = stage_stats.get(label, {})
            print(row_fmt.format(
                label,
                s.get("n", 0),
                _fmt(s.get("mean")),
                _fmt(s.get("median")),
                _fmt(s.get("p95")),
                _fmt(s.get("p99")),
                _fmt(s.get("max")),
            ))
        print()

    _print_section("Overall", report["overall"])

    for model in report["models"]:
        _print_section(f"Model: {model}", report["per_model"][model])


def _write_csv(report: dict, out_path: Path):
    rows = []
    fieldnames = ["scope", "stage", "n", "mean_ms", "median_ms", "p95_ms", "p99_ms", "max_ms"]

    def _add(scope: str, stage_stats: dict):
        for label, _, _ in STAGES:
            s = stage_stats.get(label, {})
            rows.append({
                "scope": scope,
                "stage": label,
                "n": s.get("n", 0),
                "mean_ms": _fmt(s.get("mean")),
                "median_ms": _fmt(s.get("median")),
                "p95_ms": _fmt(s.get("p95")),
                "p99_ms": _fmt(s.get("p99")),
                "max_ms": _fmt(s.get("max")),
            })

    _add("overall", report["overall"])
    for model in report["models"]:
        _add(f"model:{model}", report["per_model"][model])

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Latency report generator")
    parser.add_argument("--server", default="http://localhost:8000", help="Base URL of the API server")
    parser.add_argument("--limit", type=int, default=500, help="Max rows to fetch (default 500)")
    args = parser.parse_args()

    server = args.server.rstrip("/")
    url = f"{server}/api/benchmark/latency?limit={args.limit}"

    print(f"Fetching up to {args.limit} rows from {url} ...")
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    rows = data.get("rows", [])
    if not rows:
        print("No latency rows found. Run some captures via the chat UI first.", file=sys.stderr)
        sys.exit(0)

    print(f"Fetched {len(rows)} rows.\n")

    report = compute_report(rows)
    _print_markdown_table(report)

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_path = results_dir / f"latency_report_{date_str}.csv"
    _write_csv(report, out_path)
    print(f"CSV written to: {out_path}")


if __name__ == "__main__":
    main()
