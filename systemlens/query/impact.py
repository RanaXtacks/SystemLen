"""Impact Query and Blast Radius Engine for SystemLens.

Given a target database table or code entity, computes:
1. Reachability traversal in NetworkX DiGraph up to depth `d`.
2. Multiplicative path confidence decay: c(path) = Π c(edge_i).
3. Ranked impacted functions, files, and downstream tables.
4. Mandatory blind-spot disclosure formatting per flow.md.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from systemlens.models import EdgeType, NodeType


@dataclass
class ImpactedNode:
    """Represents a node impacted by a change to the target entity."""
    node_id: str
    node_type: str
    name: str
    confidence: float
    depth: int
    path: list[str]
    evidence_chain: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "name": self.name,
            "confidence": round(self.confidence, 4),
            "depth": self.depth,
            "path": self.path,
            "evidence_chain": self.evidence_chain,
            "metadata": self.metadata,
        }


@dataclass
class ImpactResult:
    """Complete result of a blast radius query."""
    target_id: str
    target_type: str
    target_name: str
    max_depth: int
    total_impacted: int
    impacted_functions: list[ImpactedNode]
    impacted_files: list[ImpactedNode]
    impacted_tables: list[ImpactedNode]
    ranked_items: list[ImpactedNode]
    blind_spots: list[dict[str, Any]]
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": {
                "id": self.target_id,
                "type": self.target_type,
                "name": self.target_name,
            },
            "query": {
                "max_depth": self.max_depth,
                "total_impacted": self.total_impacted,
            },
            "impacted_functions": [n.to_dict() for n in self.impacted_functions],
            "impacted_files": [n.to_dict() for n in self.impacted_files],
            "impacted_tables": [n.to_dict() for n in self.impacted_tables],
            "ranked_items": [n.to_dict() for n in self.ranked_items],
            "blind_spots": self.blind_spots,
            "metrics": self.metrics,
        }


class ImpactEngine:
    """
    Graph traversal engine to calculate reachability, confidence decay,
    and blast radius from any database or code node.
    """

    def __init__(self, graph_data: dict[str, Any] | None = None) -> None:
        self.raw_graph = graph_data or {"nodes": [], "edges": [], "metrics": {}}
        self.node_map: dict[str, dict[str, Any]] = {}
        self.propagation_graph = nx.DiGraph()
        self._build_propagation_graph()

    @classmethod
    def from_graph_file(cls, filepath: str | Path) -> ImpactEngine:
        """Load and initialize the engine from a graph.json file."""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def _build_propagation_graph(self) -> None:
        """
        Build the impact propagation DiGraph.

        In the dependency graph:
        - `orders -> users` (FK: orders references users)
        - `func:get_users -> table:users` (SQL: get_users queries users)
        - `func:get_users -> file:services.py` (Structural: get_users is in services.py)

        In the impact propagation graph:
        - Changes to `users` affect `orders` (users -> orders)
        - Changes to `users` affect `get_users` (users -> get_users)
        - Changes to `get_users` affect `services.py` (get_users -> services.py)
        """
        self.node_map.clear()
        self.propagation_graph.clear()

        for n in self.raw_graph.get("nodes", []):
            node_id = n["id"]
            self.node_map[node_id] = n
            self.propagation_graph.add_node(
                node_id,
                type=n.get("type", "unknown"),
                name=n.get("name", node_id),
                source_system=n.get("source_system", "unknown"),
                metadata=n.get("metadata", {}),
            )

        for e in self.raw_graph.get("edges", []):
            source = e["source"]
            target = e["target"]
            edge_type = e.get("type", "")
            confidence = float(e.get("confidence", 1.0))
            evidence = e.get("evidence", "")

            # Ensure endpoints exist
            if source not in self.node_map:
                self.node_map[source] = {"id": source, "type": "unknown", "name": source}
                self.propagation_graph.add_node(source, type="unknown", name=source)
            if target not in self.node_map:
                self.node_map[target] = {"id": target, "type": "unknown", "name": target}
                self.propagation_graph.add_node(target, type="unknown", name=target)

            # Impact propagation direction:
            # If structural belongs_to (function -> file): function change impacts file
            if edge_type == EdgeType.STRUCTURAL_BELONGS_TO.value:
                u, v = source, target
            else:
                # Reference/dependency edge: target change impacts source (target -> source)
                u, v = target, source

            if self.propagation_graph.has_edge(u, v):
                existing_conf = self.propagation_graph[u][v].get("confidence", 0.0)
                if confidence > existing_conf:
                    self.propagation_graph[u][v].update({
                        "confidence": confidence,
                        "evidence": evidence,
                        "type": edge_type,
                    })
            else:
                self.propagation_graph.add_edge(
                    u,
                    v,
                    confidence=confidence,
                    evidence=evidence,
                    type=edge_type,
                )

    def resolve_target_id(self, target: str) -> str | None:
        """
        Resolve a user input string (e.g. 'users', 'public.users', 'table:public.users')
        to a concrete node ID in the graph.
        """
        if target in self.node_map:
            return target

        lower = target.lower()
        # Direct check table:lower
        candidate_id = f"table:{lower}"
        if candidate_id in self.node_map:
            return candidate_id

        # Search by bare name or qualified name in node attributes
        for node_id, data in self.node_map.items():
            name = data.get("name", "").lower()
            if name == lower:
                return node_id
            if node_id.lower() == lower or node_id.lower() == f"table:{lower}":
                return node_id

        # Partial match on suffix: e.g. 'users' matches 'table:public.users'
        for node_id, data in self.node_map.items():
            clean = node_id.replace("table:", "").lower()
            if clean.endswith(f".{lower}") or clean == lower:
                return node_id

        return None

    def blast_radius(
        self,
        target: str,
        max_depth: int = 2,
        min_confidence: float = 0.0,
    ) -> ImpactResult:
        """
        Compute blast radius reachability and path confidence decay from target.

        Args:
            target: Name or ID of target node (e.g. 'users', 'table:public.users').
            max_depth: Maximum traversal depth (default 2).
            min_confidence: Minimum path confidence threshold (default 0.0).

        Returns:
            ImpactResult with ranked functions, files, tables, and blind spots.
        """
        resolved_id = self.resolve_target_id(target)
        if not resolved_id:
            # Target not found in graph
            return ImpactResult(
                target_id=target,
                target_type="unknown",
                target_name=target,
                max_depth=max_depth,
                total_impacted=0,
                impacted_functions=[],
                impacted_files=[],
                impacted_tables=[],
                ranked_items=[],
                blind_spots=self._build_blind_spots(target),
                metrics={"error": f"Target entity '{target}' not found in graph."},
            )

        target_node = self.node_map[resolved_id]
        target_name = target_node.get("name", resolved_id)
        target_type = target_node.get("type", "unknown")

        # BFS tracking highest confidence path to each reachable node
        # best_reach: node_id -> (confidence, depth, path, evidence_chain)
        best_reach: dict[str, tuple[float, int, list[str], list[str]]] = {}

        # Queue items: (current_node, current_depth, current_conf, path, evidence_chain)
        queue: deque[tuple[str, int, float, list[str], list[str]]] = deque()
        queue.append((resolved_id, 0, 1.0, [resolved_id], []))

        while queue:
            curr_id, curr_depth, curr_conf, curr_path, curr_evidence = queue.popleft()

            if curr_depth >= max_depth:
                continue

            for neighbor in self.propagation_graph.successors(curr_id):
                # Don't loop in cycles
                if neighbor in curr_path:
                    continue

                edge_data = self.propagation_graph.get_edge_data(curr_id, neighbor)
                edge_conf = float(edge_data.get("confidence", 1.0))
                edge_evid = edge_data.get("evidence", "")

                # Multiplicative path confidence decay: c(path) = Π c(edge_i)
                new_conf = round(curr_conf * edge_conf, 4)
                if new_conf < min_confidence:
                    continue

                new_depth = curr_depth + 1
                new_path = curr_path + [neighbor]
                new_evidence = curr_evidence + [edge_evid]

                # If neighbor not visited or found higher confidence path
                if neighbor not in best_reach or new_conf > best_reach[neighbor][0]:
                    best_reach[neighbor] = (new_conf, new_depth, new_path, new_evidence)
                    queue.append((neighbor, new_depth, new_conf, new_path, new_evidence))

        # Convert reached nodes to ImpactedNode objects
        impacted_nodes: list[ImpactedNode] = []
        for n_id, (conf, depth, path, evid) in best_reach.items():
            n_data = self.node_map.get(n_id, {})
            impacted_nodes.append(
                ImpactedNode(
                    node_id=n_id,
                    node_type=n_data.get("type", "unknown"),
                    name=n_data.get("name", n_id),
                    confidence=conf,
                    depth=depth,
                    path=path,
                    evidence_chain=evid,
                    metadata=n_data.get("metadata", {}),
                )
            )

        # Sort ranked items by confidence descending, then by depth ascending
        impacted_nodes.sort(key=lambda n: (-n.confidence, n.depth, n.name))

        # Partition into groups
        funcs = [n for n in impacted_nodes if n.node_type == NodeType.FUNCTION.value]
        files = [n for n in impacted_nodes if n.node_type == NodeType.FILE.value]
        tables = [
            n
            for n in impacted_nodes
            if n.node_type in (NodeType.TABLE.value, NodeType.VIEW.value, NodeType.PARTITION.value)
        ]

        blind_spots = self._build_blind_spots(resolved_id)

        return ImpactResult(
            target_id=resolved_id,
            target_type=target_type,
            target_name=target_name,
            max_depth=max_depth,
            total_impacted=len(impacted_nodes),
            impacted_functions=funcs,
            impacted_files=files,
            impacted_tables=tables,
            ranked_items=impacted_nodes,
            blind_spots=blind_spots,
            metrics={
                "functions_count": len(funcs),
                "files_count": len(files),
                "downstream_tables_count": len(tables),
            },
        )

    def _build_blind_spots(self, target_id: str) -> list[dict[str, Any]]:
        """
        Build mandatory blind spots disclosure list per flow.md.
        Guaranteed to be non-empty.
        """
        blind_spots: list[dict[str, Any]] = []

        # 1. Unresolved dynamic queries disclosure
        dynamic_edges = [
            e for e in self.raw_graph.get("edges", [])
            if e.get("type") == EdgeType.DYNAMIC_UNRESOLVED.value
        ]
        dynamic_count = len(dynamic_edges)
        dynamic_functions = list(dict.fromkeys(e["source"] for e in dynamic_edges))

        if dynamic_count > 0:
            blind_spots.append({
                "type": "dynamic_unresolved_sql",
                "severity": "high" if dynamic_count > 5 else "medium",
                "count": dynamic_count,
                "message": (
                    f"Not fully visible: {dynamic_count} dynamic SQL/variable executions "
                    f"across {len(dynamic_functions)} function(s) could not be resolved statically."
                ),
                "functions": dynamic_functions[:10],
            })
        else:
            blind_spots.append({
                "type": "dynamic_unresolved_sql",
                "severity": "info",
                "count": 0,
                "message": "No dynamic unresolved SQL calls detected in analyzed code.",
                "functions": [],
            })

        # 2. Cross-service calls boundary disclosure
        blind_spots.append({
            "type": "cross_service_boundary",
            "severity": "medium",
            "message": (
                "Cross-service HTTP/gRPC boundaries and message queue topics "
                "are not analyzed in V1."
            ),
        })

        # 3. Unreferenced database tables disclosure
        code_targets = {
            e["target"].replace("table:", "").lower()
            for e in self.raw_graph.get("edges", [])
            if e.get("type") in (EdgeType.STATIC_SQL_STRING.value, EdgeType.ORM_CALL.value)
        }
        all_db_tables = {
            n["name"].lower()
            for n in self.raw_graph.get("nodes", [])
            if n.get("type") in (NodeType.TABLE.value, NodeType.VIEW.value)
        }
        unreferenced_tables = list(all_db_tables - code_targets)
        if unreferenced_tables:
            blind_spots.append({
                "type": "unreferenced_tables",
                "severity": "low",
                "count": len(unreferenced_tables),
                "message": (
                    f"{len(unreferenced_tables)} database table(s) in schema are not referenced "
                    f"by analyzed Python code."
                ),
                "tables": unreferenced_tables[:10],
            })

        return blind_spots
