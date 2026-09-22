"""Core data models for SystemLens graph representation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    TABLE = "table"
    VIEW = "view"
    PARTITION = "partition"
    FUNCTION = "function"
    FILE = "file"


class EdgeType(str, Enum):
    DECLARED_FK = "declared_fk"
    INFERRED_NAMING = "inferred_naming"
    STATIC_SQL_STRING = "static_sql_string"
    ORM_CALL = "orm_call"
    DYNAMIC_UNRESOLVED = "dynamic_unresolved"
    STRUCTURAL_BELONGS_TO = "structural_belongs_to"


# Base weights per source type defined in tech.md
BASE_WEIGHTS: dict[EdgeType, float] = {
    EdgeType.DECLARED_FK: 1.0,
    EdgeType.STATIC_SQL_STRING: 0.85,
    EdgeType.ORM_CALL: 0.80,
    EdgeType.INFERRED_NAMING: 0.55,
    EdgeType.DYNAMIC_UNRESOLVED: 0.15,
    EdgeType.STRUCTURAL_BELONGS_TO: 1.0,
}


@dataclass
class Node:
    """Represents a node in the dependency graph."""
    id: str
    type: NodeType
    name: str
    source_system: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, Enum) else str(self.type),
            "name": self.name,
            "source_system": self.source_system,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Node:
        node_type = NodeType(data["type"]) if isinstance(data["type"], str) else data["type"]
        return cls(
            id=data["id"],
            type=node_type,
            name=data["name"],
            source_system=data.get("source_system", "unknown"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Edge:
    """Represents a directional relationship between two nodes in the graph."""
    source: str
    target: str
    type: EdgeType
    confidence: float
    evidence: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Clamp confidence to [0.0, 1.0]
        if self.confidence < 0.0:
            self.confidence = 0.0
        elif self.confidence > 1.0:
            self.confidence = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "type": self.type.value if isinstance(self.type, Enum) else str(self.type),
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Edge:
        edge_type = EdgeType(data["type"]) if isinstance(data["type"], str) else data["type"]
        return cls(
            source=data["source"],
            target=data["target"],
            type=edge_type,
            confidence=float(data.get("confidence", BASE_WEIGHTS.get(edge_type, 0.5))),
            evidence=data.get("evidence", ""),
            metadata=data.get("metadata", {}),
        )
