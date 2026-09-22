"""Base SourceAdapter interface."""

from abc import ABC, abstractmethod
from typing import Any

from systemlens.models import Edge, Node


class SourceAdapter(ABC):
    """Abstract base class for all source introspectors/analyzers."""

    @abstractmethod
    def extract_nodes(self) -> list[Node]:
        """Extract and return list of graph nodes."""
        pass

    @abstractmethod
    def extract_edges(self) -> list[Edge]:
        """Extract and return list of graph edges."""
        pass

    @abstractmethod
    def extract_raw_catalog(self) -> dict[str, Any]:
        """Extract raw unlinked catalog data for inspection/export."""
        pass
