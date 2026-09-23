from benchmark.loader import build_benchmark_db_artifacts

nodes, edges, cat = build_benchmark_db_artifacts()
print("Transactions columns in catalog:")
for c in cat["tables"]["public.transactions"]["columns"]:
    print(c)
