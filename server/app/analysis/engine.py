"""
Thesis IoT Server — Multimodal Visual Analysis Engine

Core agentic layer: takes a captured image + the original monitoring objective
and produces a structured analysis with actionable recommendations.

Supports three backends:
  - Qwen3-VL-30B-A3B (via vLLM, OpenAI-compatible)
  - Qwen2.5-VL-3B (via vLLM, lightweight baseline)
  - Gemini 3 Flash (via Google GenAI API)
"""

import base64
import time
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings


# ── System Prompt ────────────────────────────────────────

ANALYSIS_SYSTEM_PROMPT = """You are the visual analysis engine of an autonomous IoT monitoring system.

You receive images captured by an STM32 microcontroller camera and the user's original monitoring objective.

Analyze the image and produce a JSON response with exactly these fields:
{
  "description": "<2-3 sentence factual description of what is visible in the image>",
  "objective_met": true/false,
  "findings": "<specific observations related to the monitoring objective>",
  "recommendation": "<one actionable recommendation based on what you see>"
}

Rules:
- Be specific and factual — describe what you actually see, not what you assume
- If the image is blurry, dark, or unreadable, say so honestly
- The recommendation should be practical and immediately actionable
- Output ONLY the JSON, no markdown fences, no explanation"""


async def analyze_image(
    image_path: str,
    objective: str,
    model_key: str = "gemini-3",
) -> dict:
    """
    Analyze a captured image against a monitoring objective.

    Args:
        image_path: Path to the JPEG image on disk.
        objective: The original monitoring objective from the user's plan.
        model_key: Which AI backend to use.

    Returns:
        Dict with: description, objective_met, findings, recommendation, model_used, inference_time_ms
    """
    start = time.monotonic()

    if model_key in ("qwen3-vl", "qwen2.5-vl"):
        result = await _analyze_with_vllm(image_path, objective, model_key)
    elif model_key == "gemini-3":
        result = await _analyze_with_gemini(image_path, objective)
    else:
        raise ValueError(f"Unknown model: {model_key}")

    elapsed_ms = (time.monotonic() - start) * 1000
    result["model_used"] = model_key
    result["inference_time_ms"] = round(elapsed_ms, 1)
    return result


async def _analyze_with_vllm(
    image_path: str, objective: str, model_key: str
) -> dict:
    """Analyze image using local vLLM (OpenAI-compatible vision API)."""
    model_name = (
        settings.vllm_model
        if model_key == "qwen3-vl"
        else "Qwen/Qwen2.5-VL-3B-Instruct"
    )

    image_b64 = _load_image_b64(image_path)

    client = AsyncOpenAI(
        base_url=settings.vllm_base_url,
        api_key="not-needed",
    )

    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                    {
                        "type": "text",
                        "text": f"Monitoring objective: {objective}",
                    },
                ],
            },
        ],
        temperature=0.1,
        max_tokens=1024,
    )

    return _parse_analysis(response.choices[0].message.content)


async def _analyze_with_gemini(image_path: str, objective: str) -> dict:
    """Analyze image using Gemini 3 Flash API."""
    from google import genai
    from google.genai import types

    image_bytes = Path(image_path).read_bytes()

    client = genai.Client(api_key=settings.gemini_api_key)

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Content(
                parts=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    types.Part.from_text(
                        f"{ANALYSIS_SYSTEM_PROMPT}\n\nMonitoring objective: {objective}"
                    ),
                ]
            )
        ],
    )

    return _parse_analysis(response.text)


def _parse_analysis(raw_output: str) -> dict:
    """Parse LLM output into a structured analysis dict."""
    import json

    text = raw_output.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # LLM returned unstructured text — wrap it
        return {
            "description": text[:500],
            "objective_met": False,
            "findings": text,
            "recommendation": "Unable to parse structured analysis — review image manually.",
        }

    return {
        "description": data.get("description", ""),
        "objective_met": data.get("objective_met", False),
        "findings": data.get("findings", ""),
        "recommendation": data.get("recommendation", ""),
    }


def _load_image_b64(image_path: str) -> str:
    """Load an image file and return its base64 encoding."""
    return base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")
