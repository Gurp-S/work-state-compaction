import csv
import json
from pathlib import Path


def run(source, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with open(source, encoding='utf-8', errors='replace') as stream:
        rows = list(csv.DictReader(stream))
    total = sum(float(row['amount']) for row in rows)
    result = {'format': 'invoice.pipeline/1', 'total': total, 'rows': rows}
    (output/'manifest.json').write_text(json.dumps(result), encoding='utf-8')
    return result
