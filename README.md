# Nebraska Election Feeds v2 (additive)

This version keeps `public/feeds/congress.csv` **unchanged**, including the `district_keys` field and all party vote/percentage columns. It adds a visualization index and candidate-level CSVs for every race.

## Install in existing GitHub repository

Upload/replace `update.py`, add `build_views.py`, add both `config/*.csv` files, and update `.github/workflows/update.yml`. Do not delete `public/feeds/congress.csv`. In the GitHub web UI, create hidden workflow file with **Add file > Create new file** and enter `.github/workflows/update.yml` as the filename.

The workflow first runs `python update.py --output public`, then `python build_views.py --public public --config config`, and commits changes to `public`.

## Test locally

`python update.py --input 'Media (6).csv' --output public`

`python build_views.py --public public --config config`

Inspect `public/feeds/congress.csv`, `public/feeds/visualization_index.csv`, and `public/feeds/views/candidate_bars/13166.csv`.

## Datawrapper

Keep the existing map connected to `public/feeds/congress.csv` and match `district_keys` against the map's Code key. For a candidate bar chart, connect its source to `public/feeds/views/candidate_bars/<RaceID>.csv`, use `candidate_name` as the label and `pct` as the value; display `votes` in the tooltip or table. The CSV is a data contract, not a guarantee that Datawrapper can automatically generate or reconfigure charts. Configure each chart template once, then duplicate or use the API.

The `visualization_index.csv` lists all races, output URLs (as paths), visualization type and optional editorial chart IDs. An election hub can use this file as its race directory, while stories embed individual published Datawrapper chart URLs.

## Editorial overrides

Edit `config/race-config.csv` to change a race's `template`, `display_name`, `priority`, `enabled` or `chart_id`. The default classification rules live in `config/race-rules.csv`. Unknown contests default to `results_table` and should be reviewed before publishing. Never automatically call a race: `leader_name` means the current vote leader only, and stays empty on zero votes or ties.

## Safeguards and limitations

This is a development prototype. Live fetch has not been verified here. It does not yet implement source-age alerts, human race calls, data-quality quarantine, full county-level geographic maps, official certification status or historical election-cycle separation. It preserves the original `PET` code in candidate feeds; do not assume all petition candidates are independent. All results are unofficial until certified. GitHub Actions may delay scheduled runs, and Datawrapper's own refresh cadence may differ.
