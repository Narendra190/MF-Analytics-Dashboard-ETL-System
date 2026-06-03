import sqlite3
from pathlib import Path

SQL_FILE = Path('sql/queries.sql')
OUT_DIR = Path('reports/query_results')
OUT_DIR.mkdir(parents=True, exist_ok=True)

with SQL_FILE.open() as f:
    content = f.read()

import re
pattern = re.compile(r"-- Query:\s*(?P<name>[^\n]+)\n(?P<sql>.*?)(?=\n=+\n|\Z)", re.S)
matches = pattern.finditer(content)

conn = sqlite3.connect('bluestock_mf.db')
cur = conn.cursor()

summary = []
import csv
for m in matches:
    name = m.group('name').strip()
    sql = m.group('sql').strip()
    if not sql:
        continue
    # sanitize filename
    safe_name = ''.join(c if c.isalnum() or c in ('_', '-') else '_' for c in name)
    out_file = OUT_DIR / f"{safe_name}.csv"
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        with out_file.open('w', newline='', encoding='utf-8') as csvf:
            writer = csv.writer(csvf)
            if cols:
                writer.writerow(cols)
            writer.writerows(rows)
        summary.append((name, out_file, len(rows)))
        print(f"Wrote {len(rows)} rows to {out_file}")
    except Exception as e:
        print(f"Query {name} failed: {e}")

conn.close()
print('\nDone')
