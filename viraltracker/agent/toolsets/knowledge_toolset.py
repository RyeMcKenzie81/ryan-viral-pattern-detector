"""
Knowledge Base Toolset

Reusable tools for semantic search over the knowledge base.
Can be attached to any agent that needs access to domain knowledge.

Usage:
    from viraltracker.agent.toolsets import knowledge_toolset

    # Attach to an agent
    my_agent = Agent(
        model="claude-sonnet-4-5-20250929",
        deps_type=AgentDependencies,
        toolsets=[knowledge_toolset]
    )

    # Or attach at runtime
    result = await my_agent.run(prompt, deps=deps, toolsets=[knowledge_toolset])
"""

import logging
from typing import Optional
from pydantic_ai import FunctionToolset, RunContext

from ..dependencies import AgentDependencies

logger = logging.getLogger(__name__)

# Create the reusable toolset
knowledge_toolset = FunctionToolset()


@knowledge_toolset.tool
def search_knowledge(
    ctx: RunContext[AgentDependencies],
    query: str,
    tags: Optional[list[str]] = None,
    limit: int = 5
) -> str:
    """
    Search the knowledge base for relevant information.

    Use this tool to find copywriting best practices, hook formulas,
    brand guidelines, headline templates, or other domain-specific knowledge.

    The knowledge base contains curated documents on:
    - Copywriting techniques and power words
    - Hook formulas (PAS, BAB, etc.)
    - Headline templates
    - Brand voice guidelines
    - Industry-specific knowledge

    Args:
        query: Natural language description of what you're looking for.
               Example: "hook formulas for weight loss products"
        tags: Optional filter by category. Valid tags include:
              - 'copywriting' - General copywriting techniques
              - 'hooks' - Hook and headline formulas
              - 'brand' - Brand guidelines and voice
              - 'templates' - Reusable templates
              If not specified, searches all documents.
        limit: Maximum number of results to return (default 5)

    Returns:
        Relevant knowledge passages with their sources, formatted for use
        in content generation. Returns "No relevant knowledge found." if
        no matching documents exist.

    Examples:
        - search_knowledge("hook formulas for urgency")
        - search_knowledge("power words for headlines", tags=["copywriting"])
        - search_knowledge("emotional triggers", limit=3)
    """
    if not hasattr(ctx.deps, 'docs') or ctx.deps.docs is None:
        return "Knowledge base not configured. Set OPENAI_API_KEY to enable."

    try:
        results = ctx.deps.docs.search(query, limit=limit, tags=tags)

        if not results:
            return "No relevant knowledge found for this query."

        # Format results for LLM consumption
        formatted = []
        for r in results:
            # Include title and similarity score for context
            header = f"## {r.title} (relevance: {r.similarity:.0%})"
            formatted.append(f"{header}\n{r.chunk_content}")

        return "\n\n---\n\n".join(formatted)

    except Exception as e:
        logger.error(f"Knowledge search failed: {e}")
        return f"Knowledge search error: {str(e)}"


@knowledge_toolset.tool
def get_knowledge_by_category(
    ctx: RunContext[AgentDependencies],
    category: str
) -> str:
    """
    Get all knowledge documents in a specific category.

    Use this when you need comprehensive information about a topic,
    rather than searching for specific concepts.

    Args:
        category: The category to retrieve. Valid categories:
                  - 'copywriting' - Copywriting techniques and best practices
                  - 'hooks' - Hook formulas and templates
                  - 'brand' - Brand voice and guidelines
                  - 'templates' - Reusable content templates
                  - 'products' - Product-specific knowledge

    Returns:
        All document content in that category, or a message if no
        documents exist for the category.

    Examples:
        - get_knowledge_by_category("hooks")
        - get_knowledge_by_category("copywriting")
    """
    if not hasattr(ctx.deps, 'docs') or ctx.deps.docs is None:
        return "Knowledge base not configured. Set OPENAI_API_KEY to enable."

    try:
        docs = ctx.deps.docs.get_by_tags([category])

        if not docs:
            return f"No documents found in category: {category}"

        formatted = []
        for doc in docs:
            formatted.append(f"## {doc.title}\n\n{doc.content}")

        return "\n\n---\n\n".join(formatted)

    except Exception as e:
        logger.error(f"Knowledge retrieval failed: {e}")
        return f"Knowledge retrieval error: {str(e)}"


@knowledge_toolset.tool
def list_knowledge_categories(
    ctx: RunContext[AgentDependencies]
) -> str:
    """
    List all available knowledge categories and document counts.

    Use this to understand what knowledge is available before searching.

    Returns:
        Summary of available categories, document counts, and tool usages.
    """
    if not hasattr(ctx.deps, 'docs') or ctx.deps.docs is None:
        return "Knowledge base not configured. Set OPENAI_API_KEY to enable."

    try:
        stats = ctx.deps.docs.get_stats()

        if stats["document_count"] == 0:
            return "Knowledge base is empty. No documents have been uploaded yet."

        lines = [
            f"Knowledge Base Statistics:",
            f"- Total documents: {stats['document_count']}",
            f"- Total chunks: {stats['chunk_count']}",
            "",
            "Available categories (tags):",
        ]

        for tag in stats["tags"]:
            lines.append(f"  - {tag}")

        if stats["tool_usages"]:
            lines.append("")
            lines.append("Tools using knowledge base:")
            for tool in stats["tool_usages"]:
                lines.append(f"  - {tool}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Knowledge stats failed: {e}")
        return f"Knowledge stats error: {str(e)}"
