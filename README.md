# Nebraska Election Results — simple GitHub edition

**One source, one Python script, one GitHub workflow. No API token needed.**

## Source

`https://electionresults.nebraska.gov/resultsCSV.aspx?text=All&type=All&map=CTY`

The script is tested against the provided pre-election `Media (6).csv` fixture (625 candidate rows, 463 races). The live endpoint and Datawrapper live-refresh behavior have **not** been tested here. This is a pilot, not an election-night production guarantee.

## Install

1. Make a **new public GitHub repository** (recommended for a clean restart). Upload `update.py`, `config/races.json`, and `.gitignore`. Do **not** upload `test-output/`.
2. Add `.github/workflows/update.yml` through GitHub's **Add file → Create new file** and paste the contents (the dot-prefixed `.github` folder may be hidden on Mac).
3. Open **Actions → Update Nebraska election feeds → Run workflow**. Workflow grants `contents: write` via YAML. If your organization restricts writes, an administrator must allow them.
4. Confirm `public/feeds/congress.csv`, `public/feeds/ballot-measures.csv`, and the candidate CSVs appear in the repo.
5. Connect each Datawrapper chart to its public raw CSV URL:
   `https://raw.githubusercontent.com/OWNER/REPO/main/public/feeds/ballot-measures.csv`
   Replace `OWNER` and `REPO` with yours. Use the **Raw** URL, not GitHub's `blob` page.
6. Configure charts manually in Datawrapper and verify their external-data refresh settings. Do not publish zero-vote charts as real results.

## Outputs

- `public/feeds/senate.csv`
- `public/feeds/governor.csv`
- `public/feeds/house-1.csv`, `house-2.csv`, `house-3.csv`
- `public/feeds/ballot-measures.csv` (wide columns: Ballot measure, For %, Against %, For votes, Against votes, Total votes, Precincts reporting %, Last updated, Has results)
- `public/feeds/congress.csv` (legacy-compatible column names, including `district_keys` 1/2/3 and party percentage columns)
- `public/feeds/index.json` (simple catalog)

**Existing repository users:** This is a new feed layout. `public/feeds/congress.csv` keeps its old header names and map keys, but the *other* legacy feed URLs and schemas are not guaranteed compatible. To avoid disrupting published charts, use a new repo and move embeds only after verifying them. The converter does not delete older files if you run it in the old repo, so stale files can remain there.

## Edit the races

Edit only `config/races.json` to change the five candidate-race IDs or four ballot-measure IDs. Race IDs may change for future election cycles. The script fails rather than silently publishing an empty file if a configured race is absent.

## Datawrapper settings

- Candidate bars: category `Candidate`; value `Vote %`. `Votes` remains in the CSV for a results table; standard bars do not have customizable vote-count tooltips. For a vote-count display use a table or surrounding page text.
- Ballot measures: category `Ballot measure`; series `For %` and `Against %`; stacked bars, 0–100 axis. Both percentages remain empty until votes arrive.
- Congressional choropleth: match Datawrapper `Code (1,2,3)` with `district_keys`; select e.g. `rep_pct` for shading. It is a party-share map, not a leading-party map.
- `Precincts reporting %` and `Last updated` are feed columns. They do **not** automatically become a Datawrapper footer. Show them in a table, or on a separately built results page; avoid claiming a live footer without implementing it.

## Test locally

From the project directory:

`python update.py --input '/path/to/Media (6).csv' --output public`

The converter uses Python standard library only. A local sample is included under `sample-output/` for inspection. All source votes were zero in the supplied fixture; no fictional votes are injected.

## Operational safeguards and limits

- Runs every 5 minutes **on a best-effort basis**; GitHub Actions can delay or skip scheduled runs. Datawrapper's external-data refresh interval is separate and may vary with chart settings and publication age.
- Download/format errors stop the workflow before committing; previously committed feeds remain available. No automatic alerts are configured.
- Source reporting is computed as reported/total precincts, rounded to one decimal. If precinct counts are missing, reporting percentage is blank.
- The official source timestamp is preserved as supplied. Do not assume it has an explicit time-zone offset.
- Election-night data is unofficial. The tool makes no race calls, does not certify results and does not infer winners from zero votes.
- For a historical archive, enable `SAVE_SNAPSHOTS=1` in the workflow environment *only after planning storage/retention*. Default is off to keep the Git repo small.
- `map=CTY` is a contest-level export in the supplied sample. County-by-county map data requires separately verifying the geographic export.
- GitHub raw CSV files are publicly accessible. No secrets or private records belong in them.
