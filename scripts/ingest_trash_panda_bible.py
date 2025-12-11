#!/usr/bin/env python3
"""
Ingest the Trash Panda Economics Bible into the Knowledge Base.

Usage:
    python scripts/ingest_trash_panda_bible.py /path/to/bible.md

This script:
1. Reads the bible markdown file
2. Ingests it into the knowledge base with proper tags
3. Reports the number of chunks created
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from viraltracker.core.database import get_supabase_client
from viraltracker.services.knowledge_base import DocService


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_trash_panda_bible.py /path/to/bible.md")
        sys.exit(1)

    bible_path = sys.argv[1]

    if not os.path.exists(bible_path):
        print(f"Error: File not found: {bible_path}")
        sys.exit(1)

    # Read the bible content
    print(f"Reading bible from: {bible_path}")
    with open(bible_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print(f"Bible size: {len(content):,} characters, ~{len(content.split()):,} words")

    # Initialize services
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    supabase = get_supabase_client()
    doc_service = DocService(supabase=supabase, openai_api_key=api_key)

    # Check if bible already exists
    existing_docs = doc_service.list_documents()
    for doc in existing_docs:
        if "trash panda" in doc.title.lower() and "bible" in doc.title.lower():
            print(f"\nFound existing bible document: {doc.title} (ID: {doc.id})")
            response = input("Delete and re-ingest? [y/N]: ")
            if response.lower() == 'y':
                doc_service.delete_document(doc.id)
                print("Deleted existing document")
            else:
                print("Aborted")
                sys.exit(0)

    # Ingest the bible
    print("\nIngesting bible into knowledge base...")
    print("  - Chunking content (500 words per chunk, 50 word overlap)")
    print("  - Generating embeddings via OpenAI...")

    doc = doc_service.ingest(
        title="Trash Panda Economics Production Bible V6",
        content=content,
        tags=[
            "trash-panda-bible",
            "production-bible",
            "style-guide",
            "trash-panda-economics"
        ],
        tool_usage=[
            "script_generation",
            "script_review",
            "topic_discovery"
        ],
        source="Trash Panda Economics Bible V6.md",
        chunk_size=500,
        chunk_overlap=50
    )

    chunk_count = doc_service.get_chunk_count(doc.id)

    print(f"\nSuccess!")
    print(f"  Document ID: {doc.id}")
    print(f"  Title: {doc.title}")
    print(f"  Chunks created: {chunk_count}")
    print(f"  Tags: {', '.join(doc.tags)}")
    print(f"  Tool usage: {', '.join(doc.tool_usage)}")

    # Quick search test
    print("\n--- Quick Search Test ---")
    test_queries = [
        "banned words list",
        "hook formula heist",
        "character voice settings"
    ]

    for query in test_queries:
        results = doc_service.search(query, limit=1, tags=["trash-panda-bible"])
        if results:
            print(f"\n'{query}' → {results[0].similarity:.0%} match")
            print(f"  Chunk preview: {results[0].chunk_content[:100]}...")
        else:
            print(f"\n'{query}' → No results")

    print("\n✅ Bible ingestion complete!")


if __name__ == "__main__":
    main()
