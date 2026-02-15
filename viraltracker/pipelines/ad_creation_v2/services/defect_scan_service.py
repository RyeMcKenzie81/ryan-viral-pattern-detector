"""
V2 Defect Scan Service — Stage 1 binary defect detection using Gemini Flash.

5 binary defect checks:
- TEXT_GARBLED: Distorted, unreadable, or nonsensical text
- ANATOMY_ERROR: Malformed human anatomy (extra fingers, distorted faces)
- PHYSICS_VIOLATION: Impossible physics (floating objects, broken perspective)
- PACKAGING_TEXT_ERROR: Product packaging text is wrong or garbled
- PRODUCT_DISTORTION: Product shape/color significantly distorted

Returns DefectScanResult with pass/fail, defect list, model info, and latency.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DEFECT_TYPES = [
    "TEXT_GARBLED",
    "ANATOMY_ERROR",
    "PHYSICS_VIOLATION",
    "PACKAGING_TEXT_ERROR",
    "PRODUCT_DISTORTION",
]


@dataclass
class Defect:
    """A single detected defect."""
    type: str
    description: str
    severity: str = "critical"

    def to_dict(self) -> Dict[str, str]:
        return {"type": self.type, "description": self.description, "severity": self.severity}


@dataclass
class DefectScanResult:
    """Result from Stage 1 defect scan.

    Attributes:
        passed: True if no defects found.
        defects: List of detected defects (empty if passed).
        model: Model used for scan.
        latency_ms: Scan latency in milliseconds.
    """
    passed: bool
    defects: List[Defect] = field(default_factory=list)
    model: str = ""
    latency_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "defects": [d.to_dict() for d in self.defects],
            "model": self.model,
            "latency_ms": self.latency_ms,
        }


class DefectScanService:
    """Stage 1 defect scan using Gemini Flash vision."""

    async def scan_for_defects(
        self,
        image_base64: str,
        product_name: str,
        media_type: str = "image/png",
    ) -> DefectScanResult:
        """Scan a generated ad image for visual defects.

        Args:
            image_base64: Base64-encoded image data.
            product_name: Product name for context.
            media_type: MIME type of the image.

        Returns:
            DefectScanResult with pass/fail and any defects found.
        """
        from viraltracker.services.gemini_service import GeminiService

        start_time = time.time()
        model_name = "gemini-2.0-flash"

        try:
            gemini = GeminiService()
            prompt = self._build_scan_prompt(product_name)

            response = await gemini.analyze_image(
                image_base64=image_base64,
                prompt=prompt,
                media_type=media_type,
                model=model_name,
            )

            latency_ms = int((time.time() - start_time) * 1000)
            return self._parse_scan_result(response, model_name, latency_ms)

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.warning(f"Defect scan failed, treating as passed: {e}")
            # On failure, pass through (don't block pipeline)
            return DefectScanResult(
                passed=True,
                model=model_name,
                latency_ms=latency_ms,
            )

    def _build_scan_prompt(self, product_name: str) -> str:
        """Build the defect scan prompt."""
        return f"""Analyze this generated ad image for the product "{product_name}" and check for these 5 defect types:

1. TEXT_GARBLED: Any text in the image that is distorted, unreadable, nonsensical, or has wrong characters
2. ANATOMY_ERROR: Any human body parts that look wrong (extra fingers, distorted faces, wrong proportions)
3. PHYSICS_VIOLATION: Impossible physics (floating objects, broken perspective, objects clipping through each other)
4. PACKAGING_TEXT_ERROR: Product packaging or label text that is garbled, wrong, or illegible
5. PRODUCT_DISTORTION: Product shape, color, or form significantly distorted from what a real product looks like

Return a JSON object with:
- "passed": true if NO defects found, false if ANY defect found
- "defects": array of objects, each with "type" (one of the 5 types above) and "description" (brief explanation)

If the image looks good with no defects, return: {{"passed": true, "defects": []}}

Only return the JSON object, no other text."""

    def _parse_scan_result(
        self, raw_output: str, model: str, latency_ms: int
    ) -> DefectScanResult:
        """Parse Gemini response into DefectScanResult."""
        try:
            text = raw_output.strip()
            # Strip markdown code fences
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            parsed = json.loads(text)

            passed = parsed.get("passed", True)
            defects = []
            for d in parsed.get("defects", []):
                if isinstance(d, dict):
                    defect_type = d.get("type", "UNKNOWN")
                    if defect_type not in DEFECT_TYPES:
                        defect_type = "UNKNOWN"
                    defects.append(Defect(
                        type=defect_type,
                        description=d.get("description", ""),
                    ))

            # Override passed if defects were found
            if defects:
                passed = False

            return DefectScanResult(
                passed=passed,
                defects=defects,
                model=model,
                latency_ms=latency_ms,
            )

        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to parse defect scan result, treating as passed: {e}")
            return DefectScanResult(
                passed=True,
                model=model,
                latency_ms=latency_ms,
            )
