"""
Schedule Generation Benchmark Runner

Hits POST /api/benchmark/plan with 20 prompts × N models, scores outputs,
writes results to benchmarks/results/.

Usage:
  python benchmarks/schedule_gen.py --server http://localhost:8000 --models claude-haiku,claude-sonnet,gemini-3
  python benchmarks/schedule_gen.py --server http://89.167.11.147 --models claude-haiku,gemini-3

Output:
  benchmarks/results/schedule_gen_<ISO_DATE>_<RUN_ID>.json
  Summary table printed to stdout.
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Prompt corpus ────────────────────────────────────────────────────────────

PROMPTS = [
    # ── Tier 1 — Simple (7) ──────────────────────────────────────────────────
    {"tier": 1, "prompt": "Take a picture every 30 minutes for the next 2 hours"},
    {"tier": 1, "prompt": "Capture once at 9 AM"},
    {"tier": 1, "prompt": "Monitor every 15 minutes from 10 AM to 12 PM"},
    {"tier": 1, "prompt": "Take a photo every hour starting now for 4 hours"},
    {"tier": 1, "prompt": "Capture every 5 minutes for the next 30 minutes"},
    {"tier": 1, "prompt": "Take one picture in 10 minutes"},
    {"tier": 1, "prompt": "Photograph every 2 hours from 9 AM to 5 PM"},
    # ── Tier 2 — Moderate (7) ───────────────────────────────────────────────
    {"tier": 2, "prompt": "Take pictures every 20 minutes from 9 AM to 12 PM, then every hour until 5 PM"},
    {"tier": 2, "prompt": "Capture every 30 minutes during business hours (9 AM to 5 PM)"},
    {"tier": 2, "prompt": "Monitor the parking lot every hour during weekdays only"},
    {"tier": 2, "prompt": "Take a picture at 8 AM, 12 PM, 4 PM, and 8 PM today"},
    {"tier": 2, "prompt": "Capture every 15 minutes for the first 2 hours, then slow down to every hour"},
    {"tier": 2, "prompt": "Take photos at 7:30 AM and again every hour starting at 9 AM through 6 PM"},
    {"tier": 2, "prompt": "Monitor every 45 minutes from 10 AM to 3 PM"},
    # ── Tier 3 — Complex (6) ────────────────────────────────────────────────
    {"tier": 3, "prompt": "Watch the door more frequently around lunch time when people come and go more often"},
    {"tier": 3, "prompt": "Capture during the hours when most movement is expected — say morning rush and evening rush"},
    {"tier": 3, "prompt": "Take pictures often in the first hour, then progressively less frequently for the next 4 hours"},
    {"tier": 3, "prompt": "Monitor the room every 20 minutes but skip the lunch hour"},
    {"tier": 3, "prompt": "I want to track packages — capture at delivery times, around 10 AM, 2 PM, and 4 PM"},
    {"tier": 3, "prompt": "Set up monitoring as if you were a security camera — every 10 minutes during night hours from 8 PM to 6 AM"},
]

# ── Scoring helpers ──────────────────────────────────────────────────────────

_HH_MM_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")


def _score(result: dict) -> dict:
    """Score a single /api/benchmark/plan response."""
    tool_name = result.get("tool_name") or ""
    tool_input = result.get("tool_input") or {}
    latency_ms = result.get("latency_ms", 0)

    parseable = tool_name in ("create_schedule", "capture_sequence", "capture_now")

    # For create_schedule the planning engine returns tasks array via `prompt`,
    # but the benchmark endpoint returns the raw tool_call input.
    # For capture_sequence the schema has count + interval_ms.
    has_required_fields = False
    task_count = 0
    time_format_valid = False

    if tool_name == "create_schedule":
        # tool_input has {"prompt": "..."} — the schedule planner isn't called here,
        # only the routing decision is tested. We record that routing occurred.
        has_required_fields = "prompt" in tool_input and bool(tool_input["prompt"])
        task_count = 0  # scheduling details not available at routing stage
        time_format_valid = True  # not applicable; mark as valid to not penalise
    elif tool_name == "capture_sequence":
        has_required_fields = "count" in tool_input and "interval_ms" in tool_input
        task_count = int(tool_input.get("count", 0))
        time_format_valid = True  # capture_sequence uses ms, not HH:MM
    elif tool_name == "capture_now":
        has_required_fields = True
        task_count = 1
        time_format_valid = True
    else:
        has_required_fields = False

    return {
        "parseable": parseable,
        "has_required_fields": has_required_fields,
        "task_count": task_count,
        "time_format_valid": time_format_valid,
        "latency_ms": round(latency_ms, 1),
        "tool_name": tool_name,
        "tool_input": tool_input,
        "raw_text": result.get("raw_text", ""),
        "success": result.get("success", False),
        "error": result.get("error"),
        "manual_score": None,  # fill in after manual review
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def run_benchmark(server: str, models: list[str], request_delay: float = 0.5) -> dict:
    server = server.rstrip("/")
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc).isoformat()

    print(f"\n=== Schedule Generation Benchmark ===")
    print(f"Server  : {server}")
    print(f"Models  : {', '.join(models)}")
    print(f"Prompts : {len(PROMPTS)}")
    print(f"Run ID  : {run_id}")
    print(f"Started : {started_at}\n")

    prompt_results = []

    for pi, p in enumerate(PROMPTS, 1):
        tier = p["tier"]
        prompt = p["prompt"]
        per_model: dict[str, dict] = {}

        print(f"[{pi:02d}/{len(PROMPTS)}] T{tier}: {prompt[:60]}{'...' if len(prompt) > 60 else ''}")

        for model in models:
            try:
                resp = requests.post(
                    f"{server}/api/benchmark/plan",
                    json={"prompt": prompt, "model_key": model},
                    timeout=120,
                )
                resp.raise_for_status()
                raw = resp.json()
            except requests.exceptions.Timeout:
                raw = {"success": False, "error": "HTTP timeout (120s)", "latency_ms": 120000, "tool_name": None, "tool_input": None, "raw_text": ""}
            except Exception as e:
                raw = {"success": False, "error": str(e), "latency_ms": 0, "tool_name": None, "tool_input": None, "raw_text": ""}

            scored = _score(raw)
            per_model[model] = scored
            status = "OK" if scored["parseable"] else "FAIL"
            print(f"    {model:40s}  {status}  {scored['latency_ms']:7.0f}ms  tool={scored['tool_name'] or 'none'}")

            if request_delay > 0:
                time.sleep(request_delay)

        prompt_results.append({
            "tier": tier,
            "prompt": prompt,
            "results": per_model,
        })

    # ── Per-model summary ─────────────────────────────────────────────────────
    summary: dict[str, dict] = {}
    for model in models:
        all_rows = [pr["results"][model] for pr in prompt_results if model in pr["results"]]
        n = len(all_rows)
        parseable_count = sum(1 for r in all_rows if r["parseable"])
        latencies = [r["latency_ms"] for r in all_rows if r["latency_ms"] > 0]
        mean_lat = sum(latencies) / len(latencies) if latencies else 0

        # Per-tier breakdown
        tier_stats: dict[int, dict] = {}
        for t in (1, 2, 3):
            tier_rows = [pr["results"][model] for pr in prompt_results if pr["tier"] == t and model in pr["results"]]
            tn = len(tier_rows)
            tier_stats[t] = {
                "n": tn,
                "parseable": sum(1 for r in tier_rows if r["parseable"]),
                "parseable_rate": round(sum(1 for r in tier_rows if r["parseable"]) / tn, 3) if tn else 0,
            }

        summary[model] = {
            "n": n,
            "parseable": parseable_count,
            "parseable_rate": round(parseable_count / n, 3) if n else 0,
            "mean_latency_ms": round(mean_lat, 1),
            "tier": tier_stats,
        }

    output = {
        "run_id": run_id,
        "started_at": started_at,
        "server": server,
        "models": models,
        "prompts": prompt_results,
        "summary": {"per_model": summary},
    }

    return output


def _print_summary_table(output: dict):
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    header = f"{'Model':<40} {'Parse%':>7} {'Lat(ms)':>9}"
    print(header)
    print("-" * 70)
    for model, stats in output["summary"]["per_model"].items():
        print(
            f"{model:<40} {stats['parseable_rate']*100:6.1f}%  {stats['mean_latency_ms']:8.0f}"
        )
    print("=" * 70)

    print("\nPer-tier parseable rate:")
    header2 = f"{'Model':<40} {'Tier1':>6} {'Tier2':>6} {'Tier3':>6}"
    print(header2)
    print("-" * 60)
    for model, stats in output["summary"]["per_model"].items():
        t = stats.get("tier", {})
        r1 = t.get(1, {}).get("parseable_rate", 0) * 100
        r2 = t.get(2, {}).get("parseable_rate", 0) * 100
        r3 = t.get(3, {}).get("parseable_rate", 0) * 100
        print(f"{model:<40} {r1:5.1f}%  {r2:5.1f}%  {r3:5.1f}%")
    print()


def main():
    parser = argparse.ArgumentParser(description="Schedule generation benchmark runner")
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
    out_path = results_dir / f"schedule_gen_{date_str}_{output['run_id']}.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"Results written to: {out_path}")


if __name__ == "__main__":
    main()
