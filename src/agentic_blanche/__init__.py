"""Theory-aware exact search for perfect Mondrian dissections."""

from agentic_blanche.graph import PlaneGraph, RootedPlaneGraph
from agentic_blanche.presentations import (
    KirchhoffPresentation,
    build_adaptive_cycle_presentation,
    build_bilinear_presentation,
    build_edge_current_presentation,
)
from agentic_blanche.workflow import SearchConfig, SearchWorkflow, SieveMode

__all__ = [
    "KirchhoffPresentation",
    "PlaneGraph",
    "RootedPlaneGraph",
    "SearchConfig",
    "SearchWorkflow",
    "SieveMode",
    "build_adaptive_cycle_presentation",
    "build_bilinear_presentation",
    "build_edge_current_presentation",
]

__version__ = "0.4.0"
