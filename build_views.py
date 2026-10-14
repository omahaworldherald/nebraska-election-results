#!/usr/bin/env python3
"""Add presentation-specific Datawrapper CSVs without modifying existing feeds."""
import argparse
import csv
from pathlib import Path

TEMPLATES = {'candidate_bars', 'results_table', 'ballot_measure', 'retention', 'leader_map'}

def read(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def write(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)

def config_rows(path):
    return read(path) if path.exists() else []

def choose(race, overrides, rules):
    rid = race['race_id']
    override = overrides.get(rid, {})
    if override.get('template'):
        return override['template']
    for rule in rules:
        typ, val = rule['match_type'], rule['match_value']
        if typ == 'area_type' and race['area_type'] == val:
            return rule['template']
        if typ == 'race_name_contains' and val.lower() in race['race_name'].lower():
            return rule['template']
        if typ == 'fallback':
            return rule['template']
    return 'results_table'

def build(public, config):
    feeds = public / 'feeds'
    races = read(feeds / 'race_index.csv')
    overrides = {r['race_id']:r for r in config_rows(config / 'race-config.csv')}
    rules = config_rows(config / 'race-rules.csv')
    index = []
    for race in races:
        rid = race['race_id']
        o = overrides.get(rid, {})
        if o.get('enabled', 'true').strip().lower() in ('false', 'no', '0'):
            continue
        template = choose(race, overrides, rules)
        if template not in TEMPLATES:
            raise ValueError(f'Unsupported template {template!r} for race {rid}')
        candidates = read(feeds / 'races' / f'{rid}.csv')
        total = sum(int(c['votes']) for c in candidates)
        candidates.sort(key=lambda c: (-int(c['votes']), c['candidate_name']))
        leader = candidates[0] if total and candidates else None
        tied = len(candidates)>1 and int(candidates[0]['votes']) == int(candidates[1]['votes'])
        if tied:
            leader = None
        base = {'race_id':rid, 'race_name':o.get('display_name') or race['race_name'],
                'template':template, 'total_votes':total, 'has_results': 'yes' if total else 'no'}
        rows=[]
        for i,c in enumerate(candidates,1):
            rows.append({**base, 'candidate_name':c['candidate_name'], 'party_code':c['party_code'],
                         'votes':c['votes'], 'pct':c['pct'] if total else '',
                         'rank':i if total else '', 'precincts_reporting':c['precincts_reporting'],
                         'precincts_total':c['precincts_total'], 'source_updated':c['source_updated']})
        out = f'views/{template}/{rid}.csv'
        write(feeds / out, ['race_id','race_name','template','candidate_name','party_code','votes','pct','rank','total_votes','has_results','precincts_reporting','precincts_total','source_updated'],rows)
        index.append({'race_id':rid,'race_name':base['race_name'],'area_type':race['area_type'],
                      'area_num':race['area_num'],'template':template,'feed_path':'feeds/'+out,
                      'total_votes':total,'has_results':base['has_results'],
                      'leader_name':leader['candidate_name'] if leader else '',
                      'leader_party':leader['party_code'] if leader else '',
                      'priority':o.get('priority',''), 'chart_id':o.get('chart_id','')})
    write(feeds / 'visualization_index.csv', ['race_id','race_name','area_type','area_num','template','feed_path','total_votes','has_results','leader_name','leader_party','priority','chart_id'], index)
    print(f'Built {len(index)} visualization feeds; existing congress.csv untouched')

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--public', default='public')
    p.add_argument('--config', default='config')
    a=p.parse_args()
    build(Path(a.public),Path(a.config))
