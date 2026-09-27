from benchmark.loader import build_benchmark_db_artifacts

nodes, edges, cat = build_benchmark_db_artifacts()
print(f"Nodes: {len(nodes)}")
print(f"Edges: {len(edges)}")
print(f"Tables in catalog: {len(cat['tables'])}")

for e in edges:
    print(f"  {e.type.value}: {e.source} -> {e.target} (c={e.confidence})")
