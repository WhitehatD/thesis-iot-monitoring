"""
Thesis IoT Server — Agentic Chat Endpoint (SSE)

Uses Claude Haiku with tool_use for reliable intent dispatch.
The LLM decides which tool to call based on the user's message,
then the server executes the tool and streams results.

Available tools:
  - create_schedule: NL → JSON schedule → MQTT to board
  - capture_now: Single immediate camera capture
  - capture_sequence: Multiple captures with ms-precision timing
  - ping_board: LED heartbeat sequence on the physical board
  - analyze_latest: Fetch and display the most recent AI analysis
  - get_board_status: Report board telemetry
  - erase_wifi: Factory reset WiFi credentials (destructive)

SSE event types:
  - thinking: AI reasoning text
  - tool_call: Agent is executing a tool (spinner on frontend)
  - tool_result: Tool execution complete (spinner → checkmark)
  - reply: Final markdown response
  - error: Something went wrong
  - done: Stream complete
"""

import asyncio
import json
import re
import time
from datetime import datetime, timedelta

import anthropic
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.models import ChatMessage, ChatSession
from app.config import settings
from app.db.database import async_session
from app.mqtt.client import mqtt_client
from app.planning.engine import generate_plan

router = APIRouter(prefix="/agent", tags=["Agent"])


# ── Session CRUD ────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(board_id: str = "stm32-iot-cam-01"):
    """List all chat sessions for a board."""
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession)
            .where(ChatSession.board_id == board_id)
            .order_by(ChatSession.created_at.desc())
        )
        sessions = list(result.scalars().all())

    return [
        {"id": s.id, "name": s.name, "boardId": s.board_id, "createdAt": s.created_at.isoformat()}
        for s in sessions
    ]


@router.post("/sessions")
async def create_session(request: Request):
    """Create a new chat session."""
    body = await request.json()
    board_id = body.get("boardId", "stm32-iot-cam-01")
    name = body.get("name", f"Session {datetime.now().strftime('%H:%M')}")

    async with async_session() as db:
        session = ChatSession(board_id=board_id, name=name)
        db.add(session)
        await db.commit()
        await db.refresh(session)

    return {"id": session.id, "name": session.name, "boardId": session.board_id, "createdAt": session.created_at.isoformat()}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: int):
    """Delete a chat session and all its messages."""
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession).where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return JSONResponse(status_code=404, content={"detail": "Session not found"})
        await db.delete(session)
        await db.commit()

    return {"ok": True}


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: int):
    """Get all messages for a session."""
    async with async_session() as db:
        result = await db.execute(
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            return JSONResponse(status_code=404, content={"detail": "Session not found"})

    return [
        {"role": m.role, "content": m.content, "createdAt": m.created_at.isoformat()}
        for m in session.messages
    ]


@router.delete("/sessions/{session_id}/messages")
async def clear_session_messages(session_id: int):
    """Clear all messages in a session (like /clear)."""
    from sqlalchemy import delete as sql_delete

    async with async_session() as db:
        await db.execute(
            sql_delete(ChatMessage).where(ChatMessage.session_id == session_id)
        )
        await db.commit()

    return {"ok": True}


async def _persist_message(session_id: int, role: str, content: str):
    """Save a message to the database."""
    async with async_session() as db:
        db.add(ChatMessage(session_id=session_id, role=role, content=content))
        await db.commit()


async def _load_history(session_id: int, limit: int = 20) -> list[dict]:
    """Load recent messages from DB for Claude's context."""
    async with async_session() as db:
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())

    # Return in chronological order
    return [
        {"role": m.role, "content": m.content}
        for m in reversed(messages)
    ]

# ── Tool Definitions (Claude tool_use format) ────────────

AGENT_TOOLS = [
    {
        "name": "create_schedule",
        "description": (
            "Create a LONG-DURATION monitoring schedule (2+ minutes). "
            "Uses HH:MM time format — CANNOT schedule at sub-minute precision. "
            "DO NOT use for durations under 2 minutes — use capture_sequence instead. "
            "The schedule is saved to the database and sent to the board via MQTT."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The monitoring request with your chosen duration and frequency. Include 'every X minutes for Y duration'.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "capture_now",
        "description": (
            "Take a single picture immediately. The full pipeline runs: "
            "capture → upload → AI analysis. Use for single snapshots."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "capture_sequence",
        "description": (
            "Take multiple pictures with millisecond-precision timing. "
            "Use this for ANY monitoring with sub-minute intervals OR durations under 2 minutes. "
            "Examples: 'every 20 seconds for 5 min' → count=16, interval_ms=20000. "
            "'monitor for 30 seconds' → count=4, interval_ms=7500. "
            "'monitor for 1 minute' → count=5, interval_ms=12000. "
            "'burst of 3 shots' → count=3, interval_ms=2000. "
            "YOU decide count and interval_ms based on the duration and interval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of pictures to take (2-16). Decide based on duration and interval.",
                },
                "interval_ms": {
                    "type": "integer",
                    "description": "Milliseconds between each capture (minimum 500). Decide based on requested interval.",
                },
                "objective": {
                    "type": "string",
                    "description": "What to monitor/look for in each capture.",
                },
            },
            "required": ["count", "interval_ms"],
        },
    },
    {
        "name": "ping_board",
        "description": (
            "Send a ping command to the board. The board flashes its LEDs "
            "in a distinctive pattern to confirm it's alive and responsive. "
            "Use when the user wants to verify the board is reachable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "start_portal",
        "description": (
            "Force the board into WiFi setup (captive portal) mode. "
            "The board starts a local access point so the user can "
            "reconfigure WiFi credentials via a browser. Use when the "
            "user says 'setup mode', 'portal', 'reconfigure wifi', or "
            "'enter setup'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "analyze_latest",
        "description": (
            "Retrieve the most recent AI visual analysis from the database. "
            "Shows the objective, findings, and recommendation from the last "
            "image that was analyzed by the multimodal LLM."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_board_status",
        "description": (
            "Get the current board status including online/offline state, "
            "firmware version, uptime, and capture count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "activate_schedule",
        "description": (
            "Activate an existing (currently inactive) monitoring schedule. "
            "Use when the user says 'activate schedule', 'start schedule', 'resume schedule', "
            "'turn on schedule', or 'run schedule X'. "
            "This deactivates any other active schedule first. "
            "For brand-new schedules use create_schedule instead."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "integer",
                    "description": "ID of the schedule to activate.",
                },
            },
            "required": ["schedule_id"],
        },
    },
    {
        "name": "deactivate_schedule",
        "description": (
            "Deactivate (stop) a currently active monitoring schedule. "
            "Use when the user says 'stop monitoring', 'cancel schedule', "
            "'deactivate', 'turn off', or 'disable schedule'. "
            "If schedule_id is not provided, deactivates whichever schedule is currently active."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "integer",
                    "description": "ID of the schedule to deactivate. If omitted, deactivates the active schedule.",
                },
            },
        },
    },
    {
        "name": "synthesize_schedule",
        "description": (
            "Synthesize all AI vision analyses into an evolving conclusion. "
            "Reads all recent analyses, identifies patterns and changes over time, "
            "and produces a progressive insight report. Use when the user asks "
            "'what did you learn', 'summarize findings', or 'conclusions'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent analyses to synthesize (default 10).",
                },
            },
        },
    },
    {
        "name": "modify_schedule",
        "description": (
            "Modify an EXISTING monitoring schedule — change its times, frequency, or objective. "
            "Use when user says 'change', 'update', 'reschedule', 'adjust', 'shift', or 'modify' "
            "a schedule that already exists. Re-generates the schedule from a new prompt. "
            "DO NOT use to create a brand-new schedule — use create_schedule for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "New monitoring request to replace the schedule with.",
                },
                "schedule_id": {
                    "type": "integer",
                    "description": "ID of the schedule to modify. If omitted, modifies the currently active schedule.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "sleep_mode",
        "description": (
            "Toggle the board's sleep mode. Use when the user says 'sleep', 'standby', "
            "'low power', 'wake up', or 'wake the board'. "
            "Pass enabled=true to sleep, enabled=false to wake."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "True to put the board to sleep, False to wake it up.",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "delete_schedule",
        "description": (
            "Permanently DELETE a monitoring schedule from the database. "
            "Use when the user says 'delete schedule', 'remove schedule', or 'get rid of schedule X'. "
            "This is permanent — use deactivate_schedule to just stop it without deleting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "integer",
                    "description": "ID of the schedule to delete.",
                },
            },
            "required": ["schedule_id"],
        },
    },
    {
        "name": "delete_image",
        "description": (
            "Delete a captured image and its AI analysis from storage and the database. "
            "Use when the user says 'delete image', 'remove photo', or refers to a specific image file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date folder of the image, e.g. '2026-04-25'.",
                },
                "filename": {
                    "type": "string",
                    "description": "Image filename, e.g. 'task_42_1745000000.jpg'.",
                },
            },
            "required": ["date", "filename"],
        },
    },
]

AGENT_SYSTEM_PROMPT = """You are the IoT Visual Monitoring Agent — an action-first operator controlling a physical STM32 camera board over MQTT. Be decisive, concise, and always prefer DOING over explaining.

Personality: You are a proactive field operator. When the user asks anything that could involve the camera, TAKE THE SHOT. When in doubt between looking at old data vs capturing fresh data, always capture fresh. Never say "I can't" — find the closest tool that achieves the intent.

## Tool routing (follow EXACTLY)

capture_now (DEFAULT — use this most often):
- "what do you see" / "look" / "check" / "show me" / "see now" / ANY question about current state
- "take a picture" / "capture" / "snap" / "photo"
- ANY ambiguous request → capture_now (bias toward action)

capture_sequence (timed multi-shot, up to 16 captures, runs in BACKGROUND):
- "monitor for/the next X seconds/minute" → capture_sequence
- "burst" / "sequence" / "take N pictures" / "rapid"
- ANY request with sub-minute intervals (e.g. "every 10/20/30 seconds") → capture_sequence
- 30s → count=4, interval_ms=7500
- 1 min → count=5, interval_ms=12000
- 5 min every 20s → count=16, interval_ms=20000
- NEVER use capture_now for "monitor" requests.
- This runs in the background — images appear in the Gallery as they arrive.

create_schedule (duration 2+ min, minute-level intervals ONLY):
- "monitor for X minutes/hours" with intervals >= 1 minute
- Uses HH:MM — CANNOT do sub-minute intervals (every 10s, 20s, 30s)
- If user asks for sub-minute intervals, ALWAYS use capture_sequence instead.
- YOU decide frequency. Pass duration+frequency as prompt.

Other tools:
- activate_schedule: "activate schedule X" / "start schedule" / "resume schedule" / "run schedule X"
- deactivate_schedule: "stop" / "cancel" / "deactivate" / "turn off" / "disable" schedule
- delete_schedule: "delete schedule" / "remove schedule" / "get rid of schedule" (permanent removal)
- modify_schedule: "change the schedule" / "update monitoring" / "reschedule" / "adjust" / "shift" an EXISTING schedule
- sleep_mode(enabled=true): "sleep" / "standby" / "low power" / "hibernate"
- sleep_mode(enabled=false): "wake up" / "wake the board" / "turn on"
- delete_image: "delete image" / "remove photo" / "delete the picture" (needs date + filename)
- ping_board: "ping" / "alive" / "responsive"
- start_portal: "setup" / "portal" / "wifi config"
- get_board_status: "status" / "health" / "firmware" / "uptime"
- analyze_latest: ONLY when user explicitly says "last" / "previous" / "show the old analysis"
- synthesize_schedule: "summarize all" / "conclusions" / "what did you learn"

## Rules

1. ACTION FIRST: Call the tool immediately. Don't ask clarifying questions unless truly ambiguous between two very different actions.
2. FRESH > STALE: If user asks "what do you see" or similar — ALWAYS capture_now. Never show old analysis for present-tense questions.
3. CONCISE: The streaming pipeline shows progress. Don't narrate what will happen. After results arrive, give a 1-2 sentence human summary.
4. MULTI-TOOL: You can call multiple tools in one response when appropriate.
5. NO EXCUSES: Every user intent maps to a tool. Execute it.
"""


def _sse_event(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, **data})}\n\n"


@router.post("/chat")
async def agent_chat(request: Request):
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("sessionId")  # DB integer ID
    model_key = body.get("model", "claude-haiku")

    MODEL_MAP = {
        "claude-haiku": settings.claude_haiku_model,
        "claude-sonnet": settings.claude_sonnet_model,
    }
    resolved_model = MODEL_MAP.get(model_key, settings.claude_haiku_model)

    if not message:
        return StreamingResponse(
            iter([_sse_event("error", {"text": "Empty message"})]),
            media_type="text/event-stream",
        )

    # Validate session exists
    if session_id is not None:
        try:
            session_id = int(session_id)
        except (ValueError, TypeError):
            session_id = None

    async def event_stream():
        try:
            # Load conversation history from DB
            history = await _load_history(session_id) if session_id else []
            history.append({"role": "user", "content": message})

            # Persist user message
            if session_id:
                await _persist_message(session_id, "user", message)

            yield _sse_event("thinking", {"text": f"Processing: \"{message}\""})

            # ── Call Claude with tools ──
            if not settings.anthropic_api_key:
                async for ev in _fallback_dispatch(message, session_id):
                    yield ev
                yield _sse_event("done", {})
                return

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            response = await client.messages.create(
                model=resolved_model,
                max_tokens=1024,
                system=AGENT_SYSTEM_PROMPT,
                tools=AGENT_TOOLS,
                messages=history,
                temperature=0.1,
            )

            # Process response blocks
            reply_parts = []
            for block in response.content:
                if block.type == "text":
                    reply_parts.append(block.text)

                elif block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input

                    if tool_name == "capture_now":
                        pipeline_reply = ""
                        async for ev in _capture_pipeline(tool_name, tool_input):
                            yield ev
                            if '"event": "reply"' in ev:
                                ev_data = json.loads(ev.split("data: ", 1)[1].strip())
                                pipeline_reply = ev_data.get("text", "")
                        if pipeline_reply and session_id:
                            await _persist_message(session_id, "assistant", pipeline_reply)
                        continue
                    elif tool_name == "capture_sequence":
                        pipeline_reply = ""
                        async for ev in _capture_sequence_pipeline(tool_input):
                            yield ev
                            if '"event": "reply"' in ev:
                                try:
                                    ev_data = json.loads(ev.split("data: ", 1)[1].strip())
                                    pipeline_reply = ev_data.get("text", "")
                                except Exception:
                                    pass
                        if pipeline_reply and session_id:
                            await _persist_message(session_id, "assistant", pipeline_reply)
                        continue
                    else:
                        yield _sse_event("tool_call", {
                            "id": tool_name,
                            "label": _tool_label(tool_name, tool_input),
                        })

                        result = await _execute_tool(tool_name, tool_input, session_id)

                        yield _sse_event("tool_result", {
                            "id": tool_name,
                            "success": result["success"],
                            "summary": result["summary"],
                        })

                        reply_parts.append(result.get("detail", ""))

            full_reply = "\n\n".join(p for p in reply_parts if p)
            if full_reply:
                if session_id:
                    await _persist_message(session_id, "assistant", full_reply)
                yield _sse_event("reply", {"text": full_reply})

            yield _sse_event("done", {})

        except anthropic.APIError as e:
            yield _sse_event("error", {"text": f"Claude API error: {e.message}"})
        except Exception as e:
            yield _sse_event("error", {"text": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _tool_label(name: str, inp: dict) -> str:
    labels = {
        "create_schedule": f"Generating schedule: \"{inp.get('prompt', '')[:60]}\"",
        "capture_now": "Sending capture command to board...",
        "capture_sequence": f"Sending {inp.get('count', '?')}-shot sequence...",
        "activate_schedule": f"Activating schedule #{inp.get('schedule_id', '?')}...",
        "deactivate_schedule": "Deactivating schedule...",
        "delete_schedule": f"Deleting schedule #{inp.get('schedule_id', '?')}...",
        "modify_schedule": f"Updating schedule: \"{inp.get('prompt', '')[:50]}\"",
        "sleep_mode": "Sleeping board..." if inp.get("enabled") else "Waking board...",
        "delete_image": f"Deleting {inp.get('filename', 'image')}...",
        "ping_board": "Pinging board...",
        "analyze_latest": "Fetching latest AI analysis...",
        "get_board_status": "Checking board status...",
    }
    return labels.get(name, f"Executing {name}...")


async def _capture_pipeline(tool_name: str, tool_input: dict):
    """Full agentic pipeline: capture → wait for upload(s) → analysis → report."""
    from sqlalchemy import select, func
    from app.analysis.models import AnalysisResult
    from app.db.database import async_session

    task_id = int(time.time())
    expected = 1

    if tool_name == "capture_sequence":
        expected = max(2, min(tool_input.get("count", 3), 16))
        interval = max(500, tool_input.get("interval_ms", 2000))
        delays = [i * interval for i in range(expected)]
        total_seq_ms = delays[-1] + 5000  # last capture + upload headroom
        command = json.dumps({
            "type": "capture_sequence",
            "task_id": task_id,
            "delays_ms": delays,
        })
        yield _sse_event("tool_call", {"id": "capture", "label": f"Sending {expected}-shot sequence ({interval}ms apart)..."})
    else:
        total_seq_ms = 0
        command = json.dumps({"type": "capture_now", "task_id": task_id})
        yield _sse_event("tool_call", {"id": "capture", "label": "Sending capture command to board..."})

    mqtt_client.publish(settings.mqtt_topic_commands, command)
    yield _sse_event("tool_result", {"id": "capture", "success": True, "summary": f"Capture command sent (task #{task_id})"})

    # Wait for analysis results — one for single capture, N for sequence.
    # Poll every 1s. Timeout: 20s for single shot; sequence duration + 10s/image.
    start_time = datetime.now()
    timeout_polls = max(20, (total_seq_ms // 1000) + (expected * 10))
    analyses = []
    seen_ids = set()
    wait_label = f"Waiting for {'image' if expected == 1 else f'{expected} images'}..."

    yield _sse_event("tool_call", {"id": "upload", "label": wait_label})

    for poll_idx in range(timeout_polls):
        await asyncio.sleep(1)
        elapsed = poll_idx + 1

        # Heartbeat every 5s so the client knows the server is still alive
        if elapsed % 5 == 0 and elapsed < timeout_polls:
            yield _sse_event("tool_update", {
                "id": "upload",
                "label": f"{wait_label} ({elapsed}s)",
            })

        async with async_session() as db:
            # Filter by task_id to avoid picking up stale results from other captures
            query = (
                select(AnalysisResult)
                .where(AnalysisResult.created_at >= start_time)
                .where(AnalysisResult.task_id >= task_id)
                .order_by(AnalysisResult.created_at.asc())
            )
            result = await db.execute(query)
            new_results = [r for r in result.scalars().all() if r.id not in seen_ids]

        for a in new_results:
            seen_ids.add(a.id)
            analyses.append(a)
            if expected > 1:
                yield _sse_event("tool_result", {
                    "id": f"img_{len(analyses)}",
                    "success": True,
                    "summary": f"Image {len(analyses)}/{expected} analyzed (task #{a.task_id})",
                })

        if len(analyses) >= expected:
            break

    if not analyses:
        yield _sse_event("tool_result", {"id": "upload", "success": False, "summary": f"Timeout after {timeout_polls}s — board may be offline or capture failed"})
        yield _sse_event("reply", {"text": "**Capture timed out.** The board didn't upload an image within the expected window. Check that it's online and the firmware is current."})
        return

    yield _sse_event("tool_result", {
        "id": "upload",
        "success": True,
        "summary": f"{len(analyses)}/{expected} image{'s' if expected > 1 else ''} analyzed",
    })

    # Build report
    if len(analyses) == 1:
        a = analyses[0]
        detail = (
            f"**Capture & Analysis Complete** (task #{a.task_id})\n\n"
            f"**Objective:** {a.objective}\n\n"
            f"**Findings:** {a.analysis}\n\n"
            f"**Recommendation:** {a.recommendation}\n\n"
            f"*{a.model_used} | {a.inference_time_ms:.0f}ms*"
        )
    else:
        parts = [f"**Sequence Complete** — {len(analyses)}/{expected} images analyzed\n"]
        for i, a in enumerate(analyses, 1):
            parts.append(
                f"**#{i}** (task {a.task_id}): {a.analysis[:120]}{'...' if len(a.analysis) > 120 else ''}"
            )
        if analyses[-1].recommendation:
            parts.append(f"\n**Recommendation:** {analyses[-1].recommendation}")
        parts.append(f"\n*{analyses[-1].model_used} | avg {sum(a.inference_time_ms for a in analyses) / len(analyses):.0f}ms*")
        detail = "\n\n".join(parts)

    yield _sse_event("reply", {"text": detail})


async def _capture_sequence_pipeline(tool_input: dict):
    """
    Proper agentic sequence pipeline:
      1. Create DB schedule (real task IDs for objective lookup)
      2. Send MQTT capture_sequence with first task's DB ID
      3. Poll for all N analysis results as they arrive
      4. Stream per-image SSE events in real time

    This replaces the old fire-and-forget _tool_capture_sequence path.
    """
    from app.analysis.models import AnalysisResult
    from app.scheduler.service import create_schedule, activate_schedule
    from app.scheduler.notify import notify_schedule_update

    count = max(2, min(tool_input.get("count", 3), 16))
    interval = max(500, tool_input.get("interval_ms", 2000))
    objective = tool_input.get("objective", "Quick monitoring sequence")
    total_s = (count - 1) * interval / 1000

    # Create DB schedule so every upload can look up its objective by task_id
    now = datetime.now()
    tasks = []
    for i in range(count):
        offset_s = i * interval / 1000
        task_time = now + timedelta(seconds=offset_s)
        tasks.append({
            "time": task_time.strftime("%H:%M:%S"),
            "action": "CAPTURE_IMAGE",
            "objective": objective,
        })

    async with async_session() as db:
        schedule = await create_schedule(
            db,
            name=f"Quick: {count} shots over {total_s:.0f}s",
            description=f"Automated {count}-capture sequence at {interval}ms intervals",
            tasks=tasks,
        )
        await activate_schedule(db, schedule.id)

    await notify_schedule_update()

    first_task_id = schedule.tasks[0].id
    delays = [i * interval for i in range(count)]
    command = json.dumps({
        "type": "capture_sequence",
        "task_id": first_task_id,
        "delays_ms": delays,
    })

    yield _sse_event("tool_call", {
        "id": "capture",
        "label": f"Sending {count}-shot sequence ({interval}ms apart)...",
    })
    mqtt_client.publish(settings.mqtt_topic_commands, command)
    yield _sse_event("tool_result", {
        "id": "capture",
        "success": True,
        "summary": f"Sequence started (task #{first_task_id})",
    })

    # Poll for N analyses — all uploads arrive with task_id = first_task_id
    start_time = datetime.now()
    total_seq_ms = delays[-1] + 5000  # last capture + upload + analysis headroom
    timeout_polls = max(20, (total_seq_ms // 1000) + (count * 10))
    analyses = []
    seen_ids: set[int] = set()
    seq_label = f"Waiting for {count} image{'s' if count > 1 else ''}..."

    yield _sse_event("tool_call", {"id": "upload", "label": seq_label})

    for poll_idx in range(int(timeout_polls)):
        await asyncio.sleep(1)
        elapsed = poll_idx + 1

        if elapsed % 5 == 0 and elapsed < timeout_polls:
            yield _sse_event("tool_update", {
                "id": "upload",
                "label": f"{seq_label} ({elapsed}s, {len(analyses)}/{count})",
            })

        async with async_session() as db:
            result = await db.execute(
                select(AnalysisResult)
                .where(AnalysisResult.created_at >= start_time)
                .where(AnalysisResult.task_id == first_task_id)
                .order_by(AnalysisResult.created_at.asc())
            )
            new_results = [r for r in result.scalars().all() if r.id not in seen_ids]

        for a in new_results:
            seen_ids.add(a.id)
            analyses.append(a)
            yield _sse_event("tool_result", {
                "id": f"img_{len(analyses)}",
                "success": True,
                "summary": f"Image {len(analyses)}/{count} analyzed (task #{a.task_id})",
            })

        if len(analyses) >= count:
            break

    if not analyses:
        yield _sse_event("tool_result", {
            "id": "upload",
            "success": False,
            "summary": "Timeout — board may be offline",
        })
        yield _sse_event("reply", {
            "text": "**Sequence sent** but no images received yet. The board may be offline or busy.",
        })
        return

    yield _sse_event("tool_result", {
        "id": "upload",
        "success": True,
        "summary": f"{len(analyses)}/{count} image{'s' if count > 1 else ''} analyzed",
    })

    # Build per-image report
    parts = [f"**Sequence Complete** — {len(analyses)}/{count} images analyzed\n"]
    for i, a in enumerate(analyses, 1):
        snippet = a.analysis[:120] + ("..." if len(a.analysis) > 120 else "")
        parts.append(f"**#{i}**: {snippet}")
    if analyses[-1].recommendation:
        parts.append(f"\n**Recommendation:** {analyses[-1].recommendation}")
    avg_ms = sum(a.inference_time_ms for a in analyses) / len(analyses)
    parts.append(f"\n*{analyses[-1].model_used} | avg {avg_ms:.0f}ms*")

    yield _sse_event("reply", {"text": "\n\n".join(parts)})


async def _execute_tool(name: str, inp: dict, session_id: str) -> dict:
    """Execute a tool and return {success, summary, detail}."""

    if name == "create_schedule":
        return await _tool_create_schedule(inp)
    elif name == "capture_now":
        return await _tool_capture_now()
    elif name == "capture_sequence":
        return await _tool_capture_sequence(inp)
    elif name == "activate_schedule":
        return await _tool_activate_schedule(inp)
    elif name == "deactivate_schedule":
        return await _tool_deactivate_schedule(inp)
    elif name == "modify_schedule":
        return await _tool_modify_schedule(inp)
    elif name == "ping_board":
        return await _tool_ping()
    elif name == "start_portal":
        return await _tool_start_portal()
    elif name == "analyze_latest":
        return await _tool_analyze_latest()
    elif name == "get_board_status":
        return await _tool_board_status()
    elif name == "synthesize_schedule":
        return await _tool_synthesize(inp)
    elif name == "sleep_mode":
        return await _tool_sleep_mode(inp)
    elif name == "delete_schedule":
        return await _tool_delete_schedule(inp)
    elif name == "delete_image":
        return await _tool_delete_image(inp)
    else:
        return {"success": False, "summary": f"Unknown tool: {name}", "detail": ""}


async def _tool_create_schedule(inp: dict) -> dict:
    from app.db.database import async_session
    from app.scheduler.service import create_schedule, activate_schedule, list_schedules

    prompt = inp.get("prompt", "")
    model_key = "claude-sonnet" if settings.anthropic_api_key else "qwen3-vl"

    # Enrich prompt with current time so the planner avoids past times
    now = datetime.now()
    enriched_prompt = (
        f"Current time: {now.strftime('%H:%M')} on {now.strftime('%Y-%m-%d')}. "
        f"Request: {prompt}"
    )

    try:
        plan = await generate_plan(enriched_prompt, model_key)
    except Exception as e:
        return {"success": False, "summary": f"Planning failed: {e}", "detail": ""}

    if not plan.tasks:
        return {"success": False, "summary": "No tasks generated", "detail": "The planner returned an empty schedule."}

    task_count = len(plan.tasks)
    times = [t.time for t in plan.tasks]

    # Persist to DB so analysis can find objectives by task_id
    async with async_session() as db:
        # Check for conflicting active schedules
        existing = await list_schedules(db)
        active = [s for s in existing if s.is_active]
        conflict_note = ""
        if active:
            conflict_note = f"\n\n*Deactivated previous schedule: \"{active[0].name}\"*"

        schedule = await create_schedule(
            db,
            name=f"Agent: {prompt[:50]}",
            description=prompt,
            tasks=[t.model_dump() for t in plan.tasks],
        )

        # Activate (deactivates others) and get MQTT payload
        mqtt_payload = await activate_schedule(db, schedule.id)

    # Publish to board
    mqtt_client.publish(settings.mqtt_topic_commands, json.dumps(mqtt_payload))

    # Push real-time update to dashboard
    from app.scheduler.notify import notify_schedule_update
    await notify_schedule_update()

    task_list = "\n".join(
        f"| {t.id} | {t.time} | {t.action} | {t.objective} |"
        for t in plan.tasks
    )
    detail = (
        f"**Schedule active** ({task_count} tasks, {times[0]}–{times[-1]})\n\n"
        f"| ID | Time | Action | Objective |\n|---|---|---|---|\n{task_list}"
        f"{conflict_note}"
    )

    return {
        "success": True,
        "summary": f"{task_count} tasks scheduled ({times[0]}–{times[-1]})",
        "detail": detail,
    }


async def _tool_activate_schedule(inp: dict) -> dict:
    from app.db.database import async_session
    from app.scheduler.service import activate_schedule, get_schedule
    from app.scheduler.notify import notify_schedule_update

    schedule_id = inp.get("schedule_id")
    if not schedule_id:
        return {"success": False, "summary": "schedule_id required", "detail": ""}

    async with async_session() as db:
        try:
            mqtt_payload = await activate_schedule(db, int(schedule_id))
            schedule = await get_schedule(db, int(schedule_id))
            name = schedule.name
        except Exception as e:
            return {"success": False, "summary": f"Activate failed: {e}", "detail": ""}

    mqtt_client.publish(settings.mqtt_topic_commands, json.dumps(mqtt_payload))
    await notify_schedule_update()

    return {
        "success": True,
        "summary": f"Activated: {name}",
        "detail": f"**Schedule activated:** \"{name}\"\n\nThe board has been sent the updated task list.",
    }


async def _tool_deactivate_schedule(inp: dict) -> dict:
    from app.db.database import async_session
    from app.scheduler.service import deactivate_schedule, list_schedules
    from app.scheduler.notify import notify_schedule_update

    schedule_id = inp.get("schedule_id")

    async with async_session() as db:
        if schedule_id:
            schedule = await deactivate_schedule(db, schedule_id)
            name = schedule.name
        else:
            # Find and deactivate the currently active schedule
            schedules = await list_schedules(db)
            active = [s for s in schedules if s.is_active]
            if not active:
                return {"success": False, "summary": "No active schedule", "detail": "There is no active schedule to deactivate."}
            schedule = await deactivate_schedule(db, active[0].id)
            name = schedule.name

    # Tell board to clear its schedule
    command = json.dumps({"type": "delete_schedule"})
    mqtt_client.publish(settings.mqtt_topic_commands, command)

    await notify_schedule_update()

    return {
        "success": True,
        "summary": f"Deactivated: {name}",
        "detail": f"**Schedule deactivated:** \"{name}\"\n\nThe board has been told to clear its schedule.",
    }


async def _tool_modify_schedule(inp: dict) -> dict:
    """Re-plan and update an existing schedule in-place."""
    from app.db.database import async_session
    from app.scheduler.service import get_schedule, list_schedules, update_schedule, activate_schedule
    from app.scheduler.notify import notify_schedule_update

    prompt = inp.get("prompt", "")
    schedule_id = inp.get("schedule_id")

    # Find the target schedule
    async with async_session() as db:
        if schedule_id:
            try:
                schedule = await get_schedule(db, int(schedule_id))
            except Exception:
                return {"success": False, "summary": f"Schedule #{schedule_id} not found", "detail": ""}
        else:
            schedules = await list_schedules(db)
            active = [s for s in schedules if s.is_active]
            if not active:
                # Fall back to most recently created
                if schedules:
                    schedule = schedules[0]
                else:
                    return {
                        "success": False,
                        "summary": "No schedule found to modify",
                        "detail": "There are no schedules. Create one first with create_schedule.",
                    }
            else:
                schedule = active[0]
            schedule_id = schedule.id

        was_active = schedule.is_active
        old_name = schedule.name

    # Re-generate schedule from new prompt
    now = datetime.now()
    enriched_prompt = (
        f"Current time: {now.strftime('%H:%M')} on {now.strftime('%Y-%m-%d')}. "
        f"Request: {prompt}"
    )
    model_key = "claude-sonnet" if settings.anthropic_api_key else "qwen3-vl"
    try:
        plan = await generate_plan(enriched_prompt, model_key)
    except Exception as e:
        return {"success": False, "summary": f"Re-planning failed: {e}", "detail": ""}

    if not plan.tasks:
        return {"success": False, "summary": "Planner returned empty schedule", "detail": ""}

    # Update DB (replaces tasks atomically)
    async with async_session() as db:
        await update_schedule(
            db,
            schedule_id=int(schedule_id),
            name=f"Agent: {prompt[:50]}",
            description=prompt,
            tasks=[t.model_dump() for t in plan.tasks],
        )
        if was_active:
            mqtt_payload = await activate_schedule(db, int(schedule_id))

    if was_active:
        mqtt_client.publish(settings.mqtt_topic_commands, json.dumps(mqtt_payload))

    await notify_schedule_update()

    times = [t.time for t in plan.tasks]
    task_list = "\n".join(
        f"| {t.id} | {t.time} | {t.action} | {t.objective} |"
        for t in plan.tasks
    )
    detail = (
        f"**Schedule updated** (was: \"{old_name}\")\n\n"
        f"**New plan:** {len(plan.tasks)} tasks, {times[0]}–{times[-1]}\n\n"
        f"| ID | Time | Action | Objective |\n|---|---|---|---|\n{task_list}"
        + (f"\n\n*Board notified with updated schedule.*" if was_active else "")
    )
    return {
        "success": True,
        "summary": f"Schedule #{schedule_id} updated: {len(plan.tasks)} tasks ({times[0]}–{times[-1]})",
        "detail": detail,
    }


async def _tool_capture_now() -> dict:
    task_id = int(time.time())
    command = json.dumps({"type": "capture_now", "task_id": task_id})
    mqtt_client.publish(settings.mqtt_topic_commands, command)
    return {
        "success": True,
        "summary": f"Capture sent (task #{task_id})",
        "detail": f"**Capture triggered** (task #{task_id}). The image will appear in the gallery after upload + AI analysis.",
    }


async def _tool_capture_sequence(inp: dict) -> dict:
    from app.db.database import async_session
    from app.scheduler.service import create_schedule, activate_schedule

    count = max(2, min(inp.get("count", 3), 16))
    interval = max(500, inp.get("interval_ms", 2000))
    total_s = (count - 1) * interval / 1000

    # Build schedule tasks — use current time offset for display
    now = datetime.now()
    tasks = []
    for i in range(count):
        offset_s = i * interval / 1000
        task_time = now + timedelta(seconds=offset_s)
        tasks.append({
            "time": task_time.strftime("%H:%M:%S"),
            "action": "CAPTURE_IMAGE",
            "objective": inp.get("objective", "Quick monitoring sequence"),
        })

    # Persist as a real schedule
    async with async_session() as db:
        schedule = await create_schedule(
            db,
            name=f"Quick: {count} shots over {total_s:.0f}s",
            description=f"Automated {count}-capture sequence at {interval}ms intervals",
            tasks=tasks,
        )
        await activate_schedule(db, schedule.id)

    # Push real-time update to dashboard
    from app.scheduler.notify import notify_schedule_update
    await notify_schedule_update()

    # Send the capture_sequence MQTT command (ms-precision timing)
    delays = [i * interval for i in range(count)]
    command = json.dumps({
        "type": "capture_sequence",
        "task_id": schedule.tasks[0].id,
        "delays_ms": delays,
    })
    mqtt_client.publish(settings.mqtt_topic_commands, command)

    return {
        "success": True,
        "summary": f"{count} captures scheduled ({total_s:.0f}s sequence)",
        "detail": (
            f"**Monitoring started** — {count} captures over {total_s:.0f}s, running in the background.\n\n"
            f"Track progress in the Schedules tab."
        ),
    }


async def _tool_ping() -> dict:
    command = json.dumps({"type": "ping"})
    mqtt_client.publish(settings.mqtt_topic_commands, command)
    return {
        "success": True,
        "summary": "Ping sent — board LEDs will flash",
        "detail": "**Ping sent.** The board's LEDs will flash to confirm it's alive.",
    }


async def _tool_start_portal() -> dict:
    command = json.dumps({"type": "start_portal"})
    mqtt_client.publish(settings.mqtt_topic_commands, command)
    return {
        "success": True,
        "summary": "Portal mode started — board is now an access point",
        "detail": (
            "**Setup mode activated.** The board is starting a WiFi access point.\n\n"
            "Connect to the board's AP network and open `http://192.168.10.1` "
            "in a browser to reconfigure WiFi credentials."
        ),
    }


async def _tool_analyze_latest() -> dict:
    from sqlalchemy import select
    from app.analysis.models import AnalysisResult
    from app.db.database import async_session

    async with async_session() as db:
        result = await db.execute(
            select(AnalysisResult).order_by(AnalysisResult.created_at.desc()).limit(1)
        )
        analysis = result.scalar_one_or_none()

    if not analysis:
        return {
            "success": False,
            "summary": "No analyses found",
            "detail": "No image analyses found yet. Try capturing an image first.",
        }

    return {
        "success": True,
        "summary": f"Analysis for task #{analysis.task_id}",
        "detail": (
            f"**Latest Analysis** (task #{analysis.task_id})\n\n"
            f"**Objective:** {analysis.objective}\n\n"
            f"**Findings:** {analysis.analysis}\n\n"
            f"**Recommendation:** {analysis.recommendation}\n\n"
            f"*{analysis.model_used} | {analysis.inference_time_ms:.0f}ms*"
        ),
    }


async def _tool_board_status() -> dict:
    from sqlalchemy import func, select
    from app.analysis.models import AnalysisResult
    from app.db.database import async_session

    # Count analyses and images to give real stats
    async with async_session() as db:
        count_result = await db.execute(select(func.count(AnalysisResult.id)))
        analysis_count = count_result.scalar() or 0

        latest_result = await db.execute(
            select(AnalysisResult).order_by(AnalysisResult.created_at.desc()).limit(1)
        )
        latest = latest_result.scalar_one_or_none()

    detail = "**Board Status**\n\n"
    detail += f"- **Total Analyses:** {analysis_count}\n"
    if latest:
        detail += f"- **Last Analysis:** task #{latest.task_id} ({latest.model_used}, {latest.inference_time_ms:.0f}ms)\n"
        detail += f"- **Last Objective:** {latest.objective}\n"

    return {
        "success": True,
        "summary": f"{analysis_count} analyses recorded",
        "detail": detail,
    }


async def _tool_synthesize(inp: dict) -> dict:
    """Synthesize all recent analyses into evolving conclusions."""
    from sqlalchemy import select
    from app.analysis.models import AnalysisResult
    from app.db.database import async_session

    limit = inp.get("limit", 10)

    async with async_session() as db:
        result = await db.execute(
            select(AnalysisResult)
            .order_by(AnalysisResult.created_at.desc())
            .limit(limit)
        )
        analyses = list(result.scalars().all())

    if not analyses:
        return {
            "success": False,
            "summary": "No analyses to synthesize",
            "detail": "No image analyses found. Capture some images first.",
        }

    # Build a synthesis using Claude
    if settings.anthropic_api_key:
        entries = []
        for a in reversed(analyses):  # chronological order
            entries.append(
                f"Task #{a.task_id} | {a.objective}\n"
                f"Findings: {a.analysis}\n"
                f"Recommendation: {a.recommendation}"
            )

        synthesis_prompt = (
            "You are analyzing a series of visual monitoring observations from an IoT camera over time.\n\n"
            "Observations (chronological):\n\n" +
            "\n---\n".join(entries) +
            "\n\nSynthesize these observations into:\n"
            "1. **Pattern**: What patterns or trends do you see across observations?\n"
            "2. **Changes**: What changed between observations?\n"
            "3. **Conclusion**: Overall assessment of the monitored environment.\n"
            "4. **Recommendation**: What should be done next?\n\n"
            "Be concise and specific."
        )

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=settings.claude_haiku_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": synthesis_prompt}],
            temperature=0.2,
        )
        synthesis = response.content[0].text
    else:
        # Fallback: simple aggregation
        synthesis = "**Observations:**\n\n"
        for a in reversed(analyses):
            synthesis += f"- Task #{a.task_id}: {a.analysis[:100]}\n"

    return {
        "success": True,
        "summary": f"Synthesized {len(analyses)} observations",
        "detail": synthesis,
    }


async def _tool_sleep_mode(inp: dict) -> dict:
    enabled = inp.get("enabled", True)
    payload = json.dumps({"type": "sleep_mode", "enabled": enabled})
    mqtt_client.publish(settings.mqtt_topic_commands, payload)
    state = "sleep" if enabled else "wake"
    return {
        "success": True,
        "summary": f"Board {state} command sent",
        "detail": f"**Board is now {'sleeping' if enabled else 'awake'}.**",
    }


async def _tool_delete_schedule(inp: dict) -> dict:
    from app.db.database import async_session
    from app.scheduler.service import get_schedule, delete_schedule as svc_delete
    from app.scheduler.notify import notify_schedule_update

    schedule_id = inp.get("schedule_id")
    if not schedule_id:
        return {"success": False, "summary": "schedule_id required", "detail": ""}

    async with async_session() as db:
        try:
            schedule = await get_schedule(db, int(schedule_id))
            name = schedule.name
            await svc_delete(db, int(schedule_id))
        except Exception as e:
            return {"success": False, "summary": f"Delete failed: {e}", "detail": ""}

    payload = json.dumps({"type": "delete_schedule", "schedule_id": schedule_id})
    mqtt_client.publish(settings.mqtt_topic_commands, payload)
    await notify_schedule_update()

    return {
        "success": True,
        "summary": f"Deleted: {name}",
        "detail": f"**Schedule deleted:** \"{name}\"",
    }


async def _tool_delete_image(inp: dict) -> dict:
    from pathlib import Path
    from sqlalchemy import delete as sql_delete
    from app.analysis.models import AnalysisResult
    from app.db.database import async_session

    date = inp.get("date", "")
    filename = inp.get("filename", "")

    if not date or not filename:
        return {"success": False, "summary": "date and filename required", "detail": ""}

    # Prevent path traversal
    if any(c in date + filename for c in ("/", "\\", "..")):
        return {"success": False, "summary": "Invalid path characters", "detail": ""}

    img_path = Path(settings.upload_dir) / date / filename
    if not img_path.exists():
        return {"success": False, "summary": f"{filename} not found", "detail": f"Image `{filename}` not found in {date}/"}

    img_path.unlink()

    # Delete matching AnalysisResult row (filename: task_{id}_{ts}.jpg)
    parts = Path(filename).stem.split("_")
    if len(parts) >= 2:
        try:
            task_id = int(parts[1])
            async with async_session() as db:
                await db.execute(sql_delete(AnalysisResult).where(AnalysisResult.task_id == task_id))
                await db.commit()
        except (ValueError, IndexError):
            pass

    return {
        "success": True,
        "summary": f"Deleted {filename}",
        "detail": f"**Image deleted:** `{filename}` ({date})",
    }


# ── Fallback: rule-based dispatch when no API key ────────

async def _fallback_dispatch(message: str, session_id: str):
    """Simple keyword matching when Claude API is not available."""
    msg = message.lower()

    if any(w in msg for w in ["take a picture", "capture now", "snap", "photo now"]):
        result = await _tool_capture_now()
    elif any(w in msg for w in ["burst", "sequence", "multiple", "several pictures"]):
        count = 3
        for m in re.findall(r"(\d+)", message):
            count = int(m)
            break
        result = await _tool_capture_sequence({"count": count, "interval_ms": 2000})
    elif any(w in msg for w in ["what do you see", "what does", "look at", "check on", "what's there"]):
        result = await _tool_capture_now()
    elif any(w in msg for w in ["analyze", "latest image", "last capture", "previous analysis", "last analysis"]):
        result = await _tool_analyze_latest()
    elif any(w in msg for w in ["ping", "alive", "responsive"]):
        result = await _tool_ping()
    elif any(w in msg for w in ["status", "online", "health", "uptime"]):
        result = await _tool_board_status()
    elif any(w in msg for w in ["activate schedule", "start schedule", "run schedule", "resume schedule"]):
        ids = re.findall(r"\d+", message)
        if ids:
            result = await _tool_activate_schedule({"schedule_id": int(ids[0])})
        else:
            result = {"success": False, "summary": "Schedule ID required", "detail": "Please specify which schedule to activate (e.g. 'activate schedule 3')."}
    elif any(w in msg for w in ["stop", "cancel", "deactivate", "disable", "turn off"]):
        result = await _tool_deactivate_schedule({})
    elif any(w in msg for w in ["change schedule", "update schedule", "modify schedule", "reschedule", "adjust schedule"]):
        result = await _tool_modify_schedule({"prompt": message})
    elif any(w in msg for w in ["delete schedule", "remove schedule"]):
        # best-effort: extract numeric id from message
        ids = re.findall(r"\d+", message)
        if ids:
            result = await _tool_delete_schedule({"schedule_id": int(ids[0])})
        else:
            result = {"success": False, "summary": "Schedule ID required", "detail": "Please specify which schedule to delete (e.g. 'delete schedule 3')."}
    elif any(w in msg for w in ["sleep", "standby"]):
        result = await _tool_sleep_mode({"enabled": True})
    elif any(w in msg for w in ["wake up", "wake the board"]):
        result = await _tool_sleep_mode({"enabled": False})
    elif any(w in msg for w in ["monitor", "schedule", "every", "between", "watch"]):
        result = await _tool_create_schedule({"prompt": message})
    else:
        result = {
            "success": True,
            "summary": "Help",
            "detail": (
                "I can: **schedule monitoring**, **capture images**, **analyze captures**, "
                "**ping the board**, or **check status**. Try a natural language request!"
            ),
        }

    yield _sse_event("tool_call", {"id": "action", "label": "Processing..."})
    yield _sse_event("tool_result", {
        "id": "action",
        "success": result["success"],
        "summary": result["summary"],
    })
    yield _sse_event("reply", {"text": result.get("detail", "")})
