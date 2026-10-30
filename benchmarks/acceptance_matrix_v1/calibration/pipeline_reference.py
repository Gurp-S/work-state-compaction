"""Calibration-only immutable stage files and atomic manifest pointer."""
import csv
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import tempfile


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))+'\n').encode('utf-8')


def run(source, output):
    raw = Path(source).read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8'), newline=''), strict=True)
    try:
        if reader.fieldnames != ['tenant', 'invoice', 'amount']:
            raise ValueError('header_invalid')
        entries = list(reader)
    except csv.Error:
        raise ValueError('csv_invalid') from None
    unique = {}
    for row in entries:
        if set(row) != {'tenant', 'invoice', 'amount'} or any(type(v) is not str for v in row.values()):
            raise ValueError('row_invalid')
        tenant, invoice, amount = row['tenant'].strip(), row['invoice'].strip(), row['amount'].strip()
        if not tenant or not invoice or not re.fullmatch(r'-?[0-9]+(?:\.[0-9]{1,2})?', amount):
            raise ValueError('row_invalid')
        unsigned = amount.removeprefix('-')
        whole, _, fraction = unsigned.partition('.')
        cents = (int(whole)*100 + int((fraction+'00')[:2])) * (-1 if amount.startswith('-') else 1)
        key = (tenant, invoice)
        if key in unique and unique[key] != cents:
            raise ValueError('invoice_conflict')
        unique[key] = cents
    normalized = [dict(tenant=tenant, invoice=invoice, cents=cents) for (tenant, invoice), cents in sorted(unique.items())]
    groups = {}
    for row in normalized:
        group = groups.setdefault(row['tenant'], dict(tenant=row['tenant'], invoice_count=0, total_cents=0))
        group['invoice_count'] += 1
        group['total_cents'] += row['cents']
    totals = [groups[key] for key in sorted(groups)]
    payloads = {'normalized': encode(normalized), 'totals': encode(totals)}
    output = Path(output)
    generations = output/'generations'
    generation = sha256(raw).hexdigest()
    target = generations/generation
    generations.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix='.stage-', dir=generations) as temporary:
            staging = Path(temporary).resolve()
            if not staging.is_relative_to(generations.resolve()):
                raise ValueError('staging_scope_changed')
            for name, payload in payloads.items():
                (staging/(name+'.json')).write_bytes(payload)
            os.rename(staging, target)
    for name, payload in payloads.items():
        if (target/(name+'.json')).read_bytes() != payload:
            raise ValueError('generation_conflict')
    manifest = dict(format='invoice.pipeline/2', source_sha256=generation, stages={
        'normalized': dict(path=(target/'normalized.json').relative_to(output).as_posix(),
                           sha256=sha256(payloads['normalized']).hexdigest(), rows=len(normalized)),
        'totals': dict(path=(target/'totals.json').relative_to(output).as_posix(),
                       sha256=sha256(payloads['totals']).hexdigest(), from_sha256=sha256(payloads['normalized']).hexdigest(),
                       tenants=len(totals))})
    filename = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.manifest-', dir=output, delete=False) as stream:
            filename = Path(stream.name)
            stream.write(encode(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, output/'manifest.json')
    finally:
        if filename is not None and filename.exists():
            filename.unlink()
    return manifest
