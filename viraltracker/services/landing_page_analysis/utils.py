"""Shared utilities for the landing page analysis package."""

import json


def parse_llm_json(response_text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks.

    Tries three strategies:
    1. Direct JSON parse after stripping code fences
    2. Extract first JSON object from surrounding text
    3. Raise ValueError if nothing works

    Args:
        response_text: Raw LLM response that should contain JSON

    Returns:
        Parsed dict

    Raises:
        ValueError: If no valid JSON found in response
    """
    clean = response_text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines)
    clean = clean.strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON object from surrounding text
    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(clean[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {clean[:200]}...")
