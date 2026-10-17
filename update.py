#!/usr/bin/env python3
"""Fetch Nebraska all-contests results and publish stable, race-specific CSVs."""
import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import urllib.request
from datetime import datetime, timezone

SOURCE = 'https://electionresults.nebraska.gov/resultsCSV.aspx?text=All&type=All&map=CTY'
FIELDS = ['RaceID','RaceName','PartyCode','AreaType','AreaNum','CandidateID','CandidateName','CurrentDateTime','CandidateVotes','CandidatePercentage','PrecinctsReporting']
PARTIES = ['REP','DEM','LIB','LMN','NWP','AFP','IND','OTH']


def load_csv(raw):
    text = raw.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not set(FIELDS).issubset(reader.fieldnames):
        raise ValueError('Missing expected Nebraska columns; refusing to publish')
    rows = []
    for r in reader:
        if not r.get('RaceID') or not r.get('CandidateID'):
            continue
        r = {k:(v or '').strip() for k,v in r.items() if k is not None}
        r['CandidateVotes'] = int(r['CandidateVotes'].replace(',',''))
        if r['CandidateVotes'] < 0:
            raise ValueError('Negative vote count')
        rows.append(r)
    if not rows:
        raise ValueError('Empty results; refusing to overwrite published data')
    return rows


def csv_write(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    content = stream.getvalue()
    if not path.exists() or path.read_text(encoding='utf-8') != content:
        path.write_text(content, encoding='utf-8')


def precincts(value):
    match = re.search(r'(\d+)\s*/\s*(\d+)', value or '')
    return (int(match.group(1)), int(match.group(2))) if match else (None,None)



def reporting_percentage(reported, total):
    """Return a one-decimal percentage or blank for unavailable denominators."""
    try:
        reported, total = int(reported), int(total)
        if total <= 0 or reported < 0 or reported > total:
            return ''
        return round(100 * reported / total, 1)
    except (ValueError, TypeError):
        return ''

def normalize_party(code):
    # PET = petition; classification not assumed independent.
    return code if code in PARTIES else 'OTH'


def produce(rows, root):
    feeds = root/'feeds'
    by_race = {}
    for r in rows:
        by_race.setdefault(r['RaceID'], []).append(r)
    catalog = []
    candidate_fields = ['race_id','race_name','area_type','area_num','candidate_id','candidate_name','party_code','party_group','votes','pct','total_votes','precincts_reporting','precincts_total','reporting_pct','source_updated']
    for rid, group in sorted(by_race.items(), key=lambda item: int(item[0])):
        total = sum(r['CandidateVotes'] for r in group)
        out = []
        for r in group:
            reported, precinct_total = precincts(r['PrecinctsReporting'])
            out.append({'race_id':rid,'race_name':r['RaceName'],'area_type':r['AreaType'],'area_num':r['AreaNum'],
                'candidate_id':r['CandidateID'],'candidate_name':' '.join(r['CandidateName'].split()),
                'party_code':r['PartyCode'],'party_group':normalize_party(r['PartyCode']),
                'votes':r['CandidateVotes'],'pct':round(100*r['CandidateVotes']/total,3) if total else 0,
                'total_votes':total,'precincts_reporting':reported,'precincts_total':precinct_total,'reporting_pct':reporting_percentage(reported, precinct_total),
                'source_updated':r['CurrentDateTime']})
        csv_write(feeds/'races'/f'{rid}.csv',out,candidate_fields)
        catalog.append({'race_id':rid,'race_name':group[0]['RaceName'],'area_type':group[0]['AreaType'],
                        'area_num':group[0]['AreaNum'],'candidate_count':len(group),'total_votes':total})
    csv_write(feeds/'race_index.csv',catalog,['race_id','race_name','area_type','area_num','candidate_count','total_votes'])
    # Congressional geography: one district per row, wide party columns for Datawrapper.
    cg = [g for g in by_race.values() if g[0]['AreaType']=='CG']
    wide = []
    for group in sorted(cg,key=lambda g:g[0]['AreaNum']):
        total = sum(r['CandidateVotes'] for r in group)
        party_votes = {p:0 for p in PARTIES}
        for r in group:
            party_votes[normalize_party(r['PartyCode'])] += r['CandidateVotes']
        reporting, precinct_total = precincts(group[0]['PrecinctsReporting'])
        number = re.search(r'\d+',group[0]['AreaNum'])
        if not number:
            raise ValueError('Unexpected congressional area identifier')
        record = {'district_keys':str(int(number.group())),'district':f'NE-{int(number.group()):02d}','race_id':group[0]['RaceID'],
                  'total_votes':total,'precincts_reporting':reporting,'precincts_total':precinct_total,'reporting_pct':reporting_percentage(reporting, precinct_total),
                  'source_updated':group[0]['CurrentDateTime']}
        for p in PARTIES:
            record[p.lower()+'_votes'] = party_votes[p]
            record[p.lower()+'_pct'] = round(100*party_votes[p]/total,3) if total else 0
        record['has_results'] = 'yes' if total else 'no'
        wide.append(record)
    wide_fields = ['district_keys','district','race_id','total_votes','precincts_reporting','precincts_total','reporting_pct','source_updated','has_results'] + [f'{p.lower()}_{suffix}' for p in PARTIES for suffix in ('votes','pct')]
    csv_write(feeds/'congress.csv',wide,wide_fields)
    # Convenience feeds for named statewide contests, based on area type and race name.
    for label,term in [('senate','united states senator'),('governor','governor')]:
        selected = [c for c in catalog if c['area_type']=='SW' and term in c['race_name'].lower()]
        merged=[]
        for c in selected:
            with (feeds/'races'/f"{c['race_id']}.csv").open(newline='',encoding='utf-8') as f:
                merged.extend(csv.DictReader(f))
        csv_write(feeds/f'{label}.csv',merged,candidate_fields)
    return len(by_race),len(wide)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',help='Use a downloaded file instead of fetching')
    ap.add_argument('--output',default='public')
    args=ap.parse_args()
    if args.input:
        raw=Path(args.input).read_bytes()
    else:
        req=urllib.request.Request(SOURCE,headers={'User-Agent':'NebraskaElectionData/0.1 (newsroom data feed)','Accept':'text/csv,*/*'})
        with urllib.request.urlopen(req,timeout=45) as response:
            raw=response.read(10_000_001)
        if len(raw)>10_000_000:
            raise ValueError('Unexpected oversized response')
    rows=load_csv(raw)
    root=Path(args.output)
    root.mkdir(parents=True,exist_ok=True)
    n,congress=produce(rows,root)
    digest=hashlib.sha256(raw).hexdigest()
    snapshot=root/'snapshots'/f'{digest[:16]}.csv'
    if not snapshot.exists():
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        snapshot.write_bytes(raw)
    status={'source_url':SOURCE,'source_sha256':digest,'processed_at_utc':datetime.now(timezone.utc).isoformat(),
            'candidate_rows':len(rows),'races':n,'congressional_districts':congress,
            'source_updated':rows[0]['CurrentDateTime']}
    # Avoid committing changed timestamps when the source has not changed.
    status_path=root/'status.json'
    if status_path.exists():
        previous=json.loads(status_path.read_text())
        if previous.get('source_sha256')==digest:
            status['processed_at_utc']=previous['processed_at_utc']
    status_path.write_text(json.dumps(status,indent=2)+'\n')
    print(f"Processed {len(rows)} rows, {n} races, {congress} congressional districts; source {digest[:12]}")

if __name__=='__main__':
    main()
