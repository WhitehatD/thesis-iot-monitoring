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

import json
import re
import time

import anthropic
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.mqtt.client import mqtt_client
from app.planning.engine import generate_plan

router = APIRouter(prefix="/agent", tags=["Agent"])

# Server-side session history
_sessions: dict[str, list[dict]] = {}

# ── Tool Definitions (Claude tool_use format) ────────────

AGENT_TOOLS = [
    {
        "name": "create_schedule",
        "description": (
            "Generate a monitoring schedule from a natural language request. "
            "Translates time ranges and frequencies into a JSON task list and "
            "publishes it to the STM32 board via MQTT. Use this when the user "
            "wants periodic or scheduled image captures over a time window."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The user's natural language monitoring request, forwarded to the planning LLM.",
                },
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "capture_now",
        "description": (
            "Take a single picture immediately. Sends a capture_now command "
            "to the STM32 board. The board captures one image, uploads it, "
            "and the server runs AI analysis on it. Use for single snapshots."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "capture_sequence",
        "description": (
            "Take multiple pictures in rapid succession with precise timing. "
            "Sends a single MQTT message with an array of millisecond delays. "
            "The board executes all captures without needing additional MQTT "
            "messages. Use when the user wants 2+ captures close together "
            "(e.g. 'take 3 pictures 2 seconds apart', 'burst of 5 shots')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of pictures to take (2-16).",
                },
                "interval_ms": {
                    "type": "integer",
                    "description": "Milliseconds between each capture (minimum 500).",
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
]

AGENT_SYSTEM_PROMPT = """You are the IoT Visual Monitoring Agent controlling an STM32 camera board.

You have tools to control the board. Use them based on the user's request:
- For scheduled/periodic monitoring → create_schedule
- For a single immediate photo → capture_now
- For multiple rapid photos (burst, sequence) → capture_sequence
- To check if the board is alive → ping_board
- To see what the camera last saw → analyze_latest
- To check board health → get_board_status

Always use a tool when the user's request maps to one. Be concise in your responses.
When you use a tool, briefly explain what you did and the result.
For capture_sequence, derive count and interval_ms from the user's request (default: 2s interval).
"""


def _sse_event(event: str, data: dict) -> str:
    return f"data: {json.dumps({'event': event, **data})}\n\n"


@router.post("/chat")
async def agent_chat(request: Request):
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("sessionId", "default")

    if not message:
        return StreamingResponse(
            iter([_sse_event("error", {"text": "Empty message"})]),
            media_type="text/event-stream",
        )

    async def event_stream():
        try:
            if session_id not in _sessions:
                _sessions[session_id] = []
            history = _sessions[session_id]
            history.append({"role": "user", "content": message})

            # Trim history to last 20 messages
            if len(history) > 20:
                _sessions[session_id] = history[-20:]
                history = _sessions[session_id]

            yield _sse_event("thinking", {"text": f"Processing: \"{message}\""})

            # ── Call Claude with tools ──
            if not settings.anthropic_api_key:
                # Fallback: rule-based dispatch without LLM
                async for ev in _fallback_dispatch(message, session_id):
                    yield ev
                yield _sse_event("done", {})
                return

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            response = await client.messages.create(
                model=settings.claude_haiku_model,
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
                history.append({"role": "assistant", "content": full_reply})
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
        "ping_board": "Pinging board...",
        "analyze_latest": "Fetching latest AI analysis...",
        "get_board_status": "Checking board status...",
    }
    return labels.get(name, f"Executing {name}...")


async def _execute_tool(name: str, inp: dict, session_id: str) -> dict:
    """Execute a tool and return {success, summary, detail}."""

    if name == "create_schedule":
        return await _tool_create_schedule(inp)
    elif name == "capture_now":
        return await _tool_capture_now()
    elif name == "capture_sequence":
        return await _tool_capture_sequence(inp)
    elif name == "ping_board":
        return await _tool_ping()
    elif name == "analyze_latest":
        return await _tool_analyze_latest()
    elif name == "get_board_status":
        return await _tool_board_status()
    else:
        return {"success": False, "summary": f"Unknown tool: {name}", "detail": ""}


async def _tool_create_schedule(inp: dict) -> dict:
    prompt = inp.get("prompt", "")
    model_key = "claude-sonnet" if settings.anthropic_api_key else "qwen3-vl"

    try:
        plan = await generate_plan(prompt, model_key)
    except Exception as e:
        return {"success": False, "summary": f"Planning failed: {e}", "detail": ""}

    task_count = len(plan.tasks)
    times = [t.time for t in plan.tasks]

    schedule_payload = {
        "type": "schedule",
        "tasks": [t.model_dump() for t in plan.tasks],
    }
    await mqtt_client.publish(settings.mqtt_topic_commands, json.dumps(schedule_payload))

    task_list = "\n".join(
        f"| {t.id} | {t.time} | {t.action} | {t.objective} |"
        for t in plan.tasks
    )
    detail = (
        f"**Schedule created** ({task_count} tasks, {times[0]}–{times[-1]})\n\n"
        f"| ID | Time | Action | Objective |\n|---|---|---|---|\n{task_list}"
    )

    return {
        "success": True,
        "summary": f"{task_count} tasks scheduled ({times[0]}–{times[-1]})",
        "detail": detail,
    }


async def _tool_capture_now() -> dict:
    task_id = int(time.time())
    command = json.dumps({"type": "capture_now", "task_id": task_id})
    await mqtt_client.publish(settings.mqtt_topic_commands, command)
    return {
        "success": True,
        "summary": f"Capture sent (task #{task_id})",
        "detail": f"**Capture triggered** (task #{task_id}). The image will appear in the gallery after upload + AI analysis.",
    }


async def _tool_capture_sequence(inp: dict) -> dict:
    count = max(2, min(inp.get("count", 3), 16))
    interval = max(500, inp.get("interval_ms", 2000))

    delays = [i * interval for i in range(count)]
    task_id = int(time.time())

    command = json.dumps({
        "type": "capture_sequence",
        "task_id": task_id,
        "delays_ms": delays,
    })
    await mqtt_client.publish(settings.mqtt_topic_commands, command)

    return {
        "success": True,
        "summary": f"{count} captures queued ({interval}ms apart)",
        "detail": (
            f"**Capture sequence started** — {count} images, {interval}ms intervals.\n\n"
            f"Delays: {delays}\n\n"
            f"All captures are batched in a single MQTT message for reliability."
        ),
    }


async def _tool_ping() -> dict:
    command = json.dumps({"type": "ping"})
    await mqtt_client.publish(settings.mqtt_topic_commands, command)
    return {
        "success": True,
        "summary": "Ping sent — board LEDs will flash",
        "detail": "**Ping sent.** The board's LEDs will flash to confirm it's alive.",
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
    return {
        "success": True,
        "summary": "Status displayed in telemetry panel",
        "detail": (
            "**Board Status**\n\n"
            "Live telemetry is shown in the left panel:\n"
            "- **Online/Offline** — MQTT heartbeats every 5s\n"
            "- **Firmware** — current version (auto-updated via OTA)\n"
            "- **Captures** — total images this session\n\n"
            "Use **Ping Node** button to verify responsiveness."
        ),
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
    elif any(w in msg for w in ["analyze", "what do you see", "latest image", "last capture"]):
        result = await _tool_analyze_latest()
    elif any(w in msg for w in ["ping", "alive", "responsive"]):
        result = await _tool_ping()
    elif any(w in msg for w in ["status", "online", "health", "uptime"]):
        result = await _tool_board_status()
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
