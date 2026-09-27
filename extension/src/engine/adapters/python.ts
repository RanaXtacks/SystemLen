import { CodeAdapter } from "./base";
import { Node, Edge, BASE_WEIGHTS } from "../graph/models";
import { extractTablesFromSqlString } from "./universalSql";

function pluralize(word: string): string {
  const lower = word.toLowerCase();
  if (lower.endsWith("y") && !/[aeiou]y$/.test(lower)) return lower.slice(0, -1) + "ies";
  if (lower.endsWith("s") || lower.endsWith("sh") || lower.endsWith("ch") || lower.endsWith("x")) return lower + "es";
  return lower + "s";
}

export class PythonCodeAdapter implements CodeAdapter {
  readonly languageId = "python";
  readonly supportedExtensions = [".py"];

  public scanFile(filePath: string, content: string, knownTables?: Set<string>): { nodes: Node[]; edges: Edge[] } {
    const nodes: Node[] = [];
    const edges: Edge[] = [];
    const fileNodeId = `file:${filePath}`;

    nodes.push({
      id: fileNodeId,
      type: "file",
      name: filePath,
      source_system: "python",
    });

    const lines = content.split("\n");
    const funcRegex = /^(?:\s*)(?:async\s+)?def\s+([a-zA-Z0-9_]+)\s*\(/;

    // Split into functions
    interface FunctionBlock {
      name: string;
      id: string;
      startLine: number;
      endLine: number;
      body: string;
    }

    const functions: FunctionBlock[] = [];
    let currentFunc: { name: string; id: string; startLine: number; lines: string[] } | null = null;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const match = funcRegex.exec(line);

      if (match) {
        if (currentFunc) {
          functions.push({
            name: currentFunc.name,
            id: currentFunc.id,
            startLine: currentFunc.startLine,
            endLine: i,
            body: currentFunc.lines.join("\n"),
          });
        }
        const fnName = match[1];
        currentFunc = {
          name: fnName,
          id: `func:${filePath}:${fnName}`,
          startLine: i + 1,
          lines: [line],
        };
      } else if (currentFunc) {
        currentFunc.lines.push(line);
      }
    }

    if (currentFunc) {
      functions.push({
        name: currentFunc.name,
        id: currentFunc.id,
        startLine: currentFunc.startLine,
        endLine: lines.length,
        body: currentFunc.lines.join("\n"),
      });
    }

    // If no functions found, treat whole file as module
    if (functions.length === 0) {
      functions.push({
        name: "<module>",
        id: `func:${filePath}:<module>`,
        startLine: 1,
        endLine: lines.length,
        body: content,
      });
    }

    for (const fn of functions) {
      nodes.push({
        id: fn.id,
        type: "function",
        name: fn.name,
        source_system: "python",
        metadata: { file: filePath, lineno: fn.startLine },
      });

      edges.push({
        source: fn.id,
        target: fileNodeId,
        type: "structural_belongs_to",
        confidence: 1.0,
        evidence: `in ${filePath}:${fn.startLine}`,
      });

      const body = fn.body;

      // 1. Django ORM: Model.objects.filter/create/get...
      const djangoOrmRegex = /\b([A-Z][a-zA-Z0-9_]*)\.objects\.(?:filter|get|create|update|all|exclude|values|bulk_create|delete)\s*\(/g;
      let ormMatch: RegExpExecArray | null;
      while ((ormMatch = djangoOrmRegex.exec(body)) !== null) {
        const modelName = ormMatch[1];
        const tbl = pluralize(modelName);
        edges.push({
          source: fn.id,
          target: `table:${tbl}`,
          type: "orm_call",
          confidence: BASE_WEIGHTS.orm_call,
          evidence: ormMatch[0],
          metadata: { file: filePath, lineno: fn.startLine, model: modelName },
        });
      }

      // 2. SQLAlchemy: session.query(Model) / select(Model)
      const saRegex = /(?:session\.query|select)\s*\(\s*([A-Z][a-zA-Z0-9_]*)\s*[\),]/g;
      while ((ormMatch = saRegex.exec(body)) !== null) {
        const modelName = ormMatch[1];
        const tbl = pluralize(modelName);
        edges.push({
          source: fn.id,
          target: `table:${tbl}`,
          type: "orm_call",
          confidence: BASE_WEIGHTS.orm_call,
          evidence: ormMatch[0],
          metadata: { file: filePath, lineno: fn.startLine, model: modelName },
        });
      }

      // 3. Raw SQL: cursor.execute("SELECT ...") or standalone SQL strings
      const rawSqlRegex = /["']{1,3}([^"'`]*(?:SELECT\s+[\s\S]*?\s+FROM|INSERT\s+INTO|UPDATE\s+[\s\S]*?\s+SET|DELETE\s+FROM)[\s\S]*?)["']{1,3}/gi;
      let sqlMatch: RegExpExecArray | null;
      while ((sqlMatch = rawSqlRegex.exec(body)) !== null) {
        const snippet = sqlMatch[1];
        const tables = extractTablesFromSqlString(snippet);
        for (const tbl of tables) {
          edges.push({
            source: fn.id,
            target: `table:${tbl}`,
            type: "static_sql_string",
            confidence: BASE_WEIGHTS.static_sql_string,
            evidence: snippet.slice(0, 80),
            metadata: { file: filePath, lineno: fn.startLine },
          });
        }
      }

      // 4. Dynamic query: cursor.execute(query_var)
      const dynamicRegex = /\b(?:cursor\.execute|execute|raw)\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*[,)]/g;
      let dynMatch: RegExpExecArray | null;
      while ((dynMatch = dynamicRegex.exec(body)) !== null) {
        const varName = dynMatch[1];
        if (!varName.startsWith('"') && !varName.startsWith("'")) {
          edges.push({
            source: fn.id,
            target: "table:unresolved",
            type: "dynamic_unresolved",
            confidence: BASE_WEIGHTS.dynamic_unresolved,
            evidence: dynMatch[0],
            metadata: { file: filePath, lineno: fn.startLine, variable: varName },
          });
        }
      }
    }

    return { nodes, edges };
  }
}
