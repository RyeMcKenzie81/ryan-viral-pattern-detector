#!/usr/bin/env python3
"""
Ingest the Comic Production Knowledge Base into the Knowledge Base.

This script parses 20 comic production documents and ingests them
as separate entries with appropriate tags for RAG retrieval.

Usage:
    python scripts/ingest_comic_kb.py [--clear-existing]

Options:
    --clear-existing    Delete all existing comic-production documents before ingesting
"""

import sys
import os
import re
import argparse

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from viraltracker.core.database import get_supabase_client
from viraltracker.services.knowledge_base import DocService


def parse_comic_kb_file(filepath: str) -> list[dict]:
    """
    Parse the comic KB file into individual documents.

    Args:
        filepath: Path to the comic KB file

    Returns:
        List of document dicts with keys: document_id, category, tags, content, title
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split by the document separator pattern
    # Pattern: Line of === followed by DOCUMENT:
    doc_pattern = r'={50,}\nDOCUMENT:\s*(\S+)\nCATEGORY:\s*(.+)\nTAGS:\s*(.+)\n={20,}\n'

    # Find all document headers and their positions
    matches = list(re.finditer(doc_pattern, content))

    documents = []
    for i, match in enumerate(matches):
        document_id = match.group(1).strip()
        category = match.group(2).strip()
        tags_raw = match.group(3).strip()

        # Parse comma-separated tags
        tags = [t.strip() for t in tags_raw.split(',') if t.strip()]

        # Get content between this match end and next match start (or EOF)
        content_start = match.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        doc_content = content[content_start:content_end].strip()

        # Create title from document_id
        title = document_id.replace('_', ' ').title()

        documents.append({
            'document_id': document_id,
            'category': category,
            'tags': tags,
            'content': doc_content,
            'title': title
        })

    return documents


def main():
    parser = argparse.ArgumentParser(description='Ingest Comic Production KB')
    parser.add_argument('--clear-existing', action='store_true',
                        help='Delete all existing comic-production documents first')
    args = parser.parse_args()

    # KB file path
    kb_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'data', 'comic_production_kb.txt'
    )

    if not os.path.exists(kb_path):
        print(f"Error: File not found: {kb_path}")
        sys.exit(1)

    # Initialize services
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY not set")
        sys.exit(1)

    supabase = get_supabase_client()
    doc_service = DocService(supabase=supabase, openai_api_key=api_key)

    # Check for existing comic-production documents
    existing_docs = doc_service.list_documents()
    comic_docs = [d for d in existing_docs if 'comic-production' in d.tags]

    if comic_docs:
        print(f"\nFound {len(comic_docs)} existing comic-production documents")
        if args.clear_existing:
            print("Deleting existing documents...")
            for doc in comic_docs:
                doc_service.delete_document(doc.id)
                print(f"  Deleted: {doc.title}")
            print(f"Deleted {len(comic_docs)} documents")
        else:
            print("Use --clear-existing to delete and re-ingest")
            response = input("Continue and add duplicates? [y/N]: ")
            if response.lower() != 'y':
                print("Aborted")
                sys.exit(0)

    # Parse the KB file
    print(f"\nParsing KB file: {kb_path}")
    documents = parse_comic_kb_file(kb_path)
    print(f"Found {len(documents)} documents to ingest")

    # Define tool usage based on category
    tool_usage_map = {
        'core-philosophy': ['comic_planning', 'comic_evaluation', 'comic_revision'],
        'craft-pillars': ['comic_planning', 'comic_evaluation'],
        'patterns': ['comic_planning', 'comic_revision'],
        'platforms': ['comic_planning'],
        'evaluation': ['comic_evaluation', 'comic_revision'],
        'examples': ['comic_planning', 'comic_evaluation', 'comic_revision'],
        'meta': ['comic_planning', 'comic_evaluation', 'comic_revision']
    }

    # Ingest each document
    print("\nIngesting documents...")
    total_chunks = 0

    for i, doc in enumerate(documents, 1):
        # Build tags: collection identifier + category + document tags
        tags = ['comic-production', doc['category']] + doc['tags']

        # Get tool usage based on category
        tool_usage = tool_usage_map.get(doc['category'], ['comic_planning'])

        print(f"\n[{i}/{len(documents)}] {doc['title']}")
        print(f"  Category: {doc['category']}")
        print(f"  Tags: {', '.join(doc['tags'])}")
        print(f"  Content: {len(doc['content'])} chars, ~{len(doc['content'].split())} words")

        # Ingest with smaller chunk size for focused retrieval
        # These documents are relatively short, so 300 words per chunk is reasonable
        ingested = doc_service.ingest(
            title=doc['title'],
            content=doc['content'],
            tags=tags,
            tool_usage=tool_usage,
            source=f"comic_production_kb/{doc['document_id']}",
            chunk_size=300,  # Smaller chunks for precise retrieval
            chunk_overlap=30
        )

        chunk_count = doc_service.get_chunk_count(ingested.id)
        total_chunks += chunk_count
        print(f"  Created: {chunk_count} chunks")

    # Summary
    print(f"\n{'='*60}")
    print("INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"Documents ingested: {len(documents)}")
    print(f"Total chunks created: {total_chunks}")
    print(f"Collection tag: comic-production")

    # Quick search test
    print("\n--- Quick Search Test ---")
    test_queries = [
        ("4-panel structure", ["comic-production"]),
        ("emotional payoff AHA HA OOF", ["comic-production"]),
        ("weak punchline fix", ["comic-production"]),
        ("Instagram carousel", ["comic-production"])
    ]

    for query, tags in test_queries:
        results = doc_service.search(query, limit=2, tags=tags)
        if results:
            print(f"\n'{query}':")
            for r in results:
                print(f"  {r.similarity:.0%} - {r.title}")
        else:
            print(f"\n'{query}' → No results")

    print("\nComic Production KB ingestion complete!")


if __name__ == "__main__":
    main()
