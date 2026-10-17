#!/usr/bin/env python3
"""Split Nebraska's official All Contests CSV without changing source fields."""
import argparse
import csv
import io
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

SOURCE = 'https://electionresults.nebraska.gov/resultsCSV.aspx?text=All&type=All&map=CTY'
REQUIRED = {'RaceID', 'RaceName', 'AreaNum', 'CandidateID', 'CandidateName',
            'PartyCode', 'CandidateVotes', 'PrecinctsReporting'}
PARTIES = ('rep', 'dem', 'lib', 'lmn', 'nwp', 'afp', 'ind', 'oth')


def write_csv(path, columns, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO(newline='')
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator='\n', extrasaction='ignore')
    writer.writeheader()
    writer.writerows(records)
    content = buf.getvalue()
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        path.write_text(content, encoding='utf-8')


def parse(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    columns = reader.fieldnames
    if not columns or not REQUIRED.issubset(columns):
        raise ValueError('Missing required Nebraska CSV columns')
    records = []
    for row in reader:
        if not row.get('RaceID') or not row.get('CandidateID'):
            continue
        if int((row.get('CandidateVotes') or '0').replace(',', '')) < 0:
            raise ValueError('Negative vote total')
        records.append(row)
    if not records:
        raise ValueError('No candidate records in source')
    return columns, records



def clean_name(value):
    """Collapse repeated spaces, including nonbreaking spaces, without changing spelling."""
    return ' '.join((value or '').split())


def read_calls(path):
    if not path.exists():
        return {}
    calls = {}
    with path.open(newline='', encoding='utf-8-sig') as file:
        for row in csv.DictReader(file):
            race_id = (row.get('race_id') or '').strip()
            candidate_id = (row.get('candidate_id') or '').strip()
            status = (row.get('status') or '').strip().lower()
            if not race_id and not candidate_id and not status:
                continue
            if status not in ('called', 'retracted'):
                raise ValueError(f'Invalid race-call status for {race_id}: {status}')
            if not race_id:
                raise ValueError('Race call is missing race_id')
            if status == 'called' and not candidate_id:
                raise ValueError(f'Called race {race_id} is missing candidate_id')
            if race_id in calls:
                raise ValueError(f'Duplicate race call entry: {race_id}')
            calls[race_id] = candidate_id if status == 'called' else None
    return calls


def display_rows(subset, race_id, calls, governor=False):
    selected = calls.get(str(race_id))
    candidate_ids = {r['CandidateID'].strip() for r in subset}
    if selected and selected not in candidate_ids:
        raise ValueError(f'Called candidate {selected} not found in race {race_id}')
    # Do not permit an accidental call on a contest with no votes reported.
    if selected and not any(int((r.get('CandidateVotes') or '0').replace(',', '')) > 0 for r in subset):
        raise ValueError(f'Race {race_id} has zero votes; remove the call until results are available')
    result = []
    for row in subset:
        name = clean_name(row['CandidateName'])
        if governor:
            # Governor/Lt. Governor ticket: show only the governor's name.
            name = re.split(r'\s+and\s+', name, maxsplit=1, flags=re.IGNORECASE)[0]
        party = (row.get('PartyCode') or '').strip().upper()
        label = f'{name} ({party})' if party else name
        is_called = bool(selected and row['CandidateID'].strip() == selected)
        if is_called:
            label = '✓ ' + label
        match = re.search(r'(\d+)\s*/\s*(\d+)', row.get('PrecinctsReporting') or '')
        reporting = round(100 * int(match.group(1)) / int(match.group(2)), 1) if match and int(match.group(2)) else ''
        votes = int((row.get('CandidateVotes') or '0').replace(',', ''))
        pct = (row.get('CandidatePercentage') or '').strip().replace('%', '')
        try:
            pct = round(float(pct), 1) if pct else ''
        except ValueError:
            pct = ''
        result.append({'Candidate': label, 'Votes': votes, 'Pct.': pct,
                       'Precincts Reporting': reporting, 'Called': 'Yes' if is_called else 'No'})
    return result


def write_display(feeds, slug, subset, race_id, calls):
    columns = ['Candidate', 'Votes', 'Pct.', 'Precincts Reporting', 'Called']
    write_csv(feeds / 'display' / f'{slug}.csv', columns, display_rows(subset, race_id, calls, governor=(slug == 'governor')))


def build(columns, records, config, root, calls):
    feeds = root / 'feeds'
    groups = defaultdict(list)
    for row in records:
        groups[row['RaceID']].append(row)
    write_csv(feeds / 'all-contests.csv', columns, records)
    manifest = []
    for slug, race_id in config['candidate_races'].items():
        subset = groups.get(str(race_id))
        if not subset:
            raise ValueError(f'Missing configured race {slug}: {race_id}')
        write_csv(feeds / f'{slug}.csv', columns, subset)
        write_display(feeds, slug, subset, race_id, calls)
        manifest.append({'slug': slug, 'race_id': str(race_id), 'race_name': subset[0]['RaceName'], 'feed': f'feeds/{slug}.csv'})
    measures = []
    for race_id in config['ballot_measure_ids']:
        subset = groups.get(str(race_id))
        if not subset:
            raise ValueError(f'Missing ballot measure {race_id}')
        measures.extend(subset)
    write_csv(feeds / 'ballot-measures.csv', columns, measures)
    for race_id in config['ballot_measure_ids']:
        write_display(feeds, f'measure-{race_id}', groups[str(race_id)], race_id, calls)

    # Compatibility exception: the existing congressional choropleth needs one row per district.
    congress_columns = ['district_keys', 'district', 'race_id', 'total_votes', 'precincts_reporting',
                        'precincts_total', 'source_updated', 'has_results'] + [f'{p}_{suffix}' for p in PARTIES for suffix in ('votes', 'pct')]
    congress = []
    for district in (1, 2, 3):
        race_id = str(config['candidate_races'][f'house-{district}'])
        subset = groups[race_id]
        total = sum(int((r['CandidateVotes'] or '0').replace(',', '')) for r in subset)
        counts = {p: 0 for p in PARTIES}
        for r in subset:
            code = (r['PartyCode'] or '').lower()
            counts[code if code in counts else 'oth'] += int((r['CandidateVotes'] or '0').replace(',', ''))
        import re
        match = re.search(r'(\d+)\s*/\s*(\d+)', subset[0].get('PrecinctsReporting') or '')
        done, all_precincts = (int(match.group(1)), int(match.group(2))) if match else ('', '')
        entry = {'district_keys': district, 'district': f'NE-{district:02d}', 'race_id': race_id,
                 'total_votes': total, 'precincts_reporting': done, 'precincts_total': all_precincts,
                 'source_updated': subset[0]['CurrentDateTime'], 'has_results': 'yes' if total else 'no'}
        for party in PARTIES:
            entry[f'{party}_votes'] = counts[party]
            entry[f'{party}_pct'] = round(100 * counts[party] / total, 3) if total else 0
        congress.append(entry)
    write_csv(feeds / 'congress.csv', congress_columns, congress)
    index = feeds / 'index.json'
    content = json.dumps(manifest, indent=2) + '\n'
    if not index.exists() or index.read_text(encoding='utf-8') != content:
        index.write_text(content, encoding='utf-8')
    print(f'OK: {len(records)} source rows; {len(manifest)} candidate feeds; {len(config["ballot_measure_ids"])} ballot measures; congress map preserved')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', help='Local CSV for testing')
    parser.add_argument('--output', default='public')
    parser.add_argument('--config', default='config/races.json')
    parser.add_argument('--calls', default='config/race-calls.csv')
    args = parser.parse_args()
    if args.input:
        raw = Path(args.input).read_bytes()
    else:
        request = urllib.request.Request(SOURCE, headers={'User-Agent': 'NebraskaElectionResults/1.0', 'Accept': 'text/csv,*/*'})
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read(10_000_001)
        if len(raw) > 10_000_000:
            raise ValueError('Oversized source response')
    columns, records = parse(raw)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    calls = read_calls(Path(args.calls))
    build(columns, records, config, Path(args.output), calls)


if __name__ == '__main__':
    main()
