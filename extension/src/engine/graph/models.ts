export type NodeType = "table" | "view" | "partition" | "function" | "file";

export type EdgeType =
  | "declared_fk"
  | "inferred_naming"
  | "static_sql_string"
  | "orm_call"
  | "dynamic_unresolved"
  | "structural_belongs_to";

export const BASE_WEIGHTS: Record<EdgeType, number> = {
  declared_fk: 1.0,
  structural_belongs_to: 1.0,
  static_sql_string: 0.85,
  orm_call: 0.80,
  inferred_naming: 0.55,
  dynamic_unresolved: 0.15,
};

export interface Node {
  id: string;
  type: NodeType;
  name: string;
  source_system: string;
  metadata?: Record<string, any>;
}

export interface Edge {
  source: string;
  target: string;
  type: EdgeType;
  confidence: number;
  evidence: string;
  metadata?: Record<string, any>;
}

export interface GraphData {
  nodes: Node[];
  edges: Edge[];
  metrics: {
    total_nodes: number;
    total_edges: number;
    code_to_db: {
      total_access_calls: number;
      static_sql_count: number;
      orm_call_count: number;
      dynamic_unresolved_count: number;
      dynamic_unresolved_ratio: number;
    };
  };
}
