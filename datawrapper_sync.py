#!/usr/bin/env python3
"""Manually sync one Nebraska election display CSV and status note to Datawrapper."""
import argparse
import csv
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = 'https://api.datawrapper.de/v3'

def request(method, path, token, data=None, content_type=None):
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as res:
            payload = res.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        message = exc.read().decode('utf-8', 'replace')[:600]
        raise RuntimeError(f'Datawrapper {method} {path}: HTTP {exc.code}: {message}') from exc

def load_csv(path):
    raw = path.read_bytes()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    expected = {'Candidate', 'Votes', 'Pct.', 'Precincts Reporting', 'Called', 'Last Updated'}
    if not rows or not expected.issubset(rows[0]):
        raise ValueError('Display feed missing rows or required columns')
    if len({row['Last Updated'] for row in rows}) > 1 or len({row['Precincts Reporting'] for row in rows}) > 1:
        raise ValueError('Conflicting reporting status or timestamps across candidates')
    if sum(row['Called'].strip().lower() == 'yes' for row in rows) > 1:
        raise ValueError('More than one called candidate')
    return raw, rows

def note(rows):
    reporting = rows[0]['Precincts Reporting'].strip()
    updated = rows[0]['Last Updated'].strip()
    if reporting:
        reporting = f'{reporting}% of precincts reporting'
    else:
        reporting = 'Precinct reporting unavailable'
    status = 'Unofficial results' if any(int(row['Votes'].replace(',', '')) > 0 for row in rows) else 'Awaiting results'
    called = [row['Candidate'] for row in rows if row['Called'].strip().lower() == 'yes']
    parts = [status, reporting]
    if updated:
        parts.append(f'Nebraska SOS updated: {updated}')
    if called:
        parts.append(f'Race called by Omaha World-Herald: {called[0]}')
    return ' | '.join(parts)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--chart-id', default=os.getenv('DATAWRAPPER_CHART_ID', ''))
    p.add_argument('--feed', default='public/feeds/display/house-1.csv')
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if not args.chart_id:
        p.error('Missing chart ID')
    raw, rows = load_csv(Path(args.feed))
    text = note(rows)
    print(f'Chart: {args.chart_id}; rows: {len(rows)}; CSV SHA256: {hashlib.sha256(raw).hexdigest()[:12]}')
    print('Proposed note:', text)
    if not args.apply:
        print('DRY RUN: no API requests or changes made')
        return
    token = os.environ.get('DATAWRAPPER_API_TOKEN')
    if not token:
        p.error('Missing DATAWRAPPER_API_TOKEN secret')
    chart = request('GET', f'/charts/{args.chart_id}', token)
    if chart.get('id') != args.chart_id:
        raise ValueError('Chart ID mismatch')
    # Avoid overwriting other annotate settings: preserve the metadata tree.
    metadata = chart.get('metadata') or {}
    annotate = dict(metadata.get('annotate') or {})
    annotate['notes'] = text
    # Upload then patch then publish. Failure stops the workflow; no false success.
    request('PUT', f'/charts/{args.chart_id}/data', token, raw, 'text/csv')
    request('PATCH', f'/charts/{args.chart_id}', token,
            json.dumps({'metadata': {'annotate': annotate}}).encode('utf-8'), 'application/json')
    request('POST', f'/charts/{args.chart_id}/publish', token, b'{}', 'application/json')
    print('Published updated chart:', args.chart_id)

if __name__ == '__main__':
    main()
