"""
Thesis IoT Server — Benchmark Endpoints

Provides three benchmark surfaces:
  GET  /api/benchmark/latency   — Query CaptureLatency rows (stage-level timestamps)
  POST /api/benchmark/plan      — Single planning pass: prompt + model → tool_call result
  POST /api/benchmark/analyze   — Single analysis pass: image + model → analysis result

No SSE, no MQTT, no board interaction. Safe to call from offline benchmark runners.
"""

import os
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.analysis.models import CaptureLatency
from app.api.agent_routes import AGENT_TOOLS, AGENT_SYSTEM_PROMPT
from app.analysis.engine import analyze_image
from app.config import settings

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


# ── Latency query ────────────────────────────────────────────────────────────

@router.get("/latency")
async def list_latency(
    limit: int = 200,
    model_key: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Return raw CaptureLatency rows, newest first.

    Query params:
      limit     — max rows returned (default 200)
      model_key — optional filter by model (e.g. claude-haiku)
    """
    q = select(CaptureLatency).order_by(CaptureLatency.id.desc()).limit(limit)
    if model_key:
        q = q.where(CaptureLatency.model_key == model_key)
    rows = (await db.execute(q)).scalars().all()
    return {
        "rows": [
            {c.name: getattr(r, c.name) for c in CaptureLatency.__table__.columns}
            for r in rows
        ]
    }


# ── Planning benchmark ───────────────────────────────────────────────────────

@router.post("/plan")
async def benchmark_plan(payload: dict):
    """Run a single planning pass and return the tool_call result.

    No SSE, no MQTT, no board interaction.

    Request body:
      {
        "prompt": "Take a picture every 30 minutes for 2 hours",
        "model_key": "claude-haiku" | "claude-sonnet" | "gemini-3-flash-preview" | ...
      }

    Response:
      {
        "model_key": str,
        "tool_name": str | null,
        "tool_input": dict | null,
        "raw_text": str,
        "latency_ms": float,
        "success": bool,
        "error": str | null
      }
    """
    prompt = payload.get("prompt", "")
    model_key = payload.get("model_key", "claude-haiku")

    if not prompt:
        raise HTTPException(status_code=422, detail="prompt is required")

    t0 = time.time()

    # Route to the appropriate backend
    try:
        if model_key in ("claude-haiku", "claude-sonnet"):
            result = await _plan_with_claude(prompt, model_key)
        elif model_key in ("gemini-3", "gemini-3-flash-preview"):
            result = await _plan_with_gemini(prompt)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported model_key for planning: {model_key}. "
                       "Supported: claude-haiku, claude-sonnet, gemini-3, gemini-3-flash-preview",
            )
    except HTTPException:
        raise
    except Exception as e:
        return {
            "model_key": model_key,
            "tool_name": None,
            "tool_input": None,
            "raw_text": "",
            "latency_ms": (time.time() - t0) * 1000,
            "success": False,
            "error": f"{type(e).__name__}: {e}",
        }

    result["latency_ms"] = (time.time() - t0) * 1000
    result["model_key"] = model_key
    return result


async def _plan_with_claude(prompt: str, model_key: str) -> dict:
    """Call Claude with the agent tools and return extracted tool_call result."""
    import anthropic

    if not settings.anthropic_api_key:
        return {
            "tool_name": None,
            "tool_input": None,
            "raw_text": "",
            "success": False,
            "error": "ANTHROPIC_API_KEY not configured",
        }

    CLAUDE_MODEL_MAP = {
        "claude-haiku": settings.claude_haiku_model,
        "claude-sonnet": settings.claude_sonnet_model,
    }
    model = CLAUDE_MODEL_MAP.get(model_key, settings.claude_haiku_model)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=model,
        max_tokens=1024,
        system=AGENT_SYSTEM_PROMPT,
        tools=AGENT_TOOLS,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    tool_name = None
    tool_input = None
    raw_text = ""

    for block in response.content:
        if block.type == "text":
            raw_text += block.text
        elif block.type == "tool_use":
            tool_name = block.name
            tool_input = block.input

    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "raw_text": raw_text,
        "success": tool_name is not None,
        "error": None if tool_name is not None else "No tool_use block in response",
    }


async def _plan_with_gemini(prompt: str) -> dict:
    """Call Gemini in tool-use mode and return extracted tool_call result.

    Gemini's function-calling API is used; tools are translated from the
    Anthropic tool schema format into Gemini FunctionDeclaration objects.
    """
    if not settings.gemini_api_key:
        return {
            "tool_name": None,
            "tool_input": None,
            "raw_text": "",
            "success": False,
            "error": "GEMINI_API_KEY not configured",
        }

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {
            "tool_name": None,
            "tool_input": None,
            "raw_text": "",
            "success": False,
            "error": "google-genai package not installed",
        }

    # Convert Anthropic tool schema → Gemini FunctionDeclaration
    gemini_tools = []
    for t in AGENT_TOOLS:
        gemini_tools.append(
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t["name"],
                        description=t.get("description", ""),
                        parameters=t.get("input_schema", {}),
                    )
                ]
            )
        )

    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Content(
                role="user",
                parts=[types.Part.from_text(
                    f"{AGENT_SYSTEM_PROMPT}\n\nUser request: {prompt}"
                )],
            )
        ],
        config=types.GenerateContentConfig(tools=gemini_tools, temperature=0.1),
    )

    tool_name = None
    tool_input = None
    raw_text = ""

    for candidate in response.candidates or []:
        for part in (candidate.content.parts or []):
            if part.text:
                raw_text += part.text
            if part.function_call:
                tool_name = part.function_call.name
                # Gemini returns a MapComposite — convert to plain dict
                tool_input = dict(part.function_call.args) if part.function_call.args else {}

    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "raw_text": raw_text,
        "success": tool_name is not None,
        "error": None if tool_name is not None else "No function_call in response",
    }


# ── Analysis benchmark ───────────────────────────────────────────────────────

@router.post("/analyze")
async def benchmark_analyze(payload: dict):
    """Run a single image analysis pass and return the result.

    No DB write — results are returned directly to the caller for offline
    scoring and aggregation by the benchmark runner.

    Request body:
      {
        "image_path": "/absolute/or/relative/path/to/image.jpg",
        "model_key": "claude-haiku" | "claude-sonnet" | "gemini-3" | "qwen3-vl" | ...,
        "objective": "General visual inspection"  (optional)
      }

    Response:
      {
        "model_key": str,
        "objective": str,
        "image_path": str,
        "latency_ms": float,
        "result": {analysis dict from engine}
      }
    """
    image_path = payload.get("image_path", "")
    if not image_path:
        raise HTTPException(status_code=422, detail="image_path is required")
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {image_path}")

    objective = payload.get("objective", "General visual inspection")
    model_key = payload.get("model_key", "claude-sonnet")

    t0 = time.time()
    try:
        result = await analyze_image(image_path, objective, model_key)
    except Exception as e:
        return {
            "model_key": model_key,
            "objective": objective,
            "image_path": image_path,
            "latency_ms": (time.time() - t0) * 1000,
            "result": None,
            "success": False,
            "error": f"{type(e).__name__}: {e}",
        }

    return {
        "model_key": model_key,
        "objective": objective,
        "image_path": image_path,
        "latency_ms": (time.time() - t0) * 1000,
        "result": result,
        "success": True,
        "error": None,
    }
