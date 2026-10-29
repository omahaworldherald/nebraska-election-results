#!/usr/bin/env python3
"""Split Nebraska's official All Contests CSV into election result feeds."""

import argparse
import csv
import io
import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

SOURCE = (
    'https://electionresults.nebraska.gov/'
    'resultsCSV.aspx?text=All&type=All&map=CTY'
)

REQUIRED = {
    'RaceID', 'RaceName', 'AreaNum', 'CandidateID', 'CandidateName',
    'PartyCode', 'CandidateVotes', 'PrecinctsReporting'
}
PARTIES = ('rep', 'dem', 'lib', 'lmn', 'nwp', 'afp', 'ind', 'oth')
DISPLAY_COLUMNS = [
    'Candidate', 'Pct.', 'Votes', 'Precincts Reporting', 'Called', 'Last Updated'
]
MEASURE_COLUMNS = [
    'Measure', 'For Pct.', 'Against Pct.', 'For Votes', 'Against Votes',
    'Precincts Reporting', 'Last Updated'
]


def write_csv(path, columns, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO(newline='')
    writer = csv.DictWriter(
        buf, fieldnames=columns, lineterminator='\n', extrasaction='ignore'
    )
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
    """Collapse whitespace, including nonbreaking spaces."""
    return ' '.join((value or '').split())


def read_calls(path):
    if not path.exists():
        return {}
    calls = {}
    with path.open(newline='', encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
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
    candidate_ids = {row['CandidateID'].strip() for row in subset}
    if selected and selected not in candidate_ids:
        raise ValueError(
            f'Called candidate {selected} not found in race {race_id}'
        )

    result = []
    for row in subset:
        name = clean_name(row['CandidateName'])
        if governor:
            name = re.split(
                r'\s+and\s+', name, maxsplit=1, flags=re.IGNORECASE
            )[0]

        party = (row.get('PartyCode') or '').strip().upper()
        if party == 'PET':
            party = 'IND'
        label = f'{name} ({party})' if party else name

        is_called = bool(selected and row['CandidateID'].strip() == selected)
        if is_called:
            label = '✓ ' + label

        match = re.search(
            r'(\d+)\s*/\s*(\d+)', row.get('PrecinctsReporting') or ''
        )
        reporting = (
            round(100 * int(match.group(1)) / int(match.group(2)), 1)
            if match and int(match.group(2))
            else ''
        )
        votes = int((row.get('CandidateVotes') or '0').replace(',', ''))
        pct = (row.get('CandidatePercentage') or '').strip().replace('%', '')
        try:
            pct = round(float(pct), 1) if pct else ''
        except ValueError:
            pct = ''

        result.append({
            'Candidate': label,
            'Pct.': pct,
            'Votes': votes,
            'Precincts Reporting': reporting,
            'Called': 'Yes' if is_called else 'No',
            'Last Updated': (row.get('CurrentDateTime') or '').strip(),
        })
    return result


def write_display(feeds, slug, subset, race_id, calls):
    write_csv(
        feeds / 'display' / f'{slug}.csv',
        DISPLAY_COLUMNS,
        display_rows(subset, race_id, calls, governor=(slug == 'governor')),
    )


def load_measure_descriptions(config):
    path = Path('config/ballot-measure-descriptions.json')
    descriptions = json.loads(path.read_text(encoding='utf-8'))
    expected = {str(rid) for rid in config['ballot_measure_ids']}
    if set(descriptions) != expected:
        raise ValueError(
            'Ballot description IDs do not match configured measures: '
            f'missing={sorted(expected - set(descriptions))}, '
            f'extra={sorted(set(descriptions) - expected)}'
        )
    for race_id, label in descriptions.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f'Ballot measure {race_id} has an invalid label')
    return descriptions


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
        manifest.append({
            'slug': slug,
            'race_id': str(race_id),
            'race_name': subset[0]['RaceName'],
            'feed': f'feeds/{slug}.csv',
        })

    measures = []
    for race_id in config['ballot_measure_ids']:
        subset = groups.get(str(race_id))
        if not subset:
            raise ValueError(f'Missing ballot measure {race_id}')
        measures.extend(subset)
    write_csv(feeds / 'ballot-measures.csv', columns, measures)
    for race_id in config['ballot_measure_ids']:
        write_display(
            feeds, f'measure-{race_id}', groups[str(race_id)], race_id, calls
        )

    descriptions = load_measure_descriptions(config)
    combined_rows = []
    common_reporting = set()
    common_updated = set()
    for race_id in config['ballot_measure_ids']:
        subset = groups[str(race_id)]
        choices = display_rows(subset, race_id, calls)
        # A called choice is labelled "✓ For" or "✓ Against" in its
        # individual feed. Strip that mark only for combined-feed matching.
        by_choice = {
            row['Candidate'].removeprefix('✓').strip().lower(): row
            for row in choices
        }
        if len(choices) != 2 or set(by_choice) != {'for', 'against'}:
            raise ValueError(
                f'Ballot measure {race_id} must have For and Against choices'
            )
        for_choice = by_choice['for']
        against_choice = by_choice['against']
        common_reporting.update(row['Precincts Reporting'] for row in choices)
        common_updated.update(row['Last Updated'] for row in choices)
        combined_rows.append({
            'Measure': descriptions[str(race_id)].strip(),
            'For Pct.': for_choice['Pct.'],
            'Against Pct.': against_choice['Pct.'],
            'For Votes': for_choice['Votes'],
            'Against Votes': against_choice['Votes'],
            'Precincts Reporting': for_choice['Precincts Reporting'],
            'Last Updated': for_choice['Last Updated'],
        })
    if len(common_reporting) != 1 or len(common_updated) != 1:
        raise ValueError(
            'Ballot measures have differing precinct reporting or timestamps'
        )
    write_csv(
        feeds / 'display' / 'ballot-measures-all.csv',
        MEASURE_COLUMNS,
        combined_rows,
    )

    # Combined Legislature results: one candidate row per configured district.
    legislature_ids = [str(rid) for rid in config.get('legislature_race_ids', [])]
    if legislature_ids:
        if len(legislature_ids) != len(set(legislature_ids)):
            raise ValueError('Duplicate legislature RaceIDs in config')
        legislature_rows = []
        districts_seen = set()
        for race_id in legislature_ids:
            subset = groups.get(race_id)
            if not subset:
                raise ValueError(f'Missing configured legislative race {race_id}')
            if any((row.get('AreaType') or '').strip().upper() != 'LD' for row in subset):
                raise ValueError(f'Race {race_id} is not a legislative district race')
            districts = {clean_name(row.get('AreaNum')) for row in subset}
            if len(districts) != 1:
                raise ValueError(f'Race {race_id} has inconsistent districts')
            district = districts.pop()

            # Remove leading zero from legislative district numbers.
            district = re.sub(
                r'\d+',
                lambda m: str(int(m.group())),
                district
            )

            if district in districts_seen:
                raise ValueError(f'Duplicate legislative district: {district}')
            districts_seen.add(district)
            for result in display_rows(subset, race_id, calls):
                # Legislature races are nonpartisan; omit the (NON) suffix.
                result['Candidate'] = re.sub(r'\s+\(NON\)$', '', result['Candidate'])

                # Show precinct reporting below the district heading in
                # Datawrapper, while retaining its separate CSV column.
                reporting = result['Precincts Reporting']
                reporting_text = (
                    f'{float(reporting):.1f}% precincts reporting'
                    if reporting != ''
                    else 'Precinct reporting unavailable'
                )
                district_label = f'{district}<br>{reporting_text}'
                legislature_rows.append({'District': district_label, **result})
        legislature_columns = ['District'] + DISPLAY_COLUMNS
        write_csv(
            feeds / 'display' / 'legislature-all.csv',
            legislature_columns,
            legislature_rows,
        )
        print(f'Legislature: {len(districts_seen)} districts, {len(legislature_rows)} candidates')

    congress_columns = [
        'district_keys', 'district', 'race_id', 'total_votes',
        'precincts_reporting', 'precincts_total', 'source_updated', 'has_results'
    ] + [
        f'{party}_{suffix}'
        for party in PARTIES
        for suffix in ('votes', 'pct')
    ]
    congress = []
    for district in (1, 2, 3):
        race_id = str(config['candidate_races'][f'house-{district}'])
        subset = groups[race_id]
        total = sum(
            int((row['CandidateVotes'] or '0').replace(',', ''))
            for row in subset
        )
        counts = {party: 0 for party in PARTIES}
        for row in subset:
            code = (row.get('PartyCode') or '').strip().lower()
            if code == 'pet':
                code = 'ind'
            votes = int((row['CandidateVotes'] or '0').replace(',', ''))
            counts[code if code in counts else 'oth'] += votes

        match = re.search(
            r'(\d+)\s*/\s*(\d+)', subset[0].get('PrecinctsReporting') or ''
        )
        done, all_precincts = (
            (int(match.group(1)), int(match.group(2)))
            if match else ('', '')
        )
        entry = {
            'district_keys': district,
            'district': f'NE-{district:02d}',
            'race_id': race_id,
            'total_votes': total,
            'precincts_reporting': done,
            'precincts_total': all_precincts,
            'source_updated': subset[0].get('CurrentDateTime', ''),
            'has_results': 'yes' if total else 'no',
        }
        for party in PARTIES:
            entry[f'{party}_votes'] = counts[party]
            entry[f'{party}_pct'] = (
                round(100 * counts[party] / total, 3) if total else 0
            )
        congress.append(entry)
    write_csv(feeds / 'congress.csv', congress_columns, congress)

    index = feeds / 'index.json'
    content = json.dumps(manifest, indent=2) + '\n'
    if not index.exists() or index.read_text(encoding='utf-8') != content:
        index.write_text(content, encoding='utf-8')
    print(
        f'OK: {len(records)} source rows; {len(manifest)} candidate feeds; '
        f'{len(config["ballot_measure_ids"])} ballot measures; '
        'congress map preserved'
    )


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
        request = urllib.request.Request(
            SOURCE,
            headers={
                'User-Agent': 'NebraskaElectionResults/1.0',
                'Accept': 'text/csv,*/*',
            },
        )
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
