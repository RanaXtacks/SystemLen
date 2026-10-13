import pathlib
import re

p = pathlib.Path("d:/PythonProjects/saleor/saleor")
real_sqls = []

for py in p.rglob("*.py"):
    if ".venv" in str(py):
        continue
    try:
        txt = py.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    
    # Matches cursor.execute(..., RunSQL(..., or .raw(...
    for m in re.finditer(r'(RunSQL|cursor\.execute|\.raw)\s*\(\s*([^,\)]+)', txt):
        real_sqls.append({
            "file": str(py.relative_to(p)),
            "call": m.group(1),
            "arg": m.group(2).strip()[:60]
        })

print(f"Total SQL call sites found in Saleor: {len(real_sqls)}")
for item in real_sqls[:15]:
    print(f"  [{item['call']}] {item['file']}: {item['arg']}")
