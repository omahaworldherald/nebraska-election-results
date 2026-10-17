#!/usr/bin/env python3
"""Small Nebraska results collector. Standard library only. No Datawrapper API."""
import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SOURCE = 'https://electionresults.nebraska.gov/resultsCSV.aspx?text=All&type=All&map=CTY'
REQUIRED = {'RaceID', 'RaceName', 'AreaType', 'AreaNum', 'CandidateID', 'CandidateName',
            'PartyCode', 'CandidateVotes', 'PrecinctsReporting', 'CurrentDateTime'}
PARTIES = ['REP', 'DEM', 'LIB', 'LMN', 'NWP', 'AFP', 'IND', 'OTH']
PARTY_NAMES = {'REP':'Republican', 'DEM':'Democratic', 'LIB':'Libertarian',
               'LMN':'Legal Marijuana NOW', 'NWP':'Nebraska Working People',
               'AFP':'America First', 'IND':'Independent', 'OTH':'Other', 'PET':'Petition'}
CANDIDATE_COLUMNS = ['Candidate', 'Party', 'Votes', 'Vote %', 'Precincts reporting %',
                     'Last updated', 'Race ID', 'Candidate ID']
MEASURE_COLUMNS = ['Ballot measure', 'For %', 'Against %', 'For votes', 'Against votes',
                   'Total votes', 'Precincts reporting %', 'Last updated', 'Has results']
CONGRESS_COLUMNS = ['district_keys','district','race_id','total_votes','precincts_reporting',
                    'precincts_total','source_updated','has_results'] + [f'{p.lower()}_{s}' for p in PARTIES for s in ('votes','pct')]

def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO(newline='')
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    content = buf.getvalue()
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        path.write_text(content, encoding='utf-8')

def reporting(raw):
    match = re.search(r'(\d+)\s*/\s*(\d+)', raw or '')
    if not match:
        return None, None, None
    done, total = map(int, match.groups())
    if total <= 0 or done > total:
        raise ValueError('Invalid precinct reporting: ' + str(raw))
    return done, total, round(100 * done / total, 1)

def read_source(data):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
        raise ValueError('Missing Nebraska CSV fields; refusing to overwrite feeds')
    rows = []
    for row in reader:
        if not row.get('RaceID') or not row.get('CandidateID'):
            continue
        row = {k: (v or '').strip() for k,v in row.items() if k is not None}
        row['CandidateVotes'] = int(row['CandidateVotes'].replace(',', ''))
        if row['CandidateVotes'] < 0:
            raise ValueError('Negative vote count')
        reporting(row['PrecinctsReporting'])
        rows.append(row)
    if not rows:
        raise ValueError('No candidate records')
    return rows

def results(rows, config, out):
    groups = defaultdict(list)
    for row in rows:
        groups[row['RaceID']].append(row)
    manifest = []
    for slug, race_id in config['candidate_races'].items():
        group = groups.get(str(race_id))
        if not group:
            raise ValueError(f'Configured race {race_id} ({slug}) missing from source')
        total = sum(r['CandidateVotes'] for r in group)
        display = []
        for r in group:
            _, _, pct_reporting = reporting(r['PrecinctsReporting'])
            display.append({'Candidate':' '.join(r['CandidateName'].split()),
                'Party':PARTY_NAMES.get(r['PartyCode'], r['PartyCode'] or 'Unknown'),
                'Votes':r['CandidateVotes'], 'Vote %':round(100*r['CandidateVotes']/total, 1) if total else '',
                'Precincts reporting %':pct_reporting if pct_reporting is not None else '',
                'Last updated':r['CurrentDateTime'], 'Race ID':race_id, 'Candidate ID':r['CandidateID']})
        display.sort(key=lambda r: (-r['Votes'], r['Candidate']))
        write_csv(out/'feeds'/f'{slug}.csv', CANDIDATE_COLUMNS, display)
        manifest.append({'slug':slug, 'race_id':race_id, 'title':group[0]['RaceName'],
                         'feed':f'feeds/{slug}.csv', 'has_results':bool(total)})
    measures = []
    for race_id in config['ballot_measure_ids']:
        group = groups.get(str(race_id))
        if not group:
            raise ValueError(f'Configured ballot measure {race_id} missing from source')
        choices = {}
        for r in group:
            name = ' '.join(r['CandidateName'].split()).lower()
            if name in ('for','yes','against','no'):
                key = 'for' if name in ('for','yes') else 'against'
                if key in choices:
                    raise ValueError(f'Duplicate ballot choice {key} for {race_id}')
                choices[key] = r['CandidateVotes']
        if set(choices) != {'for','against'}:
            raise ValueError(f'Unknown ballot choice labels for {race_id}: {[r["CandidateName"] for r in group]}')
        yes, no = choices['for'], choices['against']
        total = yes + no
        _, _, report_pct = reporting(group[0]['PrecinctsReporting'])
        measures.append({'Ballot measure':group[0]['RaceName'],
            'For %':round(100*yes/total, 1) if total else '',
            'Against %':round(100*no/total, 1) if total else '',
            'For votes':yes, 'Against votes':no, 'Total votes':total,
            'Precincts reporting %':report_pct if report_pct is not None else '',
            'Last updated':group[0]['CurrentDateTime'], 'Has results':'yes' if total else 'no'})
    write_csv(out/'feeds'/'ballot-measures.csv', MEASURE_COLUMNS, measures)
    congress = []
    for district in range(1,4):
        race_id = str(config['candidate_races'][f'house-{district}'])
        group = groups[race_id]
        total = sum(r['CandidateVotes'] for r in group)
        counts = {p:0 for p in PARTIES}
        for r in group:
            code = r['PartyCode']
            # Petition candidates remain in Other for the legacy map, not automatically Independent.
            counts[code if code in counts else 'OTH'] += r['CandidateVotes']
        done, n, report_pct = reporting(group[0]['PrecinctsReporting'])
        row = {'district_keys':district, 'district':f'NE-{district:02d}', 'race_id':race_id,
               'total_votes':total, 'precincts_reporting':done if done is not None else '',
               'precincts_total':n if n is not None else '',
               'source_updated':group[0]['CurrentDateTime'], 'has_results':'yes' if total else 'no'}
        for party in PARTIES:
            row[f'{party.lower()}_votes'] = counts[party]
            row[f'{party.lower()}_pct'] = round(100*counts[party]/total, 3) if total else 0
        congress.append(row)
    write_csv(out/'feeds'/'congress.csv', CONGRESS_COLUMNS, congress)
    (out/'feeds').mkdir(parents=True, exist_ok=True)
    manifest_path = out/'feeds'/'index.json'
    manifest_content = json.dumps(manifest, indent=2) + '\n'
    if not manifest_path.exists() or manifest_path.read_text() != manifest_content:
        manifest_path.write_text(manifest_content)
    return len(groups), len(measures)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', help='Local Nebraska CSV for testing (no network)')
    parser.add_argument('--output', default='public')
    parser.add_argument('--config', default='config/races.json')
    args = parser.parse_args()
    if args.input:
        raw = Path(args.input).read_bytes()
    else:
        request = urllib.request.Request(SOURCE, headers={'User-Agent':'NebraskaElectionResults/1.0', 'Accept':'text/csv,*/*'})
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read(10_000_001)
        if len(raw) > 10_000_000:
            raise ValueError('Oversized source response')
    rows = read_source(raw)
    output = Path(args.output)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    races, measures = results(rows, config, output)
    digest = hashlib.sha256(raw).hexdigest()
    # Snapshots are opt-in; avoid ballooning the Git repository on election night.
    if __import__('os').environ.get('SAVE_SNAPSHOTS') == '1':
        snapshot = output/'snapshots'/f'{digest[:20]}.csv'
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if not snapshot.exists():
            snapshot.write_bytes(raw)
    print(f'OK: {len(rows)} candidate records; {races} source races; {measures} measures; 3 congressional districts')

if __name__ == '__main__':
    main()
