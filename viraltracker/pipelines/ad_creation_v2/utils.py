"""Shared utilities for Ad Creation V2 pipeline nodes."""

from typing import Any
from uuid import UUID


def stringify_uuids(obj: Any) -> Any:
    """Recursively convert UUID values to strings in dicts/lists."""
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: stringify_uuids(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [stringify_uuids(v) for v in obj]
    return obj
