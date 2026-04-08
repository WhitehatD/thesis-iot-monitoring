"""
Thesis IoT Server — AI Planning Engine
Core innovation: Natural Language → JSON Hardware Schedule.

Primary backend: Claude Sonnet (Anthropic API)
Legacy backends (for thesis benchmarking):
  - Qwen3-VL-30B-A3B (via vLLM, OpenAI-compatible)
  - Gemini 3 Flash (via Google GenAI API)
"""

import json
from datetime import datetime

import anthropic

from app.config import settings
from app.api.schemas import PlanResponse, ScheduledTask


# ── System Prompt ────────────────────────────────────────

PLANNING_SYSTEM_PROMPT = """You are an AI Planning Engine for an IoT visual monitoring system.

Convert a natural language monitoring request into a JSON schedule for an STM32 camera board.

The request will include the current time. NEVER schedule tasks in the past.

Output ONLY valid JSON:
{
  "tasks": [
    {
      "time": "HH:MM",
      "action": "CAPTURE_IMAGE",
      "id": <sequential_integer>,
      "objective": "<what to analyze>"
    }
  ]
}

Frequency guidelines — YOU decide based on duration:
- Under 2 minutes: every 15-30 seconds (use HH:MM format, space them 1 min apart minimum)
- 2-10 minutes: every 1-2 minutes
- 10-60 minutes: every 5 minutes
- 1-4 hours: every 15 minutes
- 4-12 hours: every 30-60 minutes
- Overnight/24h: every 1-2 hours

Rules:
- Tasks must be at least 1 minute apart (board needs time to capture + upload)
- Start from the current time (or specified start), never earlier
- If duration is given without start time, start NOW (current time)
- If no duration given, default to 30 minutes
- Each task's objective should be specific to what the user wants monitored
- For evolving observations, vary the objective slightly (e.g., "check for changes since last capture")
- Task IDs start at 1 and increment
- Output ONLY JSON, no explanation"""


# ── Planning Engine ──────────────────────────────────────

_plan_counter = 0


async def generate_plan(prompt: str, model_key: str = "claude-sonnet") -> PlanResponse:
    """
    Generate a task schedule from a natural language prompt.

    Args:
        prompt: User's natural language monitoring request.
        model_key: Which AI backend to use.

    Returns:
        PlanResponse with the generated schedule.
    """
    global _plan_counter
    _plan_counter += 1

    if model_key == "claude-sonnet":
        schedule = await _plan_with_claude(prompt, settings.claude_sonnet_model)
    elif model_key == "claude-haiku":
        schedule = await _plan_with_claude(prompt, settings.claude_haiku_model)
    elif model_key in ("qwen3-vl", "qwen2.5-vl"):
        schedule = await _plan_with_vllm(prompt, model_key)
    elif model_key == "gemini-3":
        schedule = await _plan_with_gemini(prompt)
    else:
        raise ValueError(f"Unknown model: {model_key}")

    return PlanResponse(
        plan_id=_plan_counter,
        prompt=prompt,
        tasks=schedule,
        model_used=model_key,
        created_at=datetime.now(),
    )


async def _plan_with_claude(prompt: str, model: str) -> list[ScheduledTask]:
    """Generate schedule using Claude (Anthropic API)."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        system=PLANNING_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    return _parse_schedule(response.content[0].text)


async def _plan_with_vllm(prompt: str, model_key: str) -> list[ScheduledTask]:
    """Generate schedule using local vLLM (OpenAI-compatible API)."""
    from openai import AsyncOpenAI

    model_name = (
        settings.vllm_model
        if model_key == "qwen3-vl"
        else "Qwen/Qwen2.5-VL-3B-Instruct"
    )

    client = AsyncOpenAI(
        base_url=settings.vllm_base_url,
        api_key="not-needed",
    )

    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=2048,
    )

    return _parse_schedule(response.choices[0].message.content)


async def _plan_with_gemini(prompt: str) -> list[ScheduledTask]:
    """Generate schedule using Gemini 3 Flash API."""
    from google import genai

    client = genai.Client(api_key=settings.gemini_api_key)

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=f"{PLANNING_SYSTEM_PROMPT}\n\nUser request: {prompt}",
    )

    return _parse_schedule(response.text)


def _parse_schedule(raw_output: str) -> list[ScheduledTask]:
    """Parse LLM output into a list of ScheduledTask objects."""
    text = raw_output.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0]

    data = json.loads(text)
    tasks = data.get("tasks", [])

    return [
        ScheduledTask(
            time=t["time"],
            action=t.get("action", "CAPTURE_IMAGE"),
            id=t["id"],
            objective=t.get("objective", ""),
        )
        for t in tasks
    ]
