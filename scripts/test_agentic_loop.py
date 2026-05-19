#!/usr/bin/env python3
"""
Agentic loop integration test.

Exercises the multi-turn agentic loop end-to-end:
  1. Upload benchmark images to populate the DB with real analysis
  2. Run agentic chat sessions with multi-step prompts
  3. Parse every SSE event and produce a turn-by-turn trace

Usage:
    python scripts/test_agentic_loop.py
    python scripts/test_agentic_loop.py --skip-upload  # if images already uploaded
    python scripts/test_agentic_loop.py --model claude-sonnet
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import AsyncIterator

import httpx

SERVER = "http://89.167.11.147:8000"
IMAGES_DIR = Path(__file__).parent / "benchmark_images"

# Prompts chosen to force multi-turn chains — avoid capture_now since no board is attached
AGENTIC_PROMPTS = [
    {
        "label": "Analyze + schedule",
        "message": (
            "Show me the latest image analysis result from the server. "
            "Based on what you find, create a monitoring schedule appropriate for that environment."
        ),
        "expected_tools": ["analyze_latest", "create_schedule"],
    },
    {
        "label": "Board status + synthesis",
        "message": (
            "Check what the board status is, then give me a synthesized summary "
            "of all recent observations from the monitoring system."
        ),
        "expected_tools": ["get_board_status", "synthesize_schedule"],
    },
    {
        "label": "Multi-step planning",
        "message": (
            "First check the board status. Then look at the latest image analysis. "
            "Finally, create an hourly monitoring schedule optimized for an office environment."
        ),
        "expected_tools": ["get_board_status", "analyze_latest", "create_schedule"],
    },
]


# ── SSE parser ────────────────────────────────────────────────────────────────

async def stream_sse(
    client: httpx.AsyncClient, session_id: int, message: str, model: str
) -> list[dict]:
    """Send a chat message and collect all SSE events."""
    events: list[dict] = []
    url = f"{SERVER}/api/agent/chat"
    body = {"message": message, "sessionId": session_id, "model": model}

    async with client.stream("POST", url, json=body, timeout=120.0) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
                events.append(ev)
            except json.JSONDecodeError:
                events.append({"event": "raw", "text": raw})

    return events


# ── Upload helper ─────────────────────────────────────────────────────────────

async def upload_images(client: httpx.AsyncClient, images: list[Path], model: str) -> int:
    """Upload images via /api/upload, returns count uploaded."""
    count = 0
    for idx, img in enumerate(images, start=1):
        task_id = 90000 + idx  # Use high IDs outside normal range to avoid collision
        with open(img, "rb") as f:
            content = f.read()
        try:
            r = await client.post(
                f"{SERVER}/api/upload",
                params={"task_id": task_id},
                content=content,
                headers={"Content-Type": "image/jpeg"},
                timeout=30.0,
            )
            if r.status_code in (200, 201):
                count += 1
                print(f"  Uploaded {img.name} → task_id={task_id}")
            else:
                print(f"  WARN: upload {img.name} → HTTP {r.status_code}: {r.text[:80]}")
        except Exception as e:
            print(f"  ERR: upload {img.name}: {e}")

    # Wait for background analysis to complete
    if count:
        print(f"  Waiting 12s for analysis of {count} images...")
        await asyncio.sleep(12)

    return count


# ── Event reporter ────────────────────────────────────────────────────────────

def print_trace(events: list[dict], prompt_label: str, expected: list[str]) -> dict:
    """Print turn-by-turn trace; return metrics dict."""
    tool_calls: list[str] = []
    tool_results: list[dict] = []
    turns = 0
    reply_text = ""
    thinking_count = 0

    print(f"\n  {'-'*62}")
    for ev in events:
        etype = ev.get("event", "?")

        if etype == "thinking":
            thinking_count += 1
            snippet = ev.get("text", "")[:60].replace("\n", " ")
            print(f"  [THINKING]    : {snippet}...")

        elif etype == "tool_call":
            label = ev.get("label", ev.get("id", "?"))
            tool_calls.append(label)
            turns += 1
            print(f"  [TOOL CALL]   : {label}")

        elif etype == "tool_update":
            elapsed = ev.get("elapsed", "")
            label = ev.get("label", "")
            print(f"  [TOOL UPDATE] : {label} ({elapsed}s elapsed)")

        elif etype == "tool_result":
            success = ev.get("success", True)
            summary = ev.get("summary", "")
            ok = "OK" if success else "FAIL"
            tool_results.append({"success": success, "summary": summary})
            print(f"  [TOOL RESULT] [{ok}]: {summary[:80]}")

        elif etype == "reply":
            chunk = ev.get("text", "")
            reply_text += chunk
            if len(reply_text) == len(chunk):  # first chunk
                snippet = chunk[:120].replace("\n", " ")
                print(f"  [REPLY START] : {snippet}...")

        elif etype == "error":
            print(f"  [ERROR]       : {ev.get('text', '')}")

        elif etype == "done":
            print(f"  [DONE]")

    print(f"\n  Final reply ({len(reply_text)} chars):")
    # Print reply in wrapped lines
    for i in range(0, min(len(reply_text), 600), 100):
        print(f"    {reply_text[i:i+100]}")
    if len(reply_text) > 600:
        print(f"    ... [{len(reply_text)-600} chars truncated]")

    # Check expected tools
    expected_hit = [e for e in expected if any(e in tc for tc in tool_calls)]
    missing = [e for e in expected if e not in expected_hit]

    print(f"\n  {'-'*62}")
    print(f"  Metrics:")
    print(f"    Tool calls      : {len(tool_calls)}  ->  {tool_calls}")
    print(f"    Tool results    : {len(tool_results)}")
    print(f"    Agentic turns   : {turns}")
    print(f"    Thinking blocks : {thinking_count}")
    print(f"    Reply length    : {len(reply_text)} chars")
    print(f"    Expected tools  : {expected}")
    print(f"    Tools found     : {expected_hit}")
    if missing:
        print(f"    MISSING tools   : {missing}  ← agent chose differently")
    print(f"  {'─'*62}")

    return {
        "label": prompt_label,
        "tool_calls": tool_calls,
        "agentic_turns": turns,
        "reply_chars": len(reply_text),
        "expected_hit": len(expected_hit),
        "expected_total": len(expected),
        "missing_tools": missing,
        "success": all(r["success"] for r in tool_results) if tool_results else True,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(model: str, skip_upload: bool):
    async with httpx.AsyncClient() as client:
        # 1. Health check
        try:
            r = await client.get(f"{SERVER}/api/sessions/agent", timeout=5.0)
        except httpx.ConnectError:
            print(f"ERROR: Server not running at {SERVER}")
            print("Start it with: cd server && uvicorn app.main:app --reload")
            sys.exit(1)

        print(f"Server OK — model={model}\n")

        # 2. Upload benchmark images (to seed DB with real analysis results)
        if not skip_upload:
            images = sorted(IMAGES_DIR.glob("*.jpg"))[:4]
            if not images:
                print(f"No images found in {IMAGES_DIR}")
            else:
                print(f"Uploading {len(images)} benchmark images for analysis...")
                count = await upload_images(client, images, model)
                print(f"  {count}/{len(images)} uploaded and analyzed\n")

        # 3. Create a fresh agent session
        r = await client.post(
            f"{SERVER}/api/agent/sessions",
            json={"boardId": "stm32-iot-cam-01"},
            timeout=10.0,
        )
        if r.status_code not in (200, 201):
            print(f"ERR: create session → {r.status_code}: {r.text}")
            sys.exit(1)
        session = r.json()
        session_id = session["id"]
        print(f"Agent session created: id={session_id}\n")

        # 4. Run each agentic prompt
        metrics_all = []
        for i, prompt in enumerate(AGENTIC_PROMPTS, 1):
            print(f"\n{'='*66}")
            print(f"  Run {i}/{len(AGENTIC_PROMPTS)}: {prompt['label']}")
            print(f"{'='*66}")
            print(f"  Prompt: {prompt['message'][:100]}...")
            t0 = time.monotonic()
            events = await stream_sse(client, session_id, prompt["message"], model)
            elapsed = time.monotonic() - t0
            print(f"  Streamed {len(events)} events in {elapsed:.1f}s")

            m = print_trace(events, prompt["label"], prompt["expected_tools"])
            m["wall_seconds"] = round(elapsed, 1)
            metrics_all.append(m)

            # Small pause between runs to avoid hammering the LLM
            if i < len(AGENTIC_PROMPTS):
                await asyncio.sleep(2)

        # 5. Summary table
        print(f"\n\n{'='*66}")
        print("  SUMMARY")
        print(f"{'='*66}")
        print(f"  {'Label':<28} {'Turns':>6} {'Tools':>8} {'Chars':>8} {'Time':>7} {'OK':>4}")
        print(f"  {'-'*28} {'-'*6} {'-'*8} {'-'*8} {'-'*7} {'-'*4}")
        for m in metrics_all:
            ok = "✓" if m["success"] and not m["missing_tools"] else "~"
            print(
                f"  {m['label']:<28} {m['agentic_turns']:>6} "
                f"{len(m['tool_calls']):>8} {m['reply_chars']:>8} "
                f"{m['wall_seconds']:>6.1f}s {ok:>4}"
            )

        all_turns = [m["agentic_turns"] for m in metrics_all]
        print(f"\n  Avg agentic turns: {sum(all_turns)/len(all_turns):.1f}")
        print(f"  Total tool calls : {sum(len(m['tool_calls']) for m in metrics_all)}")
        multi_turn = sum(1 for t in all_turns if t > 1)
        print(f"  Multi-turn runs  : {multi_turn}/{len(AGENTIC_PROMPTS)}")
        print(f"{'='*66}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="claude-sonnet", choices=["claude-haiku", "claude-sonnet", "gemini-3"])
    parser.add_argument("--skip-upload", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.model, args.skip_upload))
