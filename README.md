# Sarpy Clarity add-on for Nebraska election results

This is an **add-on** to the existing `nebraska-election-results` repository. Do not replace `update.py`, `datawrapper_sync.py`, `config/races.json`, or `.github/workflows/update.yml`.

## Add these files to the existing main branch

- `sarpy_update.py` (repository root)
- `config/sarpy-races.json`
- `.github/workflows/update-sarpy.yml` (create by typing the complete path in GitHub's new-file editor)

## First run

1. Commit the three files.
2. Go to Actions > **Update Sarpy Clarity feeds** > Run workflow.
3. Inspect `public/feeds/sarpy/summary.csv` (original Clarity columns) and `public/feeds/display/sarpy-papillion-mayor.csv` (six Datawrapper columns).
4. The default configuration points to the **2026 primary** archive. Do not publish these primary results as general-election returns.

The collector was tested offline against the supplied `summary.zip` (72 rows, 30 contest names). It successfully generated the three selected sample contests. The remote URL has **not** been validated from GitHub Actions; the primary URL may be replaced or its report-version segment may change. A future general-election URL must be verified before enabling scheduling.

## Switch to the general election

Edit `config/sarpy-races.json`: replace `source_url` with the verified general-election `summary.zip` URL and update `contest_name` values to **exactly** match the new ZIP's `contest name` values. Keep stable slugs for charts you want to reuse. The script fails rather than silently producing empty files if a configured contest disappears.

The workflow's 5-minute schedule is commented out until the new URL is confirmed. Uncomment the `schedule:` block after testing.

## Important Datawrapper integration limitation

The existing `datawrapper_sync.py` hardcodes `SOURCE_NAME` and `SOURCE_URL` to **Nebraska Secretary of State** for every chart. **Do not add Sarpy feeds to `config/datawrapper-charts.csv` yet**, or the chart's attribution would be wrong. First adapt the publisher to accept per-chart source name and source URL, and to omit the timestamp from the notes when `Last Updated` is blank. The current sync script already permits a blank `Last Updated` value, but it still uses the statewide source attribution.

The Sarpy display CSVs deliberately have a blank `Last Updated`: `summary.csv` does not contain an official source timestamp. Do not replace it with the GitHub execution time and describe it as a Clarity update. A separate, verified Clarity publication timestamp can be added later.

To add a Sarpy chart after the publisher is source-aware, point its `feed` to `sarpy-papillion-mayor.csv` and set its source attribution to Sarpy County Election Commission / Clarity Elections as appropriate. The output schema is `Candidate,Votes,Pct.,Precincts Reporting,Called,Last Updated`.

## Calls and nonpartisan races

The `calls` object in `sarpy-races.json` is initially empty. For future testing, it can map a slug to the **exact choice name** in the Clarity CSV. A checkmark is added only for a valid named candidate and a contest with votes. Do not mark races called automatically. Clarity's `NON` party label is preserved for nonpartisan contests; automatic party coloring in the existing publisher should not treat it as a partisan affiliation.

## Douglas County later

Add a separate `douglas_update.py` (or a common adapter once its file format is known) and `config/douglas-races.json`. Use distinct `douglas-` slugs. Don't assume Douglas will use Clarity's CSV layout until a sample is available.

## Notes on workflow concurrency

The Sarpy workflow shares the `nebraska-results` concurrency group with the existing statewide workflow to reduce concurrent repository writes. The Sarpy workflow commits only its own feeds. The statewide workflow may still need `git pull --rebase` handling if other commits land during a run. Test concurrent scheduling before election night.
