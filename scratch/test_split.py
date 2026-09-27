import re

sql_text = """
CREATE TABLE IF NOT EXISTS public.transactions (
    id SERIAL PRIMARY KEY,
    payment_method_id INT NOT NULL,  -- Undeclared reference to payment_methods(id)
    invoice_id INT,                  -- Undeclared reference to invoices(id)
    amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

# Strip comments
clean_lines = []
for line in sql_text.splitlines():
    line = re.sub(r"--.*$", "", line).strip()
    if line:
        clean_lines.append(line)
clean_sql = "\n".join(clean_lines)

# Extract body
m = re.search(r"\((.*?)\);", clean_sql, re.DOTALL)
body = m.group(1)

def split_columns(body: str) -> list[str]:
    items = []
    current = []
    depth = 0
    for char in body:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        items.append("".join(current).strip())
    return [i for i in items if i]

cols = split_columns(body)
for c in cols:
    print("COL:", repr(c))
