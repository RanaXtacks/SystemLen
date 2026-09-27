import { GraphData, Node, Edge, NodeType, EdgeType } from "./models";

export interface ImpactedNode {
  node_id: string;
  node_type: NodeType | string;
  name: string;
  confidence: number;
  depth: number;
  path: string[];
  evidence_chain: string[];
  metadata: Record<string, any>;
}

export interface ImpactResult {
  target: {
    id: string;
    type: string;
    name: string;
  };
  query: {
    max_depth: number;
    total_impacted: number;
  };
  impacted_functions: ImpactedNode[];
  impacted_files: ImpactedNode[];
  impacted_tables: ImpactedNode[];
  ranked_items: ImpactedNode[];
  blind_spots: Array<{
    type: string;
    severity: string;
    message: string;
    count?: number;
    functions?: string[];
  }>;
  metrics: Record<string, any>;
}

export class NativeImpactEngine {
  private nodeMap = new Map<string, Node>();
  // Adjacency for impact propagation: u -> list of { v, confidence, evidence, type }
  private propagationMap = new Map<string, Array<{ target: string; confidence: number; evidence: string; type: string }>>();

  constructor(private graph: GraphData) {
    this.buildPropagationGraph();
  }

  private buildPropagationGraph(): void {
    this.nodeMap.clear();
    this.propagationMap.clear();

    for (const n of this.graph.nodes || []) {
      this.nodeMap.set(n.id, n);
      this.propagationMap.set(n.id, []);
    }

    for (const e of this.graph.edges || []) {
      // Ensure source and target exist in node map
      if (!this.nodeMap.has(e.source)) {
        const dummy: Node = { id: e.source, type: "file", name: e.source, source_system: "unknown" };
        this.nodeMap.set(e.source, dummy);
        this.propagationMap.set(e.source, []);
      }
      if (!this.nodeMap.has(e.target)) {
        const dummy: Node = { id: e.target, type: "table", name: e.target, source_system: "unknown" };
        this.nodeMap.set(e.target, dummy);
        this.propagationMap.set(e.target, []);
      }

      // Impact propagation direction:
      // If structural belongs_to (function -> file): function change impacts file
      // If reference/query edge (func -> table or table -> table): target change impacts source (target -> source)
      let u: string;
      let v: string;

      if (e.type === "structural_belongs_to") {
        u = e.source;
        v = e.target;
      } else {
        u = e.target;
        v = e.source;
      }

      const list = this.propagationMap.get(u) || [];
      list.push({
        target: v,
        confidence: e.confidence ?? 1.0,
        evidence: e.evidence || "",
        type: e.type,
      });
      this.propagationMap.set(u, list);
    }
  }

  public resolveTargetId(target: string): string | null {
    if (this.nodeMap.has(target)) return target;

    const lower = target.toLowerCase();
    const candidate = `table:${lower}`;
    if (this.nodeMap.has(candidate)) return candidate;

    for (const [nodeId, n] of this.nodeMap.entries()) {
      if (n.name.toLowerCase() === lower) return nodeId;
      if (nodeId.toLowerCase() === lower || nodeId.toLowerCase() === candidate) return nodeId;
      const clean = nodeId.replace("table:", "").toLowerCase();
      if (clean.endsWith(`.${lower}`) || clean === lower) return nodeId;
    }

    return null;
  }

  public blastRadius(target: string, maxDepth = 2, minConfidence = 0.0): ImpactResult {
    const resolvedId = this.resolveTargetId(target);
    if (!resolvedId) {
      return {
        target: { id: target, type: "unknown", name: target },
        query: { max_depth: maxDepth, total_impacted: 0 },
        impacted_functions: [],
        impacted_files: [],
        impacted_tables: [],
        ranked_items: [],
        blind_spots: this.buildBlindSpots(target),
        metrics: { error: `Target entity '${target}' not found in graph.` },
      };
    }

    const targetNode = this.nodeMap.get(resolvedId)!;

    // BFS tracking best reachability confidence
    interface QueueItem {
      nodeId: string;
      depth: number;
      conf: number;
      path: string[];
      evidence: string[];
    }

    const bestReach = new Map<string, { conf: number; depth: number; path: string[]; evidence: string[] }>();
    const queue: QueueItem[] = [{ nodeId: resolvedId, depth: 0, conf: 1.0, path: [resolvedId], evidence: [] }];

    while (queue.length > 0) {
      const curr = queue.shift()!;
      if (curr.depth >= maxDepth) continue;

      const neighbors = this.propagationMap.get(curr.nodeId) || [];
      for (const edge of neighbors) {
        if (curr.path.includes(edge.target)) continue;

        const newConf = Math.round(curr.conf * edge.confidence * 10000) / 10000;
        if (newConf < minConfidence) continue;

        const newDepth = curr.depth + 1;
        const newPath = [...curr.path, edge.target];
        const newEvidence = [...curr.evidence, edge.evidence];

        const existing = bestReach.get(edge.target);
        if (!existing || newConf > existing.conf) {
          bestReach.set(edge.target, { conf: newConf, depth: newDepth, path: newPath, evidence: newEvidence });
          queue.push({ nodeId: edge.target, depth: newDepth, conf: newConf, path: newPath, evidence: newEvidence });
        }
      }
    }

    const impactedNodes: ImpactedNode[] = [];
    for (const [nodeId, reach] of bestReach.entries()) {
      const n = this.nodeMap.get(nodeId);
      if (!n) continue;
      impactedNodes.push({
        node_id: nodeId,
        node_type: n.type,
        name: n.name || nodeId,
        confidence: reach.conf,
        depth: reach.depth,
        path: reach.path,
        evidence_chain: reach.evidence,
        metadata: n.metadata || {},
      });
    }

    // Sort by confidence descending, then depth ascending
    impactedNodes.sort((a, b) => b.confidence - a.confidence || a.depth - b.depth);

    const funcs = impactedNodes.filter(n => n.node_type === "function");
    const files = impactedNodes.filter(n => n.node_type === "file");
    const tables = impactedNodes.filter(n => n.node_type === "table" || n.node_type === "view");

    return {
      target: {
        id: resolvedId,
        type: targetNode.type,
        name: targetNode.name,
      },
      query: {
        max_depth: maxDepth,
        total_impacted: impactedNodes.length,
      },
      impacted_functions: funcs,
      impacted_files: files,
      impacted_tables: tables,
      ranked_items: impactedNodes,
      blind_spots: this.buildBlindSpots(resolvedId),
      metrics: {
        functions_count: funcs.length,
        files_count: files.length,
        downstream_tables_count: tables.length,
      },
    };
  }

  private buildBlindSpots(targetId: string): Array<{ type: string; severity: string; message: string; count?: number; functions?: string[] }> {
    const spots: Array<{ type: string; severity: string; message: string; count?: number; functions?: string[] }> = [];

    // 1. Dynamic unresolved queries
    const dynamicEdges = (this.graph.edges || []).filter(e => e.type === "dynamic_unresolved");
    if (dynamicEdges.length > 0) {
      const funcs = Array.from(new Set(dynamicEdges.map(e => e.source))).slice(0, 10);
      spots.push({
        type: "dynamic_unresolved_sql",
        severity: dynamicEdges.length > 5 ? "high" : "medium",
        count: dynamicEdges.length,
        message: `Not fully visible: ${dynamicEdges.length} dynamic SQL variable execution(s) could not be resolved statically.`,
        functions: funcs,
      });
    } else {
      spots.push({
        type: "dynamic_unresolved_sql",
        severity: "info",
        count: 0,
        message: "No dynamic unresolved SQL calls detected in analyzed code.",
      });
    }

    // 2. Cross-service boundaries
    spots.push({
      type: "cross_service_boundary",
      severity: "medium",
      message: "Cross-service HTTP/gRPC boundaries and message queue topics are not analyzed in V1/V2.",
    });

    return spots;
  }
}
