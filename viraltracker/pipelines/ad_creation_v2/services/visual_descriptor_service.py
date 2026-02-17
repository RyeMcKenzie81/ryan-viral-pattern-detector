"""
Visual Descriptor Service — Gemini Flash extraction + OpenAI embedding + pgvector.

Phase 8A: Extracts structured visual descriptors from ad images using Gemini Flash,
embeds descriptor text with OpenAI text-embedding-3-small, and stores in pgvector
for similarity search (exemplar matching, "more like this").
"""

import json
import logging
from typing import Dict, List, Optional, Any
from uuid import UUID

logger = logging.getLogger(__name__)

# Descriptor fields for embedding text construction
DESCRIPTOR_FIELDS = [
    "layout_type", "color_palette", "dominant_colors", "visual_style",
    "composition", "text_placement", "text_density", "has_person",
    "has_product", "mood", "background_type",
]


class VisualDescriptorService:
    """Visual embedding extraction and similarity search."""

    async def extract_descriptors(
        self, image_data: bytes, media_type: str = "image/png"
    ) -> Dict[str, Any]:
        """Extract structured visual descriptors using Gemini Flash.

        Args:
            image_data: Raw image bytes.
            media_type: MIME type of the image.

        Returns:
            Dict with layout_type, color_palette, visual_style, composition, etc.
        """
        from viraltracker.services.gemini_service import GeminiService
        import base64

        prompt = """Analyze this ad image and extract structured visual descriptors.
Return ONLY a JSON object with these exact keys:

{
    "layout_type": "grid" | "hero" | "split" | "minimal" | "overlay",
    "color_palette": ["#hex1", "#hex2", "#hex3"],
    "dominant_colors": ["warm_red", "cool_blue", etc.],
    "visual_style": "ugc" | "studio" | "lifestyle" | "minimal" | "graphic",
    "composition": "centered" | "rule_of_thirds" | "asymmetric" | "full_bleed",
    "text_placement": "top" | "bottom" | "center" | "overlay" | "sidebar",
    "text_density": "minimal" | "moderate" | "heavy",
    "has_person": true/false,
    "has_product": true/false,
    "mood": "energetic" | "calm" | "urgent" | "professional" | "playful",
    "background_type": "solid" | "gradient" | "photo" | "pattern"
}

Return ONLY valid JSON, no other text."""

        image_b64 = base64.b64encode(image_data).decode("utf-8")
        gemini = GeminiService()

        result = await gemini.analyze_image(
            image_base64=image_b64,
            prompt=prompt,
            model="gemini-2.0-flash",
        )

        return self._parse_descriptors(result)

    async def embed_descriptors(self, descriptors: Dict[str, Any]) -> List[float]:
        """Embed descriptor text using OpenAI text-embedding-3-small.

        Args:
            descriptors: Structured visual descriptor dict.

        Returns:
            1536-dim embedding vector.
        """
        import openai
        import os

        text = self._descriptors_to_text(descriptors)

        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.embeddings.create(
            input=text,
            model="text-embedding-3-small",
        )

        return response.data[0].embedding

    async def extract_and_store(
        self,
        generated_ad_id: UUID,
        brand_id: UUID,
        image_data: bytes,
        media_type: str = "image/png",
    ) -> UUID:
        """Full pipeline: extract descriptors -> embed -> store in DB.

        Args:
            generated_ad_id: The generated ad UUID.
            brand_id: Brand UUID.
            image_data: Raw image bytes.
            media_type: MIME type.

        Returns:
            visual_embeddings.id UUID.
        """
        from viraltracker.core.database import get_supabase_client

        # Extract descriptors via Gemini Flash
        descriptors = await self.extract_descriptors(image_data, media_type)

        # Embed descriptor text via OpenAI
        embedding = await self.embed_descriptors(descriptors)

        # Store in database
        db = get_supabase_client()
        result = db.table("visual_embeddings").upsert(
            {
                "generated_ad_id": str(generated_ad_id),
                "brand_id": str(brand_id),
                "visual_descriptors": descriptors,
                "embedding": embedding,
                "descriptor_schema_version": "v1",
                "descriptor_embedding_version": "text-embedding-3-small-v1",
                "extraction_model": "gemini-2.0-flash",
            },
            on_conflict="generated_ad_id",
        ).execute()

        row = result.data[0] if result.data else {}
        ve_id = row.get("id")

        logger.info(
            f"Visual embedding stored for ad {generated_ad_id}: "
            f"id={ve_id}, descriptors={list(descriptors.keys())}"
        )
        return UUID(ve_id) if ve_id else None

    async def find_similar_ads(
        self,
        brand_id: UUID,
        embedding: List[float],
        limit: int = 10,
        exclude_ad_id: Optional[UUID] = None,
    ) -> List[Dict[str, Any]]:
        """Find similar ads via pgvector cosine similarity.

        Args:
            brand_id: Brand UUID to scope search.
            embedding: Query embedding vector (1536-dim).
            limit: Max results.
            exclude_ad_id: Optional ad to exclude from results.

        Returns:
            List of dicts with generated_ad_id, visual_descriptors, similarity.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()

        # Use pgvector cosine distance via RPC
        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        exclude_clause = ""
        if exclude_ad_id:
            exclude_clause = f"AND ve.generated_ad_id != '{exclude_ad_id}'"

        query = f"""
            SELECT
                ve.id,
                ve.generated_ad_id,
                ve.visual_descriptors,
                ve.extraction_model,
                1 - (ve.embedding <=> '{embedding_str}'::vector) AS similarity
            FROM visual_embeddings ve
            WHERE ve.brand_id = '{brand_id}'
              AND ve.embedding IS NOT NULL
              {exclude_clause}
            ORDER BY ve.embedding <=> '{embedding_str}'::vector
            LIMIT {limit}
        """

        result = db.rpc("exec_sql", {"query": query}).execute()
        return result.data or []

    async def get_embedding(self, generated_ad_id: UUID) -> Optional[List[float]]:
        """Get stored embedding for an ad.

        Args:
            generated_ad_id: The generated ad UUID.

        Returns:
            1536-dim embedding vector, or None if not found.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        result = db.table("visual_embeddings").select(
            "embedding"
        ).eq("generated_ad_id", str(generated_ad_id)).limit(1).execute()

        if result.data and result.data[0].get("embedding"):
            return result.data[0]["embedding"]
        return None

    async def get_visual_embedding_row(
        self, generated_ad_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Get full visual embedding row for an ad.

        Args:
            generated_ad_id: The generated ad UUID.

        Returns:
            Full row dict or None.
        """
        from viraltracker.core.database import get_supabase_client

        db = get_supabase_client()
        result = db.table("visual_embeddings").select(
            "*"
        ).eq("generated_ad_id", str(generated_ad_id)).limit(1).execute()

        return result.data[0] if result.data else None

    # ========================================================================
    # Internal helpers
    # ========================================================================

    def _parse_descriptors(self, raw_output: str) -> Dict[str, Any]:
        """Parse structured descriptors from Gemini output."""
        text = raw_output.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse visual descriptors JSON, using defaults")
            return self._default_descriptors()

        # Validate and fill missing fields
        result = {}
        for field in DESCRIPTOR_FIELDS:
            result[field] = parsed.get(field)

        return result

    def _default_descriptors(self) -> Dict[str, Any]:
        """Return default descriptor dict when extraction fails."""
        return {
            "layout_type": "unknown",
            "color_palette": [],
            "dominant_colors": [],
            "visual_style": "unknown",
            "composition": "unknown",
            "text_placement": "unknown",
            "text_density": "unknown",
            "has_person": False,
            "has_product": False,
            "mood": "unknown",
            "background_type": "unknown",
        }

    def _descriptors_to_text(self, descriptors: Dict[str, Any]) -> str:
        """Convert descriptor dict to text for embedding.

        Creates a natural language description that captures the visual
        characteristics in an embeddable format.
        """
        parts = []

        layout = descriptors.get("layout_type", "unknown")
        parts.append(f"Layout: {layout}")

        colors = descriptors.get("dominant_colors", [])
        if colors:
            parts.append(f"Colors: {', '.join(str(c) for c in colors)}")

        palette = descriptors.get("color_palette", [])
        if palette:
            parts.append(f"Palette: {', '.join(str(c) for c in palette)}")

        style = descriptors.get("visual_style", "unknown")
        parts.append(f"Style: {style}")

        comp = descriptors.get("composition", "unknown")
        parts.append(f"Composition: {comp}")

        text_place = descriptors.get("text_placement", "unknown")
        text_dens = descriptors.get("text_density", "unknown")
        parts.append(f"Text: {text_place} placement, {text_dens} density")

        has_person = descriptors.get("has_person", False)
        has_product = descriptors.get("has_product", False)
        parts.append(f"Person: {'yes' if has_person else 'no'}")
        parts.append(f"Product: {'yes' if has_product else 'no'}")

        mood = descriptors.get("mood", "unknown")
        parts.append(f"Mood: {mood}")

        bg = descriptors.get("background_type", "unknown")
        parts.append(f"Background: {bg}")

        return " | ".join(parts)
