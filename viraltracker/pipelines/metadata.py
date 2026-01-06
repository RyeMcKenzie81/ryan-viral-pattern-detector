"""
Node Metadata for Pipeline Visualization.

This module provides the NodeMetadata class for annotating pipeline nodes
with information useful for visualization and debugging:
- Input/output state fields
- Service dependencies
- LLM usage (model, purpose)

Usage:
    from viraltracker.pipelines.metadata import NodeMetadata

    @dataclass
    class MyNode(BaseNode[MyState]):
        '''Node description.'''

        metadata: ClassVar[NodeMetadata] = NodeMetadata(
            inputs=["field1", "field2"],
            outputs=["result_field"],
            services=["my_service.do_something"],
            llm="Claude Sonnet",
            llm_purpose="Score relevance of items",
        )

        async def run(self, ctx): ...
"""

from dataclasses import dataclass, field
from typing import List, Optional, ClassVar


@dataclass
class NodeMetadata:
    """
    Metadata for pipeline node visualization.

    Attributes:
        inputs: State fields read by this node
        outputs: State fields written by this node
        services: Service methods called (e.g., "facebook.search_ads")
        llm: LLM model used, if any (e.g., "Claude Sonnet", "Gemini 3 Pro")
        llm_purpose: What the LLM does in this node
    """

    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    llm: Optional[str] = None
    llm_purpose: Optional[str] = None

    @property
    def uses_llm(self) -> bool:
        """Check if this node uses an LLM."""
        return self.llm is not None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "inputs": self.inputs,
            "outputs": self.outputs,
            "services": self.services,
            "llm": self.llm,
            "llm_purpose": self.llm_purpose,
            "uses_llm": self.uses_llm,
        }


def get_node_metadata(node_class) -> Optional[NodeMetadata]:
    """
    Extract metadata from a node class if available.

    Args:
        node_class: A BaseNode subclass

    Returns:
        NodeMetadata if the node has metadata defined, None otherwise
    """
    return getattr(node_class, "metadata", None)


def get_pipeline_llm_summary(node_classes: List) -> dict:
    """
    Get a summary of LLM usage across a pipeline's nodes.

    Args:
        node_classes: List of node classes in the pipeline

    Returns:
        Dict with llm_count, llm_models, and nodes_with_llm
    """
    llm_nodes = []
    llm_models = set()

    for node_class in node_classes:
        metadata = get_node_metadata(node_class)
        if metadata and metadata.uses_llm:
            llm_nodes.append(node_class.__name__)
            llm_models.add(metadata.llm)

    return {
        "llm_count": len(llm_nodes),
        "llm_models": list(llm_models),
        "nodes_with_llm": llm_nodes,
    }
