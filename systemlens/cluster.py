"""Catalog clustering engine for SystemLens.

Groups database tables into logical architectural modules using Louvain
community detection (modularity maximization) on calibrated edge weights.
"""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
import json
import math
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
from networkx.algorithms.community import louvain_communities, modularity


@dataclass
class ClusterInfo:
    """Metadata and member list for a single detected catalog cluster."""

    id: str
    label: str
    hub_table: str
    tables: List[str]
    size: int
    density: float
    internal_weight: float


@dataclass
class CatalogClusteringResult:
    """Complete result of catalog clustering analysis."""

    modularity_q: float
    total_tables: int
    total_clusters: int
    clusters: List[ClusterInfo] = field(default_factory=list)
    isolated_tables: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modularity_q": round(self.modularity_q, 4),
            "total_tables": self.total_tables,
            "total_clusters": self.total_clusters,
            "clusters": [asdict(c) for c in self.clusters],
            "isolated_tables": self.isolated_tables,
        }


def compute_ari(labels_true: Dict[str, Any], labels_pred: Dict[str, Any]) -> float:
    """Compute the Adjusted Rand Index (ARI) between two labelings.

    ARI measures the similarity between ground-truth module boundaries and
    clustering partitions, corrected for chance:
        ARI = (RI - Expected_RI) / (Max_RI - Expected_RI)
    Returns:
        1.0 for identical clusterings, ~0.0 for chance, negative for worse than chance.
    """
    common_keys = [k for k in labels_true if k in labels_pred]
    if len(common_keys) < 2:
        return 1.0

    def comb2(n: int) -> int:
        return n * (n - 1) // 2 if n >= 2 else 0

    classes: Dict[Any, Set[str]] = defaultdict(set)
    clusters: Dict[Any, Set[str]] = defaultdict(set)
    for k in common_keys:
        classes[labels_true[k]].add(k)
        clusters[labels_pred[k]].add(k)

    contingency: Dict[Tuple[Any, Any], int] = {}
    for c_id, c_elems in classes.items():
        for k_id, k_elems in clusters.items():
            intersect_len = len(c_elems & k_elems)
            if intersect_len > 0:
                contingency[(c_id, k_id)] = intersect_len

    sum_comb_table = sum(comb2(v) for v in contingency.values())
    sum_comb_classes = sum(comb2(len(v)) for v in classes.values())
    sum_comb_clusters = sum(comb2(len(v)) for v in clusters.values())
    n = len(common_keys)
    total_pairs = comb2(n)

    expected_index = (
        (sum_comb_classes * sum_comb_clusters) / total_pairs if total_pairs > 0 else 0.0
    )
    max_index = (sum_comb_classes + sum_comb_clusters) / 2.0
    if max_index == expected_index:
        return 1.0
    return float((sum_comb_table - expected_index) / (max_index - expected_index))


def _normalize_table_name(table_id: str) -> str:
    """Extract clean bare table name from node id (e.g. 'table:public.users' -> 'users')."""
    name = table_id
    if name.startswith("table:"):
        name = name[len("table:") :]
    if "." in name:
        name = name.split(".")[-1]
    return name


def _generate_cluster_label(tables: List[str], hub_table: str) -> str:
    """Generate a human-meaningful module title from member table names."""
    if not tables:
        return "Empty Module"
    if len(tables) == 1:
        return f"{tables[0].capitalize()} Module"

    # Tokenize table names into keywords
    words: List[str] = []
    prefixes: List[str] = []
    for t in tables:
        clean = _normalize_table_name(t)
        parts = [p.lower() for p in re.split(r"[_\W]+", clean) if len(p) >= 3]
        if parts:
            prefixes.append(parts[0])
            words.extend(parts)

    stop_words = {
        "model",
        "data",
        "item",
        "items",
        "type",
        "types",
        "table",
        "info",
        "custom",
        "base",
        "assigned",
        "entry",
        "entries",
        "record",
        "records",
    }
    filtered_words = [w for w in words if w not in stop_words]

    word_counts = Counter(filtered_words)
    prefix_counts = Counter(prefixes)

    # Pick top 1-2 dominant domain keywords
    top_candidates = [w for w, c in word_counts.most_common(3)]
    top_prefix = prefix_counts.most_common(1)[0][0] if prefix_counts else ""

    if top_prefix and top_prefix in top_candidates:
        primary = top_prefix.capitalize()
    elif top_candidates:
        primary = top_candidates[0].capitalize()
    else:
        primary = _normalize_table_name(hub_table).capitalize()

    # Find secondary keyword if distinct
    secondary = ""
    for cand in top_candidates:
        if cand.capitalize() != primary and len(cand) >= 4:
            secondary = f" & {cand.capitalize()}"
            break

    return f"{primary}{secondary} Domain"


def cluster_catalog(
    graph_data: Dict[str, Any],
    resolution: float = 1.0,
    seed: int = 42,
    include_code_cooccurrence: bool = True,
    code_cooccurrence_weight: float = 0.5,
    include_naming_prefix: bool = True,
    naming_prefix_weight: float = 0.92,
) -> CatalogClusteringResult:
    """Cluster database tables from graph_data into architectural modules.

    Args:
        graph_data: Dictionary containing 'nodes' and 'edges'.
        resolution: Louvain resolution parameter (higher = smaller clusters).
        seed: Random seed for deterministic partition computation.
        include_code_cooccurrence: If True, project table co-occurrences through code functions.
        code_cooccurrence_weight: Edge weight assigned to shared function accesses.
        include_naming_prefix: If True, add edges between tables sharing naming prefixes.
        naming_prefix_weight: Edge weight assigned to shared naming prefix families.

    Returns:
        CatalogClusteringResult containing detected clusters, modularity Q, and metadata.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # 1. Identify all table nodes
    table_nodes: Dict[str, str] = {}  # id -> clean name
    for n in nodes:
        node_id = n.get("id", "")
        node_type = n.get("type", "")
        if node_type == "table" or node_id.startswith("table:"):
            table_nodes[node_id] = _normalize_table_name(node_id)

    if not table_nodes:
        return CatalogClusteringResult(
            modularity_q=0.0,
            total_tables=0,
            total_clusters=0,
            clusters=[],
            isolated_tables=[],
        )

    # 2. Build NetworkX graph
    G = nx.Graph()
    for t_id in table_nodes:
        G.add_node(t_id)

    # 3. Add direct table-to-table relational edges (Foreign Keys, Inferred Naming, etc.)
    for e in edges:
        src = e.get("source", "")
        tgt = e.get("target", "")
        if src in table_nodes and tgt in table_nodes and src != tgt:
            w = float(e.get("confidence", e.get("weight", 1.0)))
            if G.has_edge(src, tgt):
                G[src][tgt]["weight"] += w
            else:
                G.add_edge(src, tgt, weight=w)

    # 4. Optional: Project bipartite code co-occurrences (Functions/Files touching multiple tables)
    if include_code_cooccurrence:
        func_to_tables: Dict[str, Set[str]] = defaultdict(set)
        for e in edges:
            src = e.get("source", "")
            tgt = e.get("target", "")
            if src in table_nodes and tgt not in table_nodes:
                func_to_tables[tgt].add(src)
            elif tgt in table_nodes and src not in table_nodes:
                func_to_tables[src].add(tgt)

        for _, shared_tables in func_to_tables.items():
            if len(shared_tables) > 1:
                t_list = list(shared_tables)
                for i in range(len(t_list)):
                    for j in range(i + 1, len(t_list)):
                        t1, t2 = t_list[i], t_list[j]
                        if G.has_edge(t1, t2):
                            G[t1][t2]["weight"] += code_cooccurrence_weight
                        else:
                            G.add_edge(t1, t2, weight=code_cooccurrence_weight)

    # 5. Optional: Link tables sharing exact naming prefixes (e.g. order_*, account_*)
    if include_naming_prefix:
        prefix_groups: Dict[str, List[str]] = defaultdict(list)
        for t_id, clean_name in table_nodes.items():
            parts = clean_name.split("_")
            if len(parts) >= 2 and len(parts[0]) >= 3:
                prefix_groups[parts[0]].append(t_id)

        for _, group in prefix_groups.items():
            if len(group) > 1:
                for i in range(len(group)):
                    for j in range(i + 1, len(group)):
                        t1, t2 = group[i], group[j]
                        if G.has_edge(t1, t2):
                            G[t1][t2]["weight"] += naming_prefix_weight
                        else:
                            G.add_edge(t1, t2, weight=naming_prefix_weight)

    # 6. Community Detection via Louvain
    if G.number_of_edges() > 0:
        communities = louvain_communities(G, weight="weight", resolution=resolution, seed=seed)
        try:
            q_score = float(modularity(G, communities, weight="weight"))
        except Exception:
            q_score = 0.0
    else:
        communities = [{node} for node in G.nodes()]
        q_score = 0.0

    # Sort communities by size descending
    sorted_comms = sorted(communities, key=len, reverse=True)

    clusters: List[ClusterInfo] = []
    isolated: List[str] = []

    for idx, comm in enumerate(sorted_comms, start=1):
        comm_nodes = list(comm)
        clean_names = sorted([table_nodes[n] for n in comm_nodes])

        if len(comm_nodes) == 1 and G.degree(comm_nodes[0]) == 0:
            isolated.append(clean_names[0])
            continue

        # Find hub table (highest weighted degree within community)
        subgraph = G.subgraph(comm_nodes)
        degrees = dict(subgraph.degree(weight="weight"))
        hub_node = max(degrees.keys(), key=lambda k: degrees[k]) if degrees else comm_nodes[0]
        hub_name = table_nodes[hub_node]

        internal_weight = sum(d.get("weight", 1.0) for _, _, d in subgraph.edges(data=True))
        density = (
            (2.0 * len(subgraph.edges())) / (len(comm_nodes) * (len(comm_nodes) - 1))
            if len(comm_nodes) > 1
            else 1.0
        )

        label = _generate_cluster_label(clean_names, hub_name)

        clusters.append(
            ClusterInfo(
                id=f"cluster_{idx}",
                label=label,
                hub_table=hub_name,
                tables=clean_names,
                size=len(clean_names),
                density=round(density, 3),
                internal_weight=round(internal_weight, 3),
            )
        )

    return CatalogClusteringResult(
        modularity_q=q_score,
        total_tables=len(table_nodes),
        total_clusters=len(clusters),
        clusters=clusters,
        isolated_tables=sorted(isolated),
    )


def cluster_catalog_from_file(
    graph_path: str,
    resolution: float = 1.0,
    seed: int = 42,
    include_code_cooccurrence: bool = True,
    include_naming_prefix: bool = True,
) -> CatalogClusteringResult:
    """Load graph JSON from file and perform catalog clustering."""
    with open(graph_path, "r", encoding="utf-8") as f:
        graph_data = json.load(f)
    return cluster_catalog(
        graph_data=graph_data,
        resolution=resolution,
        seed=seed,
        include_code_cooccurrence=include_code_cooccurrence,
        include_naming_prefix=include_naming_prefix,
    )
