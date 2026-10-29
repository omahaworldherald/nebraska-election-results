
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
    'RaceID',
    'RaceName',
    'AreaNum',
    'CandidateID',
    'CandidateName',
    'PartyCode',
    'CandidateVotes',
    'PrecinctsReporting'
}

PARTIES = (
    'rep', 'dem', 'lib', 'lmn',
    'nwp', 'afp', 'ind', 'oth'
)


def write_csv(path, columns, records):
    path.parent.mkdir(parents=True, exist_ok=True)

    buf = io.StringIO(newline='')

    writer = csv.DictWriter(
        buf,
        fieldnames=columns,
        lineterminator='\n',
        extrasaction='ignore'
    )

    writer.writeheader()
    writer.writerows(records)

    content = buf.getvalue()

    if (
        not path.exists()
        or path.read_text(encoding='utf-8') != content
    ):
        path.write_text(content, encoding='utf-8')


def parse(raw):
    reader = csv.DictReader(
        io.StringIO(raw.decode('utf-8-sig'))
    )

    columns = reader.fieldnames

    if not columns or not REQUIRED.issubset(columns):
        raise ValueError(
            'Missing required Nebraska CSV columns'
        )

    records = []

    for row in reader:
        if not row.get('RaceID') or not row.get('CandidateID'):
            continue

        votes = int(
            (row.get('CandidateVotes') or '0')
            .replace(',', '')
        )

        if votes < 0:
            raise ValueError('Negative vote total')

        records.append(row)

    if not records:
        raise ValueError(
            'No candidate records in source'
        )

    return columns, records


def clean_name(value):
    """Collapse repeated spaces, including nonbreaking spaces."""
    return ' '.join((value or '').split())


def read_calls(path):
    if not path.exists():
        return {}

    calls = {}

    with path.open(
        newline='',
        encoding='utf-8-sig'
    ) as file:

        for row in csv.DictReader(file):
            race_id = (
                row.get('race_id') or ''
            ).strip()

            candidate_id = (
                row.get('candidate_id') or ''
            ).strip()

            status = (
                row.get('status') or ''
            ).strip().lower()

            if not race_id and not candidate_id and not status:
                continue

            if status not in ('called', 'retracted'):
                raise ValueError(
                    f'Invalid race-call status for {race_id}: {status}'
                )

            if not race_id:
                raise ValueError(
                    'Race call is missing race_id'
                )

            if status == 'called' and not candidate_id:
                raise ValueError(
                    f'Called race {race_id} is missing candidate_id'
                )

            if race_id in calls:
                raise ValueError(
                    f'Duplicate race call entry: {race_id}'
                )

            calls[race_id] = (
                candidate_id
                if status == 'called'
                else None
            )

    return calls


def display_rows(subset, race_id, calls, governor=False):
    selected = calls.get(str(race_id))

    candidate_ids = {
        r['CandidateID'].strip()
        for r in subset
    }

    if selected and selected not in candidate_ids:
        raise ValueError(
            f'Called candidate {selected} '
            f'not found in race {race_id}'
        )

    result = []

    for row in subset:
        # Clean candidate name.
        name = clean_name(
            row['CandidateName']
        )

        # Governor/Lt. Governor ticket:
        # Show only the governor's name.
        if governor:
            name = re.split(
                r'\s+and\s+',
                name,
                maxsplit=1,
                flags=re.IGNORECASE
            )[0]

        # Convert petition candidates to Independent
        # for display only.
        party = (
            row.get('PartyCode') or ''
        ).strip().upper()

        if party == 'PET':
            party = 'IND'

        label = (
            f'{name} ({party})'
            if party
            else name
        )

        # Editorial race call.
        is_called = bool(
            selected
            and row['CandidateID'].strip() == selected
        )

        if is_called:
            label = '✓ ' + label

        # Convert precinct counts to percentage.
        match = re.search(
            r'(\d+)\s*/\s*(\d+)',
            row.get('PrecinctsReporting') or ''
        )

        reporting = (
            round(
                100
                * int(match.group(1))
                / int(match.group(2)),
                1
            )
            if match and int(match.group(2))
            else ''
        )

        # Raw votes.
        votes = int(
            (row.get('CandidateVotes') or '0')
            .replace(',', '')
        )

        # Candidate percentage.
        pct = (
            (row.get('CandidatePercentage') or '')
            .strip()
            .replace('%', '')
        )

        try:
            pct = (
                round(float(pct), 1)
                if pct
                else ''
            )
        except ValueError:
            pct = ''

        # Official Nebraska results timestamp.
        last_updated = (
            row.get('CurrentDateTime') or ''
        ).strip()

        result.append({
            'Candidate': label,
            'Votes': votes,
            'Pct.': pct,
            'Precincts Reporting': reporting,
            'Called': (
                'Yes' if is_called else 'No'
            ),
            'Last Updated': last_updated
        })

    return result


def write_display(
    feeds,
    slug,
    subset,
    race_id,
    calls
):
    columns = [
        'Candidate',
        'Pct.',
        'Votes',
        'Precincts Reporting',
        'Called',
        'Last Updated'
    ]

    write_csv(
        feeds / 'display' / f'{slug}.csv',
        columns,
        display_rows(
            subset,
            race_id,
            calls,
            governor=(slug == 'governor')
        )
    )


def build(columns, records, config, root, calls):
    feeds = root / 'feeds'

    groups = defaultdict(list)

    for row in records:
        groups[row['RaceID']].append(row)

    # Preserve original Nebraska data.
    write_csv(
        feeds / 'all-contests.csv',
        columns,
        records
    )

    manifest = []

    # Candidate races.
    for slug, race_id in config['candidate_races'].items():
        subset = groups.get(str(race_id))

        if not subset:
            raise ValueError(
                f'Missing configured race {slug}: {race_id}'
            )

        # Original passthrough.
        write_csv(
            feeds / f'{slug}.csv',
            columns,
            subset
        )

        # Clean display feed.
        write_display(
            feeds,
            slug,
            subset,
            race_id,
            calls
        )

        manifest.append({
            'slug': slug,
            'race_id': str(race_id),
            'race_name': subset[0]['RaceName'],
            'feed': f'feeds/{slug}.csv'
        })

    # Statewide ballot measures.
    measures = []

    for race_id in config['ballot_measure_ids']:
        subset = groups.get(str(race_id))

        if not subset:
            raise ValueError(
                f'Missing ballot measure {race_id}'
            )

        measures.extend(subset)

    write_csv(
        feeds / 'ballot-measures.csv',
        columns,
        measures
    )

    for race_id in config['ballot_measure_ids']:
        write_display(
            feeds,
            f'measure-{race_id}',
            groups[str(race_id)],
            race_id,
            calls
        )

    # Editorial labels are keyed by official RaceID, never CSV row order.
    description_path = Path('config/ballot-measure-descriptions.json')
    descriptions = json.loads(description_path.read_text(encoding='utf-8'))
    expected_ids = {str(rid) for rid in config['ballot_measure_ids']}
    if set(descriptions) != expected_ids:
        raise ValueError(
            'Ballot description IDs do not match configured measures: '
            f'missing={sorted(expected_ids - set(descriptions))}, '
            f'extra={sorted(set(descriptions) - expected_ids)}'
        )
    for rid, label in descriptions.items():
        if not isinstance(label, str) or not label.strip():
            raise ValueError(f'Ballot measure {rid} has an empty or invalid label')

    # Combined four-measure table: one row per statewide measure.
    # Keep individual measure feeds unchanged for existing embeds.
    combined_rows = []
    common_reporting = set()
    common_updated = set()
    for race_id in config['ballot_measure_ids']:
        subset = groups[str(race_id)]
        choices = display_rows(subset, race_id, calls)
        by_choice = {r['Candidate'].strip().lower(): r for r in choices}
        if len(choices) != 2 or set(by_choice) != {'for', 'against'}:
            raise ValueError(f'Ballot measure {race_id} must have For and Against choices')
        for_choice = by_choice['for']
        against_choice = by_choice['against']
        common_reporting.update(r['Precincts Reporting'] for r in choices)
        common_updated.update(r['Last Updated'] for r in choices)
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
        raise ValueError('Ballot measures have differing precinct reporting or timestamps')
    measure_columns = [
        'Measure', 'For Pct.', 'Against Pct.', 'For Votes',
        'Against Votes', 'Precincts Reporting', 'Last Updated'
    ]
    write_csv(feeds / 'display' / 'ballot-measures-all.csv',
              measure_columns, combined_rows)

    # Congressional choropleth compatibility feed.
    congress_columns = [
        'district_keys',
        'district',
        'race_id',
        'total_votes',
        'precincts_reporting',
        'precincts_total',
        'source_updated',
        'has_results'
    ] + [
        f'{p}_{suffix}'
        for p in PARTIES
        for suffix in ('votes', 'pct')
    ]

    congress = []

    for district in (1, 2, 3):
        race_id = str(
            config['candidate_races'][
                f'house-{district}'
            ]
        )

        subset = groups[race_id]

        total = sum(
            int(
                (r['CandidateVotes'] or '0')
                .replace(',', '')
            )
            for r in subset
        )

        counts = {
            p: 0
            for p in PARTIES
        }

        for r in subset:
            code = (
                (r.get('PartyCode') or '')
                .strip()
                .lower()
            )

            # Petition candidates count as Independent.
            if code == 'pet':
                code = 'ind'

            votes = int(
                (r['CandidateVotes'] or '0')
                .replace(',', '')
            )

            counts[
                code if code in counts else 'oth'
            ] += votes

        match = re.search(
            r'(\d+)\s*/\s*(\d+)',
            subset[0].get('PrecinctsReporting') or ''
        )

        done, all_precincts = (
            (
                int(match.group(1)),
                int(match.group(2))
            )
            if match
            else ('', '')
        )

        entry = {
            'district_keys': district,
            'district': f'NE-{district:02d}',
            'race_id': race_id,
            'total_votes': total,
            'precincts_reporting': done,
            'precincts_total': all_precincts,
            'source_updated': subset[0].get(
                'CurrentDateTime', ''
            ),
            'has_results': (
                'yes' if total else 'no'
            )
        }

        for party in PARTIES:
            entry[f'{party}_votes'] = counts[party]

            entry[f'{party}_pct'] = (
                round(
                    100 * counts[party] / total,
                    3
                )
                if total
                else 0
            )

        congress.append(entry)

    write_csv(
        feeds / 'congress.csv',
        congress_columns,
        congress
    )

    # Small index of configured races.
    index = feeds / 'index.json'

    content = json.dumps(
        manifest,
        indent=2
    ) + '\n'

    if (
        not index.exists()
        or index.read_text(
            encoding='utf-8'
        ) != content
    ):
        index.write_text(
            content,
            encoding='utf-8'
        )

    print(
        f'OK: {len(records)} source rows; '
        f'{len(manifest)} candidate feeds; '
        f'{len(config["ballot_measure_ids"])} '
        'ballot measures; congress map preserved'
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        '--input',
        help='Local CSV for testing'
    )

    parser.add_argument(
        '--output',
        default='public'
    )

    parser.add_argument(
        '--config',
        default='config/races.json'
    )

    parser.add_argument(
        '--calls',
        default='config/race-calls.csv'
    )

    args = parser.parse_args()

    if args.input:
        raw = Path(
            args.input
        ).read_bytes()

    else:
        request = urllib.request.Request(
            SOURCE,
            headers={
                'User-Agent':
                    'NebraskaElectionResults/1.0',
                'Accept':
                    'text/csv,*/*'
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=45
        ) as response:
            raw = response.read(10_000_001)

        if len(raw) > 10_000_000:
            raise ValueError(
                'Oversized source response'
            )

    columns, records = parse(raw)

    config = json.loads(
        Path(
            args.config
        ).read_text(
            encoding='utf-8'
        )
    )

    calls = read_calls(
        Path(
            args.calls
        )
    )

    build(
        columns,
        records,
        config,
        Path(args.output),
        calls
    )


if __name__ == '__main__':
    main()
