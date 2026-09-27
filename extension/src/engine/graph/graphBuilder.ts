import { SchemaCatalog } from "../schema/types";
import { GraphData, Node, Edge, BASE_WEIGHTS } from "./models";

export class GraphBuilder {
  private nodes: Node[] = [];
  private edges: Edge[] = [];
  private nodeIds = new Set<string>();

  public addSchemaCatalog(catalog: SchemaCatalog): void {
    for (const [tableKey, tableDef] of Object.entries(catalog.tables)) {
      const nodeId = `table:${tableKey}`;
      if (!this.nodeIds.has(nodeId)) {
        this.nodeIds.add(nodeId);
        this.nodes.push({
          id: nodeId,
          type: tableDef.type,
          name: tableDef.name,
          source_system: catalog.sourceType || "database",
          metadata: {
            columns: tableDef.columns,
            foreign_keys: tableDef.foreignKeys,
            source_file: tableDef.sourceFile,
          },
        });
      }

      // Foreign keys
      for (const fk of tableDef.foreignKeys) {
        const targetId = `table:${fk.targetTable.toLowerCase()}`;
        this.edges.push({
          source: nodeId,
          target: targetId,
          type: "declared_fk",
          confidence: BASE_WEIGHTS.declared_fk,
          evidence: fk.constraintName ? `FK ${fk.constraintName}` : `FK ${tableDef.name}.${fk.fromColumn} -> ${fk.targetTable}`,
          metadata: fk,
        });
      }
    }
  }

  public addCodeAnalysis(codeNodes: Node[], codeEdges: Edge[]): void {
    for (const n of codeNodes) {
      if (!this.nodeIds.has(n.id)) {
        this.nodeIds.add(n.id);
        this.nodes.push(n);
      }
    }

    for (const e of codeEdges) {
      this.edges.push(e);
      // Auto-register target table node if missing
      if (e.target.startsWith("table:") && !this.nodeIds.has(e.target)) {
        const rawName = e.target.replace("table:", "");
        this.nodeIds.add(e.target);
        this.nodes.push({
          id: e.target,
          type: rawName === "unresolved" ? "table" : "table",
          name: rawName,
          source_system: "inferred_from_code",
          metadata: { inferred: true },
        });
      }
    }
  }

  public build(): GraphData {
    let staticSqlCount = 0;
    let ormCallCount = 0;
    let dynamicUnresolvedCount = 0;

    for (const e of this.edges) {
      if (e.type === "static_sql_string") staticSqlCount++;
      else if (e.type === "orm_call") ormCallCount++;
      else if (e.type === "dynamic_unresolved") dynamicUnresolvedCount++;
    }

    const totalAccess = staticSqlCount + ormCallCount + dynamicUnresolvedCount;
    const dynamicRatio = totalAccess > 0 ? Math.round((dynamicUnresolvedCount / totalAccess) * 1000) / 1000 : 0;

    return {
      nodes: this.nodes,
      edges: this.edges,
      metrics: {
        total_nodes: this.nodes.length,
        total_edges: this.edges.length,
        code_to_db: {
          total_access_calls: totalAccess,
          static_sql_count: staticSqlCount,
          orm_call_count: ormCallCount,
          dynamic_unresolved_count: dynamicUnresolvedCount,
          dynamic_unresolved_ratio: dynamicRatio,
        },
      },
    };
  }
}
