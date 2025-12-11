#!/usr/bin/env python3
"""
Test that topic discovery uses the real bible context from KB.

Usage:
    python scripts/test_topic_discovery_with_bible.py
"""

import sys
import os
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from viraltracker.core.database import get_supabase_client
from viraltracker.services.knowledge_base import DocService
from viraltracker.services.content_pipeline.services.topic_service import TopicDiscoveryService
from uuid import UUID


async def main():
    print("=" * 60)
    print("Testing Topic Discovery with Real Bible Context")
    print("=" * 60)

    # Initialize services
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    supabase = get_supabase_client()
    doc_service = DocService(supabase=supabase, openai_api_key=api_key)
    topic_service = TopicDiscoveryService(
        supabase_client=supabase,
        docs_service=doc_service
    )

    # Get the Trash Panda Economics brand ID
    result = supabase.table("brands").select("id").eq(
        "slug", "trash-panda-economics"
    ).execute()

    if not result.data:
        print("Error: Trash Panda Economics brand not found")
        sys.exit(1)

    brand_id = UUID(result.data[0]["id"])
    print(f"\nBrand ID: {brand_id}")

    # Test getting bible context
    print("\n--- Testing Bible Context Retrieval ---")
    context = await topic_service.get_bible_context(brand_id)

    if "DocService not configured" in context or "Trash Panda Economics is a YouTube channel" in context[:100]:
        print("WARNING: Using fallback context (DocService not working properly)")
        print(f"Context preview: {context[:200]}...")
    else:
        print(f"SUCCESS: Retrieved real bible context!")
        print(f"Context length: {len(context):,} characters")
        print(f"Context preview: {context[:300]}...")

    # Test topic discovery with 3 topics (quick test)
    print("\n--- Testing Topic Discovery (3 topics) ---")
    topics = await topic_service.discover_topics(
        brand_id=brand_id,
        num_topics=3,
        focus_areas=["inflation", "Federal Reserve"]
    )

    print(f"\nGenerated {len(topics)} topics:")
    for i, topic in enumerate(topics, 1):
        print(f"\n{i}. {topic.get('title')}")
        print(f"   {topic.get('description', '')[:100]}...")
        if topic.get('hook_options'):
            print(f"   Hooks: {len(topic.get('hook_options', []))} options")

    print("\n✅ Topic discovery test complete!")


if __name__ == "__main__":
    asyncio.run(main())
