"""
Thesis IoT Server — AI Planning Engine
Core innovation: Natural Language → JSON Hardware Schedule.

Supports three backends:
  - Qwen3-VL-30B-A3B (via vLLM, OpenAI-compatible)
  - Qwen2.5-VL-3B (via vLLM, lightweight baseline)
  - Gemini 3 Flash (via Google GenAI API)
"""

import json
from datetime import datetime

from openai import AsyncOpenAI

from app.config import settings
from app.api.schemas import PlanResponse, ScheduledTask


# ── System Prompt ────────────────────────────────────────

PLANNING_SYSTEM_PROMPT = """You are an AI Planning Engine for an IoT visual monitoring system.

Your job is to convert a natural language monitoring request into a precise JSON execution schedule
that will be sent to an STM32 microcontroller with a camera.

Given a user request, extract:
1. **Timeframe**: Start and end times (use 24h format)
2. **Frequency**: How often to capture images (derive from urgency/context)
3. **Objective**: What the camera should look for in each image

Output ONLY a valid JSON object with this schema:
{
  "tasks": [
    {
      "time": "HH:MM",
      "action": "CAPTURE_IMAGE",
      "id": <sequential_integer>,
      "objective": "<what to analyze in the image>"
    }
  ]
}

Rules:
- Generate tasks at reasonable intervals (minimum 5 minutes apart)
- If no end time is specified, default to 1 hour from start
- If no frequency is specified, use 15-minute intervals
- If no start time is given, use the next upcoming hour
- Task IDs start at 1 and increment sequentially
- Keep objectives concise and specific
- Output ONLY the JSON, no explanation"""


# ── Planning Engine ──────────────────────────────────────

_plan_counter = 0


async def generate_plan(prompt: str, model_key: str = "qwen3-vl") -> PlanResponse:
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

    if model_key in ("qwen3-vl", "qwen2.5-vl"):
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


async def _plan_with_vllm(prompt: str, model_key: str) -> list[ScheduledTask]:
    """Generate schedule using local vLLM (OpenAI-compatible API)."""
    model_name = (
        settings.vllm_model
        if model_key == "qwen3-vl"
        else "Qwen/Qwen2.5-VL-3B-Instruct"
    )

    client = AsyncOpenAI(
        base_url=settings.vllm_base_url,
        api_key="not-needed",  # vLLM doesn't require an API key
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
    # Strip markdown code fences if present
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
