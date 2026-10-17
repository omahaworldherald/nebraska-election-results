# Nebraska Election Feeds — Passthrough

One Python script downloads Nebraska's All Contests CSV and splits it by race ID. It does **not** rename or recalculate source columns in the split feeds.

## Files to install

- `update.py` — replace the previous simple-edition script.
- `config/races.json` — same configuration format as before; no changes required if your existing race IDs are correct.
- `.github/workflows/update.yml` — same scheduled workflow; no changes required if it already runs successfully.

## Generated files

- `public/feeds/all-contests.csv`: complete official export, with original column headers.
- `public/feeds/senate.csv`, `governor.csv`, `house-1.csv`, `house-2.csv`, `house-3.csv`: filtered official rows, unchanged columns.
- `public/feeds/ballot-measures.csv`: official rows for all four configured measures, unchanged columns (eight candidate/choice rows).
- `public/feeds/congress.csv`: **the one exception**, a three-row wide-format file for the existing Datawrapper congressional choropleth, including `district_keys`.
- `public/feeds/index.json`: a small directory of configured candidate feeds.

## Installation

If you already use the simple-edition GitHub repo, replace only `update.py`. The existing `config/races.json` and workflow still work. Commit the change, then run **Actions → Update Nebraska election feeds → Run workflow**.

For a fresh repo, upload `update.py` and `config/races.json`, then create `.github/workflows/update.yml` directly on GitHub.

## Testing locally

```bash
python update.py --input "Media (6).csv" --output public
```

## Datawrapper note

These are raw, long-format results. Candidate charts can use `CandidateName`, `CandidateVotes`, and `CandidatePercentage`. Ballot measures contain **two rows per measure**, not a wide-format stacked-bar dataset. To show all four ballot measures in one 100% stacked chart, you would need an additional transformed feed or a different Datawrapper chart design. The congressional map continues to use `congress.csv`.

All source records are unofficial until certified by the state. Do not publish the zero-vote pre-election export as reported results.
