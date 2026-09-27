import { CodeAdapter } from "./base";
import { Node, Edge, BASE_WEIGHTS } from "../graph/models";

/**
 * Extracts table names from standard SQL strings using robust regex heuristics.
 */
export function extractTablesFromSqlString(sql: string): string[] {
  const tables = new Set<string>();

  // Patterns for FROM, JOIN, INTO, UPDATE
  const fromJoinRegex = /\b(?:FROM|JOIN|INTO|UPDATE)\s+([`"']?[a-zA-Z0-9_]+[`"']?(?:\.[`"']?[a-zA-Z0-9_]+[`"']?)?)/gi;
  let match: RegExpExecArray | null;

  while ((match = fromJoinRegex.exec(sql)) !== null) {
    const raw = match[1];
    const clean = raw.replace(/[`"']/g, "").split(".").pop() || raw;
    const lower = clean.toLowerCase();

    // Exclude common SQL keywords that can follow FROM/JOIN in subqueries
    if (!["select", "where", "values", "set", "order", "group", "having", "limit"].includes(lower)) {
      tables.add(lower);
    }
  }

  return Array.from(tables);
}

export class UniversalSqlAdapter implements CodeAdapter {
  readonly languageId = "universal";
  readonly supportedExtensions = [
    ".rs", ".cs", ".cpp", ".c", ".h", ".scala", ".kt", ".swift", ".dart", ".lua", ".r", ".sh"
  ];

  public scanFile(filePath: string, content: string, knownTables?: Set<string>): { nodes: Node[]; edges: Edge[] } {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const fileNodeId = `file:${filePath}`;

    nodes.push({
      id: fileNodeId,
      type: "file",
      name: filePath,
      source_system: "universal",
    });

    const lines = content.split("\n");
    const sqlStringRegex = /["'`]([^"'`]*(?:SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM)[\s\S]*?)["'`]/gi;

    let match: RegExpExecArray | null;
    let funcCounter = 0;

    while ((match = sqlStringRegex.exec(content)) !== null) {
      const sqlSnippet = match[1];
      const tables = extractTablesFromSqlString(sqlSnippet);

      if (tables.length > 0) {
        funcCounter++;
        const funcId = `func:${filePath}:query_${funcCounter}`;

        nodes.push({
          id: funcId,
          type: "function",
          name: `query_${funcCounter}`,
          source_system: "universal",
          metadata: { file: filePath },
        });

        edges.push({
          source: funcId,
          target: fileNodeId,
          type: "structural_belongs_to",
          confidence: 1.0,
          evidence: "belongs to",
        });

        for (const tbl of tables) {
          edges.push({
            source: funcId,
            target: `table:${tbl}`,
            type: "static_sql_string",
            confidence: BASE_WEIGHTS.static_sql_string,
            evidence: sqlSnippet.slice(0, 80),
          });
        }
      }
    }

    return { nodes, edges };
  }
}
