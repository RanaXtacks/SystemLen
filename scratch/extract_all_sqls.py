import pathlib
import re

p = pathlib.Path("d:/PythonProjects/saleor")
sqls = []

sql_pattern = re.compile(
    r'(?:"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"[^\n"]{20,}"|\'[^\n\']{20,}\')',
    re.MULTILINE
)

keywords = ["SELECT ", "UPDATE ", "INSERT INTO ", "DELETE FROM ", "ALTER TABLE "]

for py in p.rglob("*.py"):
    if ".venv" in str(py):
        continue
    try:
        txt = py.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    
    for m in sql_pattern.finditer(txt):
        raw = m.group(0).strip("\"'")
        upper = raw.upper()
        if any(kw in upper for kw in keywords):
            # Exclude markdown docstrings, comments, urls
            if len(raw) < 1500 and not raw.strip().startswith("http") and not raw.strip().startswith("```"):
                # Clean up whitespace
                clean_sql = " ".join(raw.split())
                sqls.append((str(py.relative_to(p)), clean_sql))

print(f"Total SQL string literals found in Saleor repository: {len(sqls)}")
for f, s in sqls[:15]:
    print(f"  [{f}]: {s[:80]}")
