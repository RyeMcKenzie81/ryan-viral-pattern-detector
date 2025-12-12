"""
Comparison utilities for product-level competitive analysis.

Aggregates advertising_structure data from ad analyses to enable
side-by-side comparison of brand vs competitor products.
"""

import logging
from typing import List, Dict, Any, Optional
from collections import Counter

logger = logging.getLogger(__name__)


def extract_advertising_structure(analyses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extract advertising_structure from raw_response in analysis records.

    Args:
        analyses: List of analysis records with raw_response field

    Returns:
        List of advertising_structure dicts (filters out analyses without this field)
    """
    structures = []
    for analysis in analyses:
        raw = analysis.get("raw_response", {})
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                continue

        ad_structure = raw.get("advertising_structure")
        if ad_structure:
            structures.append(ad_structure)

    return structures


def aggregate_awareness_levels(structures: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Count distribution of awareness levels across analyses.

    Args:
        structures: List of advertising_structure dicts

    Returns:
        Dict mapping awareness_level to count
    """
    levels = []
    for s in structures:
        level = s.get("awareness_level")
        if level:
            # Handle both string and list cases
            if isinstance(level, list):
                levels.extend(level)
            else:
                levels.append(level)
    return dict(Counter(levels))


def aggregate_advertising_angles(structures: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Count distribution of advertising angles across analyses.

    Args:
        structures: List of advertising_structure dicts

    Returns:
        Dict mapping advertising_angle to count
    """
    angles = []
    for s in structures:
        angle = s.get("advertising_angle")
        if angle:
            # Handle both string and list cases (AI sometimes returns multiple angles)
            if isinstance(angle, list):
                angles.extend(angle)
            else:
                angles.append(angle)
    return dict(Counter(angles))


def aggregate_emotional_drivers(structures: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Count distribution of emotional drivers from messaging angles.

    Args:
        structures: List of advertising_structure dicts

    Returns:
        Dict mapping emotional_driver to count
    """
    drivers = []
    for s in structures:
        for angle in s.get("messaging_angles", []):
            if angle.get("emotional_driver"):
                drivers.append(angle["emotional_driver"])
    return dict(Counter(drivers))


def aggregate_benefits(structures: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate benefits highlighted across analyses.

    Args:
        structures: List of advertising_structure dicts

    Returns:
        Dict mapping benefit name to {count, specificity_counts, has_proof_count}
    """
    benefits = {}
    for s in structures:
        for b in s.get("benefits_highlighted", []):
            name = b.get("benefit", "").lower().strip()
            if not name:
                continue

            if name not in benefits:
                benefits[name] = {
                    "count": 0,
                    "specificity": {"high": 0, "medium": 0, "low": 0},
                    "with_proof": 0,
                    "with_timeframe": 0
                }

            benefits[name]["count"] += 1
            spec = b.get("specificity", "").lower()
            if spec in benefits[name]["specificity"]:
                benefits[name]["specificity"][spec] += 1
            if b.get("proof_provided") and b["proof_provided"] not in [None, "null", "none", ""]:
                benefits[name]["with_proof"] += 1
            if b.get("timeframe") and b["timeframe"] not in [None, "null", "none", ""]:
                benefits[name]["with_timeframe"] += 1

    return benefits


def aggregate_features(structures: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate features mentioned across analyses.

    Args:
        structures: List of advertising_structure dicts

    Returns:
        Dict mapping feature name to {count, differentiation_count, positionings}
    """
    features = {}
    for s in structures:
        for f in s.get("features_mentioned", []):
            name = f.get("feature", "").lower().strip()
            if not name:
                continue

            if name not in features:
                features[name] = {
                    "count": 0,
                    "differentiation_count": 0,
                    "positionings": []
                }

            features[name]["count"] += 1
            if f.get("differentiation"):
                features[name]["differentiation_count"] += 1
            if f.get("positioning"):
                features[name]["positionings"].append(f["positioning"])

    return features


def aggregate_objections(structures: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Aggregate objections addressed across analyses.

    Args:
        structures: List of advertising_structure dicts

    Returns:
        Dict mapping objection to {count, methods, responses}
    """
    objections = {}
    for s in structures:
        for o in s.get("objections_addressed", []):
            name = o.get("objection", "").lower().strip()
            if not name:
                continue

            if name not in objections:
                objections[name] = {
                    "count": 0,
                    "methods": [],
                    "responses": []
                }

            objections[name]["count"] += 1
            if o.get("method"):
                objections[name]["methods"].append(o["method"])
            if o.get("response"):
                objections[name]["responses"].append(o["response"])

    return objections


def aggregate_messaging_angles(structures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Aggregate messaging angles with their benefits and emotional drivers.

    Args:
        structures: List of advertising_structure dicts

    Returns:
        List of {benefit, angle, framing, emotional_driver, count}
    """
    # Group by benefit + angle combination
    angle_counts = {}
    for s in structures:
        for ma in s.get("messaging_angles", []):
            benefit = ma.get("benefit", "").lower().strip()
            angle = ma.get("angle", "").lower().strip()
            key = f"{benefit}|{angle}"

            if key not in angle_counts:
                angle_counts[key] = {
                    "benefit": benefit,
                    "angle": angle,
                    "framings": [],
                    "emotional_drivers": [],
                    "count": 0
                }

            angle_counts[key]["count"] += 1
            if ma.get("framing"):
                angle_counts[key]["framings"].append(ma["framing"])
            if ma.get("emotional_driver"):
                angle_counts[key]["emotional_drivers"].append(ma["emotional_driver"])

    # Convert to list and sort by count
    result = list(angle_counts.values())
    result.sort(key=lambda x: x["count"], reverse=True)
    return result


def build_product_comparison(
    brand_analyses: List[Dict[str, Any]],
    competitor_analyses: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Build complete comparison data between brand and competitor product.

    Args:
        brand_analyses: List of analysis records for brand product
        competitor_analyses: List of analysis records for competitor product

    Returns:
        Dict with all comparison data for UI rendering
    """
    brand_structures = extract_advertising_structure(brand_analyses)
    competitor_structures = extract_advertising_structure(competitor_analyses)

    logger.info(
        f"Building comparison: {len(brand_structures)} brand structures, "
        f"{len(competitor_structures)} competitor structures"
    )

    return {
        "brand": {
            "total_analyses": len(brand_analyses),
            "with_ad_structure": len(brand_structures),
            "awareness_levels": aggregate_awareness_levels(brand_structures),
            "advertising_angles": aggregate_advertising_angles(brand_structures),
            "emotional_drivers": aggregate_emotional_drivers(brand_structures),
            "benefits": aggregate_benefits(brand_structures),
            "features": aggregate_features(brand_structures),
            "objections": aggregate_objections(brand_structures),
            "messaging_angles": aggregate_messaging_angles(brand_structures),
        },
        "competitor": {
            "total_analyses": len(competitor_analyses),
            "with_ad_structure": len(competitor_structures),
            "awareness_levels": aggregate_awareness_levels(competitor_structures),
            "advertising_angles": aggregate_advertising_angles(competitor_structures),
            "emotional_drivers": aggregate_emotional_drivers(competitor_structures),
            "benefits": aggregate_benefits(competitor_structures),
            "features": aggregate_features(competitor_structures),
            "objections": aggregate_objections(competitor_structures),
            "messaging_angles": aggregate_messaging_angles(competitor_structures),
        }
    }


def calculate_gaps(comparison: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate gaps/differences between brand and competitor.

    Args:
        comparison: Output from build_product_comparison

    Returns:
        Dict highlighting key differences and opportunities
    """
    gaps = {
        "awareness_gaps": [],
        "angle_gaps": [],
        "benefit_gaps": [],
        "objection_gaps": [],
        "emotional_driver_gaps": []
    }

    brand = comparison["brand"]
    competitor = comparison["competitor"]

    # Awareness level gaps
    all_levels = set(brand["awareness_levels"].keys()) | set(competitor["awareness_levels"].keys())
    for level in all_levels:
        brand_count = brand["awareness_levels"].get(level, 0)
        comp_count = competitor["awareness_levels"].get(level, 0)
        if comp_count > brand_count * 2 and comp_count >= 3:
            gaps["awareness_gaps"].append({
                "level": level,
                "brand_count": brand_count,
                "competitor_count": comp_count,
                "insight": f"Competitor focuses more on {level} audience"
            })

    # Advertising angle gaps
    all_angles = set(brand["advertising_angles"].keys()) | set(competitor["advertising_angles"].keys())
    for angle in all_angles:
        brand_count = brand["advertising_angles"].get(angle, 0)
        comp_count = competitor["advertising_angles"].get(angle, 0)
        if comp_count >= 3 and brand_count == 0:
            gaps["angle_gaps"].append({
                "angle": angle,
                "brand_count": brand_count,
                "competitor_count": comp_count,
                "insight": f"Competitor uses {angle} angle, you don't"
            })

    # Benefit gaps
    all_benefits = set(brand["benefits"].keys()) | set(competitor["benefits"].keys())
    for benefit in all_benefits:
        brand_data = brand["benefits"].get(benefit, {"count": 0})
        comp_data = competitor["benefits"].get(benefit, {"count": 0})
        if comp_data["count"] >= 3 and brand_data["count"] == 0:
            gaps["benefit_gaps"].append({
                "benefit": benefit,
                "brand_count": brand_data["count"],
                "competitor_count": comp_data["count"],
                "insight": f"Competitor highlights '{benefit}', you don't"
            })

    # Objection gaps
    all_objections = set(brand["objections"].keys()) | set(competitor["objections"].keys())
    for objection in all_objections:
        brand_data = brand["objections"].get(objection, {"count": 0})
        comp_data = competitor["objections"].get(objection, {"count": 0})
        if comp_data["count"] >= 2 and brand_data["count"] == 0:
            gaps["objection_gaps"].append({
                "objection": objection,
                "brand_count": brand_data["count"],
                "competitor_count": comp_data["count"],
                "insight": f"Competitor addresses '{objection}', you don't"
            })

    # Emotional driver gaps
    all_drivers = set(brand["emotional_drivers"].keys()) | set(competitor["emotional_drivers"].keys())
    for driver in all_drivers:
        brand_count = brand["emotional_drivers"].get(driver, 0)
        comp_count = competitor["emotional_drivers"].get(driver, 0)
        if comp_count >= 3 and brand_count == 0:
            gaps["emotional_driver_gaps"].append({
                "driver": driver,
                "brand_count": brand_count,
                "competitor_count": comp_count,
                "insight": f"Competitor uses {driver} emotional driver, you don't"
            })

    return gaps
