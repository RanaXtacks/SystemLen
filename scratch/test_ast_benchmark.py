import json
from pathlib import Path
from systemlens.adapters.python_ast import PythonASTAdapter
from systemlens.graph import assemble_unified_graph
from benchmark.loader import build_benchmark_db_artifacts

db_nodes, db_edges, raw_cat = build_benchmark_db_artifacts()

app_dir = Path("benchmark/app")
py_adapter = PythonASTAdapter(app_dir)
code_nodes = py_adapter.extract_nodes()
code_edges = py_adapter.extract_edges()

print(f"Code Nodes: {len(code_nodes)}")
print(f"Code Edges: {len(code_edges)}")

edge_counts = {}
for e in code_edges:
    edge_counts[e.type.value] = edge_counts.get(e.type.value, 0) + 1

for etype, count in sorted(edge_counts.items()):
    print(f"  {etype}: {count}")

# Assemble unified graph
graph = assemble_unified_graph(
    db_nodes=db_nodes,
    db_edges=db_edges,
    code_nodes=code_nodes,
    code_edges=code_edges,
)

out_file = Path("benchmark/benchmark_graph.json")
out_file.write_text(json.dumps(graph, indent=2), encoding="utf-8")

print(f"\nUnified Graph Assembled at {out_file}:")
print(f"Total Nodes: {len(graph['nodes'])}")
print(f"Total Edges: {len(graph['edges'])}")
print(f"Metrics: {json.dumps(graph['metrics'], indent=2)}")

# Let's inspect some static SQL and ORM edges
print("\nSample Code Edges:")
for e in graph["edges"]:
    if e["type"] in ("static_sql_string", "orm_call", "dynamic_unresolved"):
        print(f"  {e['source']} -> {e['target']} ({e['type']}, c={e['confidence']})")
