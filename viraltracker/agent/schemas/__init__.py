"""
Pydantic schemas for the ViralTracker agent system.

These schemas define the data structures used by agent tools,
following pydantic-ai best practices for type safety and validation.
"""

from .image_analysis import (
    LightingType,
    BackgroundType,
    ProductAngle,
    ImageUseCase,
    ProductImageAnalysis,
    ImageSelectionCriteria,
    ImageSelectionResult,
)

__all__ = [
    "LightingType",
    "BackgroundType",
    "ProductAngle",
    "ImageUseCase",
    "ProductImageAnalysis",
    "ImageSelectionCriteria",
    "ImageSelectionResult",
]
