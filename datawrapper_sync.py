#!/usr/bin/env python3
"""Sync configured Nebraska display feeds to existing Datawrapper charts.

State is saved only after successful publication. Commit the state file in GitHub
so scheduled runs can skip unchanged charts and retry failures.
"""
import argparse
import csv
import hashlib
import io
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

BASE = 'https://api.datawrapper.de/v3'
REQUIRED = {'Candidate', 'Votes', 'Pct.', 'Precincts Reporting', 'Called', 'Last Updated'}


def api(method, path, token, data=None, content_type=None):
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
    if content_type:
        headers['Content-Type'] = content_type
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', 'replace')[:600]
        raise RuntimeError(f'{method} {path}: HTTP {exc.code}: {body}') from exc


def load_feed(path):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    rows = list(reader)
    missing = REQUIRED - set(reader.fieldnames or [])
    if missing or not rows:
        raise ValueError(f'{path}: missing {sorted(missing)} or no candidate rows')
    if len({r['Last Updated'].strip() for r in rows}) != 1:
        raise ValueError(f'{path}: inconsistent source timestamps')
    if len({r['Precincts Reporting'].strip() for r in rows}) != 1:
        raise ValueError(f'{path}: inconsistent reporting percentages')
    if sum(r['Called'].strip().lower() == 'yes' for r in rows) > 1:
        raise ValueError(f'{path}: multiple called candidates')
    for row in rows:
        if int(row['Votes'].replace(',', '')) < 0:
            raise ValueError(f'{path}: negative votes')
    return raw, rows


from datetime import datetime

def note(rows):
    reporting = rows[0]['Precincts Reporting'].strip()
    updated = rows[0]['Last Updated'].strip()

    # Always display reporting percentage
    try:
        reporting_pct = f"{float(reporting):.1f}%"
    except (ValueError, TypeError):
        reporting_pct = "0.0%"

    # Format Nebraska's timestamp
    formatted_time = ""

    if updated:
        try:
            dt = datetime.strptime(
                updated,
                "%m/%d/%Y %I:%M:%S %p"
            )

            hour = dt.strftime("%I").lstrip("0")
            minute = dt.strftime("%M")
            am_pm = dt.strftime("%p").lower()
            month = dt.strftime("%b")
            day = dt.day
            year = dt.year

            formatted_time = (
                f"{hour}:{minute} {am_pm[0]}.m., "
                f"{month}. {day}, {year}"
            )

        except ValueError:
            formatted_time = updated

    parts = [
        f"{reporting_pct} precincts reporting"
    ]

    if formatted_time:
        parts.append(f"Updated {formatted_time}")

    # Include editorial race call when applicable
    called = [
        row['Candidate']
        for row in rows
        if row['Called'].strip().lower() == 'yes'
    ]

    if called:
        parts.append("✓ Race called by Omaha World-Herald")

    return " · ".join(parts)


def chart_config(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        if not {'chart_id', 'feed', 'enabled'}.issubset(reader.fieldnames or []):
            raise ValueError('Chart config must contain chart_id,feed,enabled')
        seen = set()
        result = []
        for row in reader:
            enabled = (row.get('enabled') or '').strip().lower()
            if enabled not in ('yes', 'no'):
                raise ValueError(f'Invalid enabled value: {enabled}')
            if enabled == 'no':
                continue
            chart_id = (row.get('chart_id') or '').strip()
            feed = (row.get('feed') or '').strip()
            if not chart_id or not feed or chart_id in seen:
                raise ValueError(f'Invalid or duplicate chart config: {row}')
            seen.add(chart_id)
            # Only read files within the expected public display directory.
            path_value = Path(feed)
            if path_value.is_absolute() or '..' in path_value.parts or path_value.suffix.lower() != '.csv':
                raise ValueError(f'Unsafe feed name: {feed}')
            result.append((chart_id, Path('public/feeds/display') / path_value))
    return result


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config/datawrapper-charts.csv')
    parser.add_argument('--state', default='config/datawrapper-published.json')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    configs = chart_config(Path(args.config))
    state_path = Path(args.state)
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    token = os.getenv('DATAWRAPPER_API_TOKEN') if args.apply else None
    if args.apply and not token:
        parser.error('DATAWRAPPER_API_TOKEN is missing')
    failures = []
    for chart_id, feed in configs:
        try:
            raw, rows = load_feed(feed)
            notes = make_note(rows)
            fingerprint = hashlib.sha256(raw + b'\nNOTES\n' + notes.encode('utf-8')).hexdigest()
            if not args.force and state.get(chart_id) == fingerprint:
                print(f'{chart_id}: unchanged, skipped')
                continue
            print(f'{chart_id}: {feed} ({len(rows)} rows); note: {notes}')
            if not args.apply:
                print(f'{chart_id}: DRY RUN; no API requests')
                continue
            chart = api('GET', f'/charts/{chart_id}', token)
            if chart.get('id') != chart_id:
                raise ValueError(f'Unexpected chart ID for {chart_id}')
            annotate = dict((chart.get('metadata') or {}).get('annotate') or {})
            annotate['notes'] = notes
            api('PUT', f'/charts/{chart_id}/data', token, raw, 'text/csv')
            api('PATCH', f'/charts/{chart_id}', token,
                json.dumps({'metadata': {'annotate': annotate}}).encode('utf-8'), 'application/json')
            api('POST', f'/charts/{chart_id}/publish', token, b'{}', 'application/json')
            state[chart_id] = fingerprint
            save_state(state_path, state)
            print(f'{chart_id}: published successfully')
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f'{chart_id}: FAILED: {exc}', flush=True)
            failures.append(chart_id)
    if failures:
        raise SystemExit(f'Failed charts: {", ".join(failures)}')


if __name__ == '__main__':
    main()
