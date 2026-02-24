"""HTML Surgery Pipeline — multipass v5.

Instead of reconstructing HTML from scratch, perform surgery on the
original page HTML: clean it, segment it, classify elements, add
data-slot/data-section attributes, and scope CSS.

Start at ~99% fidelity and maintain it.
"""

from .pipeline import SurgeryPipeline

__all__ = ["SurgeryPipeline"]
