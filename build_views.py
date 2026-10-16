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
    # Combined statewide ballot measures: one row per contest, two percentage series.
    # Use source candidate labels rather than assuming all questions use Yes/No.
    combined = []
    for race in races:
        rid = race['race_id']
        if race['area_type'] != 'SW':
            continue
        override = overrides.get(rid, {})
        if override.get('enabled', 'true').strip().lower() in ('false', 'no', '0'):
            continue
        if choose(race, overrides, rules) != 'ballot_measure':
            continue
        candidates = read(feeds / 'races' / f'{rid}.csv')
        labels = {' '.join(c['candidate_name'].lower().split()): c for c in candidates}
        positive = labels.get('for') or labels.get('yes')
        negative = labels.get('against') or labels.get('no')
        if not positive or not negative or len(candidates) != 2:
            print(f'Skipping measure {rid}: choices require editorial review')
            continue
        yes_votes = int(positive['votes'])
        no_votes = int(negative['votes'])
        total = yes_votes + no_votes
        combined.append({
            'race_id': rid,
            'measure': override.get('display_name') or race['race_name'],
            'for_pct': round(100 * yes_votes / total, 2) if total else '',
            'against_pct': round(100 * no_votes / total, 2) if total else '',
            'for_votes': yes_votes,
            'against_votes': no_votes,
            'total_votes': total,
            'precincts_reporting': positive['precincts_reporting'],
            'precincts_total': positive['precincts_total'],
            'source_updated': positive['source_updated'],
            'has_results': 'yes' if total else 'no',
        })
    write(feeds / 'views' / 'ballot_measure' / 'all-measures.csv',
          ['race_id','measure','for_pct','against_pct','for_votes','against_votes',
           'total_votes','precincts_reporting','precincts_total','source_updated','has_results'],
          combined)
    print(f'Built combined ballot-measure feed with {len(combined)} contests')
    write(feeds / 'visualization_index.csv', ['race_id','race_name','area_type','area_num','template','feed_path','total_votes','has_results','leader_name','leader_party','priority','chart_id'], index)
    print(f'Built {len(index)} visualization feeds; existing congress.csv untouched')

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--public', default='public')
    p.add_argument('--config', default='config')
    a=p.parse_args()
    build(Path(a.public),Path(a.config))
