#!/usr/bin/env python3
"""Split Nebraska's official All Contests CSV without changing source fields."""
import argparse
import csv
import io
import json
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


def build(columns, records, config, root):
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
        manifest.append({'slug': slug, 'race_id': str(race_id), 'race_name': subset[0]['RaceName'], 'feed': f'feeds/{slug}.csv'})
    measures = []
    for race_id in config['ballot_measure_ids']:
        subset = groups.get(str(race_id))
        if not subset:
            raise ValueError(f'Missing ballot measure {race_id}')
        measures.extend(subset)
    write_csv(feeds / 'ballot-measures.csv', columns, measures)

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
    build(columns, records, config, Path(args.output))


if __name__ == '__main__':
    main()
