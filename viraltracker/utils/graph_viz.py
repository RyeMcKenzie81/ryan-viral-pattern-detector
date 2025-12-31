"""
Graph Visualization Utility for Pydantic-Graph Pipelines.

Provides tools to export Mermaid diagrams for all pipeline graphs,
both as code (for documentation) and as images (for UI display).

Usage:
    # Programmatic
    from viraltracker.utils.graph_viz import get_graph_mermaid_code, export_all_graphs

    code = get_graph_mermaid_code("brand_onboarding")
    export_all_graphs("./diagrams")

    # CLI
    python -m viraltracker.utils.graph_viz --help
    python -m viraltracker.utils.graph_viz --all --output ./diagrams
    python -m viraltracker.utils.graph_viz --graph brand_onboarding --code
"""

import argparse
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


def _get_pipeline_registry() -> Dict[str, Dict[str, Any]]:
    """
    Lazy-load pipeline registry to avoid circular imports.

    Returns:
        Dictionary mapping pipeline names to their graph objects and start nodes.
    """
    from viraltracker.pipelines import (
        brand_onboarding_graph,
        template_ingestion_graph,
        belief_plan_execution_graph,
        reddit_sentiment_graph,
        ScrapeAdsNode,
        TemplateScrapeAdsNode,
        LoadPlanNode,
        ScrapeRedditNode,
    )

    return {
        "brand_onboarding": {
            "graph": brand_onboarding_graph,
            "start_node": ScrapeAdsNode,
            "description": "Scrape ads, analyze with AI, extract brand insights",
            "nodes": ["ScrapeAdsNode", "DownloadAssetsNode", "AnalyzeImagesNode",
                      "AnalyzeVideosNode", "SynthesizeNode"],
        },
        "template_ingestion": {
            "graph": template_ingestion_graph,
            "start_node": TemplateScrapeAdsNode,
            "description": "Scrape ads, queue for human review, create templates",
            "nodes": ["ScrapeAdsNode", "DownloadAssetsNode", "QueueForReviewNode"],
        },
        "belief_plan_execution": {
            "graph": belief_plan_execution_graph,
            "start_node": LoadPlanNode,
            "description": "Execute Phase 1-2 belief testing plans",
            "nodes": ["LoadPlanNode", "BuildPromptsNode", "GenerateImagesNode", "ReviewAdsNode"],
        },
        "reddit_sentiment": {
            "graph": reddit_sentiment_graph,
            "start_node": ScrapeRedditNode,
            "description": "Scrape Reddit, analyze sentiment, extract quotes",
            "nodes": ["ScrapeRedditNode", "EngagementFilterNode", "RelevanceFilterNode",
                      "SignalFilterNode", "IntentScoreNode", "TopSelectionNode",
                      "CategorizeNode", "SaveNode"],
        },
    }


# Lazy-loaded registry
PIPELINE_REGISTRY: Dict[str, Dict[str, Any]] = {}


def _ensure_registry() -> Dict[str, Dict[str, Any]]:
    """Ensure the pipeline registry is loaded."""
    global PIPELINE_REGISTRY
    if not PIPELINE_REGISTRY:
        PIPELINE_REGISTRY = _get_pipeline_registry()
    return PIPELINE_REGISTRY


def get_all_graphs_info() -> List[Dict[str, Any]]:
    """
    Get information about all registered pipeline graphs.

    Returns:
        List of dicts with name, description, node_count, nodes, start_node
    """
    registry = _ensure_registry()

    return [
        {
            "name": name,
            "description": info["description"],
            "node_count": len(info["nodes"]),
            "nodes": info["nodes"],
            "start_node": info["nodes"][0] if info["nodes"] else None,
        }
        for name, info in registry.items()
    ]


def get_graph_mermaid_code(
    graph_name: str,
    direction: str = "LR",
    include_notes: bool = True,
) -> str:
    """
    Get Mermaid diagram code for a specific graph.

    Args:
        graph_name: Name of the pipeline graph
        direction: Diagram direction ('LR', 'TB', 'RL', 'BT')
        include_notes: Whether to include node docstrings as notes

    Returns:
        Mermaid diagram code as string

    Raises:
        ValueError: If graph_name is not found in registry
    """
    registry = _ensure_registry()

    if graph_name not in registry:
        available = ", ".join(registry.keys())
        raise ValueError(f"Unknown graph '{graph_name}'. Available: {available}")

    info = registry[graph_name]
    graph = info["graph"]
    start_node = info["start_node"]

    return graph.mermaid_code(
        start_node=start_node(),
        direction=direction,
        notes=include_notes,
    )


def export_graph_image(
    graph_name: str,
    output_path: str,
    format: str = "png",
    direction: str = "LR",
) -> Path:
    """
    Export a graph as an image file.

    Args:
        graph_name: Name of the pipeline graph
        output_path: Path to save the image (without extension)
        format: Image format ('png', 'svg', 'jpeg', 'webp', 'pdf')
        direction: Diagram direction ('LR', 'TB', 'RL', 'BT')

    Returns:
        Path to the saved image file

    Raises:
        ValueError: If graph_name is not found or format is invalid
    """
    registry = _ensure_registry()

    if graph_name not in registry:
        available = ", ".join(registry.keys())
        raise ValueError(f"Unknown graph '{graph_name}'. Available: {available}")

    valid_formats = {"png", "svg", "jpeg", "webp", "pdf"}
    if format not in valid_formats:
        raise ValueError(f"Invalid format '{format}'. Valid: {valid_formats}")

    info = registry[graph_name]
    graph = info["graph"]
    start_node = info["start_node"]

    # Ensure output path has correct extension
    output = Path(output_path)
    if output.suffix.lower() != f".{format}":
        output = output.with_suffix(f".{format}")

    # Create parent directory if needed
    output.parent.mkdir(parents=True, exist_ok=True)

    # Generate and save image
    graph.mermaid_save(
        path=str(output),
        start_node=start_node(),
        direction=direction,
        image_type=format,
    )

    logger.info(f"Exported {graph_name} to {output}")
    return output


def get_graph_image_bytes(
    graph_name: str,
    format: str = "png",
    direction: str = "LR",
) -> bytes:
    """
    Get graph image as bytes (for Streamlit display).

    Args:
        graph_name: Name of the pipeline graph
        format: Image format ('png', 'svg', 'jpeg', 'webp')
        direction: Diagram direction ('LR', 'TB', 'RL', 'BT')

    Returns:
        Image bytes
    """
    registry = _ensure_registry()

    if graph_name not in registry:
        available = ", ".join(registry.keys())
        raise ValueError(f"Unknown graph '{graph_name}'. Available: {available}")

    info = registry[graph_name]
    graph = info["graph"]
    start_node = info["start_node"]

    return graph.mermaid_image(
        start_node=start_node(),
        direction=direction,
        image_type=format,
    )


def export_all_graphs(
    output_dir: str,
    format: str = "png",
    direction: str = "LR",
) -> List[Path]:
    """
    Export all pipeline graphs as images.

    Args:
        output_dir: Directory to save images
        format: Image format ('png', 'svg', 'jpeg', 'webp', 'pdf')
        direction: Diagram direction ('LR', 'TB', 'RL', 'BT')

    Returns:
        List of paths to saved image files
    """
    registry = _ensure_registry()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for name in registry:
        try:
            file_path = export_graph_image(
                graph_name=name,
                output_path=str(output_path / name),
                format=format,
                direction=direction,
            )
            saved_files.append(file_path)
        except Exception as e:
            logger.error(f"Failed to export {name}: {e}")

    return saved_files


def get_node_details(graph_name: str) -> List[Dict[str, Any]]:
    """
    Get detailed information about nodes in a graph.

    Args:
        graph_name: Name of the pipeline graph

    Returns:
        List of dicts with node name, docstring, and position
    """
    registry = _ensure_registry()

    if graph_name not in registry:
        available = ", ".join(registry.keys())
        raise ValueError(f"Unknown graph '{graph_name}'. Available: {available}")

    info = registry[graph_name]
    nodes = info["nodes"]

    # Import the actual node classes to get docstrings
    node_details = []
    for i, node_name in enumerate(nodes):
        node_details.append({
            "name": node_name,
            "position": i + 1,
            "is_start": i == 0,
            "is_end": i == len(nodes) - 1,
        })

    return node_details


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Export Mermaid diagrams for ViralTracker pipeline graphs"
    )
    parser.add_argument(
        "--graph", "-g",
        help="Specific graph to export (default: all)",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Export all graphs",
    )
    parser.add_argument(
        "--output", "-o",
        default="./diagrams",
        help="Output directory for images (default: ./diagrams)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["png", "svg", "jpeg", "webp", "pdf"],
        default="png",
        help="Image format (default: png)",
    )
    parser.add_argument(
        "--direction", "-d",
        choices=["LR", "TB", "RL", "BT"],
        default="LR",
        help="Diagram direction (default: LR)",
    )
    parser.add_argument(
        "--code", "-c",
        action="store_true",
        help="Print Mermaid code instead of saving image",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available graphs",
    )

    args = parser.parse_args()

    # List mode
    if args.list:
        print("\nAvailable Pipeline Graphs:")
        print("-" * 60)
        for info in get_all_graphs_info():
            print(f"\n  {info['name']} ({info['node_count']} nodes)")
            print(f"    {info['description']}")
            print(f"    Nodes: {' → '.join(info['nodes'])}")
        print()
        return

    # Code mode
    if args.code:
        if not args.graph:
            print("Error: --code requires --graph to be specified")
            return
        code = get_graph_mermaid_code(args.graph, direction=args.direction)
        print(code)
        return

    # Export mode
    if args.all:
        paths = export_all_graphs(
            output_dir=args.output,
            format=args.format,
            direction=args.direction,
        )
        print(f"\nExported {len(paths)} graphs to {args.output}/")
        for p in paths:
            print(f"  - {p.name}")
    elif args.graph:
        path = export_graph_image(
            graph_name=args.graph,
            output_path=f"{args.output}/{args.graph}",
            format=args.format,
            direction=args.direction,
        )
        print(f"Exported to {path}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
