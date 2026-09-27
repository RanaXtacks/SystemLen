import { Node, Edge } from "../graph/models";

export interface CodeAdapter {
  readonly languageId: string;
  readonly supportedExtensions: string[];
  scanFile(filePath: string, content: string, knownTables?: Set<string>): { nodes: Node[]; edges: Edge[] };
}
