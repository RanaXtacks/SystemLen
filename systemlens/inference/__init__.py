"""Inference engine package for SystemLens."""

from systemlens.inference.merge import compute_merge_stats, merge_edges
from systemlens.inference.naming import infer_edges_from_naming

__all__ = ["infer_edges_from_naming", "merge_edges", "compute_merge_stats"]
