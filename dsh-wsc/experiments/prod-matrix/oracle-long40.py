"""Final-state oracle for long-40: grade the workspace, not just the last answer.

Each check is a fact a later round built on. A checkpoint can lose an earlier
requirement while the final answer still sounds right; these checks catch that.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'runs' / 'long-40'


def read(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return ''


def run(ws: Path, args: list[str], timeout: int = 120) -> str:
    try:
        result = subprocess.run(['node', *args], cwd=ws, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout, shell=False)
        return (result.stdout or '') + (result.stderr or '')
    except Exception as error:
        return f'<failed: {error}>'


def checks(ws: Path) -> list[tuple[str, bool, str]]:
    src = {name: read(ws / 'src' / f'{name}.js') for name in ('format', 'store', 'report', 'cli')}
    tests = {path.name: read(path) for path in sorted((ws / 'tests').glob('*.mjs'))} if (ws / 'tests').exists() else {}
    readme = read(ws / 'README.md')
    changelog = read(ws / 'CHANGELOG.md')
    everything = '\n'.join(src.values()) + '\n' + '\n'.join(tests.values())
    out = []

    def add(label: str, ok: bool, detail: str = '') -> None:
        out.append((label, bool(ok), detail))

    add('format: formatCents present', 'formatCents' in src['format'])
    add('format: negative sign before $', bool(
        re.search(r"sign\s*=\s*[^\n]*<\s*0", src['format']) or '-$${' in src['format']))
    add('format: group option', re.search(r'group', src['format']) is not None)
    add('format: centsToAmount helper', 'centsToAmount' in src['format'])
    add('store: TAX_RATE', re.search(r'TAX_RATE[\s\S]{0,120}?0\.07', src['store']) is not None)
    add('store: taxCents(cents, rate)', re.search(r'taxCents\s*\([^)]*rate', src['store']) is not None)
    add('store: half-even rounding', 'half-even' in src['store'])
    add('store: TAX_RATE env override', re.search(r'process\.env\.TAX_RATE|envRate', src['store']) is not None)
    add('store: negative quantity RangeError', re.search(r'negative', src['store'], re.I) is not None and
        'RangeError' in src['store'])
    add('report: REPORT_LIMIT default 20', re.search(r'REPORT_LIMIT', src['report']) is not None and
        re.search(r'20', src['report']) is not None)
    add('report: limit after sorting', 'sort(' in src['report'] and 'slice(' in src['report'] and
        src['report'].find('sort(') < src['report'].find('slice('))
    add('report: sort by amountCents', re.search(r'amountCents', src['report']) is not None and
        re.search(r'\.sort\(|sort\s*===', src['report']) is not None)
    add('report: SKU AMOUNT header', re.search(r'SKU\s+AMOUNT', src['report']) is not None)
    add('report: TOTAL line', re.search(r'TOTAL', src['report']) is not None)
    add('report: totalCents', 'totalCents' in src['report'])
    add('report: toCsv header', re.search(r'sku,amountCents', src['report']) is not None)
    add('report: amountWithTaxCents column', 'amountWithTaxCents' in src['report'])
    add('report: negative CSV throws', re.search(r'negative amounts are not allowed|csv[^\n]*negative', src['report'], re.I) is not None)
    add('report: summary(rows)', re.search(r'export function summary|function summary', src['report']) is not None)
    add('report: categories from SKU prefix', 'categories' in src['report'])
    add('report: buildJsonReport', 'buildJsonReport' in src['report'])
    add('report: split/dash prefix', re.search(r"split\('-'\)|split\(\"-\"\)|indexOf\('-'\)", src['report']) is not None)
    add('cli: parseArgs exported', re.search(r'export function parseArgs', src['cli']) is not None)
    for flag in ('--limit', '--json', '--csv', '--round', '--sort', '--no-header', '--dry-run'):
        add(f'cli: {flag}', flag in src['cli'])
    add('cli: csv precedence over json', re.search(r'csv[\s\S]{0,200}json', src['cli']) is not None)
    add('README: --limit', '--limit' in readme)
    add('README: --json', '--json' in readme)
    add('README: --csv', '--csv' in readme)
    add('README: TAX_RATE', 'TAX_RATE' in readme)
    add('README: --round', '--round' in readme)
    add('README: summary/validation', re.search(r'summary|categories|negative', readme, re.I) is not None)
    add('CHANGELOG: Unreleased bullets', '## Unreleased' in changelog and changelog.count('\n- ') >= 3)
    add('tests: format edge/negative', any('format' in name and re.search(r'negative|-350|-5', text) for name, text in tests.items()))
    add('tests: sort order', any(re.search(r'sort', text, re.I) and re.search(r'C-300|order', text) for text in tests.values()))
    add('tests: csv', any('toCsv' in text for text in tests.values()))
    add('tests: round mode', any('half-even' in text for text in tests.values()))
    add('tests: categories', any('categories' in text for text in tests.values()))

    npm = run(ws, ['--test', '--experimental-test-isolation=none'])
    pass_match = re.search(r'\u2139 pass (\d+)', npm)
    fail_match = re.search(r'\u2139 fail (\d+)', npm)
    add('tests: npm test passes', pass_match is not None and (fail_match is None or int(fail_match.group(1)) == 0),
        f"pass={pass_match.group(1) if pass_match else '?'} fail={fail_match.group(1) if fail_match else '?'}")

    text_out = run(ws, ['src/cli.js', 'data/sample.json'])
    add('cli run: text header', re.search(r'SKU\s+AMOUNT', text_out) is not None)
    add('cli run: TOTAL line', re.search(r'TOTAL\s+\$', text_out) is not None)
    add('cli run: no error', 'Error' not in text_out and 'RangeError' not in text_out)
    csv_out = run(ws, ['src/cli.js', 'data/sample.json', '--csv'])
    add('cli run: csv header', csv_out.splitlines()[:1] == ['sku,amountCents,amountWithTaxCents'] or
        csv_out.startswith('sku,amountCents,amountWithTaxCents'))
    json_out = run(ws, ['src/cli.js', 'data/sample.json', '--json'])
    try:
        payload = json.loads(json_out)
        add('cli run: json summary', isinstance(payload, dict) and 'summary' in payload)
        add('cli run: json categories', isinstance(payload, dict) and 'categories' in payload)
    except Exception:
        add('cli run: json summary', False, json_out[:80])
        add('cli run: json categories', False)
    sku_out = run(ws, ['src/cli.js', 'data/sample.json', '--sort', 'sku'])
    add('cli run: sort sku', 'A-100' in sku_out and 'B-200' in sku_out and 'Error' not in sku_out)
    round_out = run(ws, ['src/cli.js', 'data/sample.json', '--round', 'half-even'])
    add('cli run: round half-even', 'Error' not in round_out and 'unsupported rounding' not in round_out)
    noheader = run(ws, ['src/cli.js', 'data/sample.json', '--no-header'])
    add('cli run: no-header', not re.search(r'SKU\s+AMOUNT', noheader) and 'TOTAL' in noheader)
    dry = run(ws, ['src/cli.js', 'data/sample.json', '--dry-run'])
    add('cli run: dry-run', 'Error' not in dry and ('would' in dry.lower() or 'dry' in dry.lower()))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--arms', default='v2f,v2,native,w80,ledger')
    parser.add_argument('--reps', default='')
    args = parser.parse_args()
    only = {int(x) for x in args.reps.split(',') if x.strip()} if args.reps else None
    for arm in [a.strip() for a in args.arms.split(',') if a.strip()]:
        for directory in sorted((RUNS / arm).glob('rep*')):
            if only and int(directory.name[3:]) not in only:
                continue
            if not (directory / 'done').exists():
                continue
            results = checks(directory / 'ws')
            passed = sum(1 for _, ok, _ in results if ok)
            failed = [label for label, ok, _ in results if not ok]
            print(f"{arm}/{directory.name}: {passed}/{len(results)}  failed={failed}")


if __name__ == '__main__':
    main()
