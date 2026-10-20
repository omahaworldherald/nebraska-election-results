#!/usr/bin/env python3
"""Collect selected Sarpy County Clarity summary contests without touching SOS feeds."""
import argparse
import csv
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

COLUMNS = ['Candidate', 'Votes', 'Pct.', 'Precincts Reporting', 'Called', 'Last Updated']
PARTIES = {'REP':'REP','DEM':'DEM','LIB':'LIB','LMN':'LMN','NWP':'NWP','AFP':'AFP','PET':'IND','IND':'IND'}
REQUIRED = {'contest name','choice name','party name','total votes','percent of votes','num Precinct total','num Precinct rptg'}

def clean(value):
    return ' '.join((value or '').split())

def number(value):
    return int(clean(value).replace(',', '') or '0')

def write_if_changed(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.write_text(text, encoding='utf-8')

def csv_text(columns, rows):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator='\n', extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()

def get_zip(source):
    if source.startswith(('https://', 'http://')):
        req = urllib.request.Request(source, headers={'User-Agent': 'NebraskaElectionResults/1.0'})
        with urllib.request.urlopen(req, timeout=45) as response:
            data = response.read(10_000_001)
    else:
        data = Path(source).read_bytes()
    if len(data) > 10_000_000:
        raise ValueError('Oversized Clarity ZIP')
        print("Downloaded bytes:", len(data))
print("Response starts with:", repr(data[:150]))

if not data.startswith(b"PK"):
    raise ValueError(
        "Clarity did not return a ZIP file. "
        "The server may be returning HTML or an error response."
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        candidates = [n for n in archive.namelist() if Path(n).name.lower() == 'summary.csv']
        if len(candidates) != 1:
            raise ValueError('Expected exactly one summary.csv in ZIP')
        info = archive.getinfo(candidates[0])
        if info.file_size > 10_000_000:
            raise ValueError('Oversized summary.csv')
        raw = archive.read(candidates[0])
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if not REQUIRED.issubset(reader.fieldnames or []):
        raise ValueError(f'Clarity summary missing columns: {sorted(REQUIRED - set(reader.fieldnames or []))}')
    rows = list(reader)
    if not rows:
        raise ValueError('Clarity summary has no rows')
    return reader.fieldnames, rows

def convert(subset, calls, slug):
    output = []
    seen = set()
    reporting = set()
    for row in subset:
        name = clean(row['choice name'])
        if not name or name in seen:
            raise ValueError(f'{slug}: missing or duplicate candidate {name!r}')
        seen.add(name)
        party = clean(row['party name']).upper()
        party = PARTIES.get(party, party)
        label = f'{name} ({party})' if party else name
        votes = number(row['total votes'])
        done, total = number(row['num Precinct rptg']), number(row['num Precinct total'])
        if votes < 0 or done < 0 or total < 0 or done > total:
            raise ValueError(f'{slug}: invalid vote or precinct totals')
        pct = clean(row['percent of votes']).replace('%','')
        pct = round(float(pct), 1) if pct else ''
        reporting_pct = round(done * 100 / total, 1) if total else ''
        reporting.add(reporting_pct)
        is_called = calls.get(slug) == name
        output.append({'Candidate': ('✓ ' if is_called else '') + label,
                       'Votes': votes, 'Pct.': pct, 'Precincts Reporting': reporting_pct,
                       'Called': 'Yes' if is_called else 'No', 'Last Updated': ''})
    if len(reporting) != 1:
        raise ValueError(f'{slug}: inconsistent precinct reporting')
    if calls.get(slug) and calls[slug] not in seen:
        raise ValueError(f'{slug}: called candidate not found')
    if calls.get(slug) and not any(r['Votes'] > 0 for r in output):
        raise ValueError(f'{slug}: cannot call zero-vote race')
    return output

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--config', default='config/sarpy-races.json')
    p.add_argument('--input', help='Optional local ZIP for offline tests')
    p.add_argument('--output', default='public')
    args = p.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    if not config.get('contests'):
        raise ValueError('No Sarpy contests configured')
    source = args.input or config['source_url']
    columns, records = get_zip(source)
    calls = config.get('calls', {})
    out = Path(args.output) / 'feeds'
    planned = []
    slugs = set()
    for contest in config['contests']:
        slug, name = contest['slug'], contest['contest_name']
        if not re.fullmatch(r'sarpy-[a-z0-9]+(?:-[a-z0-9]+)*', slug) or slug in slugs:
            raise ValueError(f'Invalid/duplicate slug: {slug}')
        slugs.add(slug)
        subset = [r for r in records if clean(r['contest name']) == name]
        if not subset:
            raise ValueError(f'Contest not found in Sarpy ZIP: {name}')
        display = convert(subset, calls, slug)
        planned.append((slug, subset, display))
    # Validate all selected contests before writing any output.
    write_if_changed(out / 'sarpy' / 'summary.csv', csv_text(columns, records))
    for slug, subset, display in planned:
        write_if_changed(out / 'sarpy' / f'{slug}.csv', csv_text(columns, subset))
        write_if_changed(out / 'display' / f'{slug}.csv', csv_text(COLUMNS, display))
        print(f'{slug}: {len(display)} choices')
    print(f'OK: {len(records)} Clarity rows; {len(planned)} selected Sarpy contests')
    print('Clarity summary.zip has no official timestamp: Last Updated intentionally blank')

if __name__ == '__main__':
    main()
