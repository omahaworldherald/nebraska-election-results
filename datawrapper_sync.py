
#!/usr/bin/env python3
"""Sync Nebraska election display feeds to Datawrapper charts.

Updates candidate results, reporting notes, race-call descriptions,
and official source attribution.

Only republishes when data or metadata changes, unless --force is used.
Publication state is saved only after a successful API publication.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


BASE = "https://api.datawrapper.de/v3"

CANDIDATE_REQUIRED = {
    "Candidate",
    "Votes",
    "Pct.",
    "Precincts Reporting",
    "Called",
    "Last Updated",
}

MEASURE_REQUIRED = {
    "Measure", "For Pct.", "Against Pct.", "For Votes", "Against Votes",
    "Precincts Reporting", "Last Updated",
}

SOURCE_NAME = "Nebraska Secretary of State"

SOURCE_URL = (
    "https://electionresults.nebraska.gov/"
    "resultsCSV.aspx?text=All&type=All&map=CTY"
)

PARTY_COLORS = {
    "REP": "#C71E1D",
    "DEM": "#1D81A2",
    "LIB": "#FA8C00",
    "LMN": "#009076",
    "NWP": "#465B70",
    "AFP": "#CBB990",
    "IND": "#8B69B4",
    "OTH": "#C4C4C4",
}

def make_candidate_colors(rows):
    colors = {}

    for row in rows:
        candidate = row["Candidate"].strip()

        # Extract party code, even with a race-call checkmark.
        match = re.search(r"\(([A-Z]+)\)$", candidate)

        if match:
            party = match.group(1)
            colors[candidate] = PARTY_COLORS.get(
                party, "#89939E"
            )

    return colors

def api(method, path, token, data=None, content_type=None):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    if content_type:
        headers["Content-Type"] = content_type

    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=40) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(
            "utf-8", "replace"
        )[:600]

        raise RuntimeError(
            f"{method} {path}: HTTP {exc.code}: {body}"
        ) from exc


def load_feed(path, feed_type="candidate"):
    raw = path.read_bytes()

    reader = csv.DictReader(
        io.StringIO(raw.decode("utf-8-sig"))
    )

    rows = list(reader)
    required = MEASURE_REQUIRED if feed_type == "measures" else CANDIDATE_REQUIRED
    if feed_type == "legislature":
        required = CANDIDATE_REQUIRED | {"District"}
    missing = required - set(reader.fieldnames or [])

    if missing or not rows:
        raise ValueError(
            f"{path}: missing {sorted(missing)} "
            "or no candidate rows"
        )

    if len({
        r["Last Updated"].strip()
        for r in rows
    }) != 1:
        raise ValueError(
            f"{path}: inconsistent source timestamps"
        )

    if feed_type != "legislature" and len({
        r["Precincts Reporting"].strip()
        for r in rows
    }) != 1:
        raise ValueError(
            f"{path}: inconsistent reporting percentages"
        )

    if feed_type == "candidate" and sum(
        r["Called"].strip().lower() == "yes"
        for r in rows
    ) > 1:
        raise ValueError(
            f"{path}: multiple called candidates"
        )

    for row in rows:
        vote_fields = ("For Votes", "Against Votes") if feed_type == "measures" else ("Votes",)
        for field in vote_fields:
            votes = int(row[field].replace(",", ""))
            if votes < 0:
                raise ValueError(f"{path}: negative {field}")

    return raw, rows


def make_note(rows, include_reporting=True):
    """Generate the source timestamp, optionally with precinct reporting."""

    reporting = rows[0]["Precincts Reporting"].strip()
    updated = rows[0]["Last Updated"].strip()

    try:
        reporting_pct = f"{float(reporting):.1f}%"
    except (ValueError, TypeError):
        reporting_pct = "0.0%"

    formatted_time = ""

    if updated:
        try:
            dt = datetime.strptime(
                updated,
                "%m/%d/%Y %I:%M:%S %p"
            )

            hour = dt.hour % 12 or 12
            minute = dt.strftime("%M")
            period = (
                "a.m." if dt.hour < 12 else "p.m."
            )

            month = dt.strftime("%b") + "."

            formatted_time = (
                f"{hour}:{minute} {period}, "
                f"{month} {dt.day}, {dt.year}"
            )

        except ValueError:
            formatted_time = updated

    parts = [f"{reporting_pct} precincts reporting"] if include_reporting else []

    if formatted_time:
        parts.append(
            f"Updated {formatted_time}"
        )

    return " · ".join(parts)


def make_description(rows):
    """Show the editorial race call, or leave description blank."""

    for row in rows:
        if row["Called"].strip().lower() == "yes":
            candidate = row["Candidate"].strip()

            # Remove leading checkmark.
            candidate = candidate.removeprefix("✓").strip()

            # Remove trailing party abbreviation.
            candidate = re.sub(
                r"\s+\([A-Z]+\)$",
                "",
                candidate
            )

            return f"Race called for {candidate}."

    return ""


def chart_config(path):
    with path.open(
        newline="",
        encoding="utf-8-sig"
    ) as stream:

        reader = csv.DictReader(stream)

        required = {
            "chart_id",
            "feed",
            "enabled",
        }

        if not required.issubset(
            reader.fieldnames or []
        ):
            raise ValueError(
                "Chart config must contain "
                "chart_id,feed,enabled"
            )

        seen = set()
        result = []

        for row in reader:
            enabled = (
                row.get("enabled") or ""
            ).strip().lower()

            if enabled not in ("yes", "no"):
                raise ValueError(
                    f"Invalid enabled value: {enabled}"
                )

            if enabled == "no":
                continue

            chart_id = (
                row.get("chart_id") or ""
            ).strip()

            feed = (
                row.get("feed") or ""
            ).strip()

            if (
                not chart_id
                or not feed
                or chart_id in seen
            ):
                raise ValueError(
                    f"Invalid or duplicate chart config: {row}"
                )

            seen.add(chart_id)

            path_value = Path(feed)

            if (
                path_value.is_absolute()
                or ".." in path_value.parts
                or path_value.suffix.lower() != ".csv"
            ):
                raise ValueError(
                    f"Unsafe feed name: {feed}"
                )

            result.append((
                chart_id,
                Path("public/feeds/display") / path_value
            ))

    return result


def save_state(path, state):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp = path.with_suffix(".tmp")

    temp.write_text(
        json.dumps(
            state,
            indent=2,
            sort_keys=True
        ) + "\n",
        encoding="utf-8"
    )

    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default="config/datawrapper-charts.csv"
    )

    parser.add_argument(
        "--state",
        default="config/datawrapper-published.json"
    )

    parser.add_argument(
        "--apply",
        action="store_true"
    )

    parser.add_argument(
        "--force",
        action="store_true"
    )

    args = parser.parse_args()

    configs = chart_config(
        Path(args.config)
    )

    state_path = Path(args.state)

    state = (
        json.loads(
            state_path.read_text(
                encoding="utf-8"
            )
        )
        if state_path.exists()
        else {}
    )

    token = (
        os.getenv("DATAWRAPPER_API_TOKEN")
        if args.apply
        else None
    )

    if args.apply and not token:
        parser.error(
            "DATAWRAPPER_API_TOKEN is missing"
        )

    failures = []

    for chart_id, feed in configs:
        try:
            if feed.name == "ballot-measures-all.csv":
                feed_type = "measures"
            elif feed.name == "legislature-all.csv":
                feed_type = "legislature"
            else:
                feed_type = "candidate"
            raw, rows = load_feed(feed, feed_type)

            notes = make_note(rows, include_reporting=(feed_type != "legislature"))
            description = make_description(rows) if feed_type == "candidate" else ""
            candidate_colors = make_candidate_colors(rows) if feed_type == "candidate" else {}

            # Include all managed fields in change detection.
            fingerprint_data = (
                raw
                + b"\nNOTES\n"
                + notes.encode("utf-8")
                + b"\nDESCRIPTION\n"
                + description.encode("utf-8")
                + b"\nSOURCE\n"
                + SOURCE_NAME.encode("utf-8")
                + b"\nSOURCE_URL\n"
                + SOURCE_URL.encode("utf-8")
                + b"\nCOLORS\n"
                + json.dumps(candidate_colors, sort_keys=True).encode("utf-8")
            )

            fingerprint = hashlib.sha256(
                fingerprint_data
            ).hexdigest()

            if (
                not args.force
                and state.get(chart_id) == fingerprint
            ):
                print(
                    f"{chart_id}: unchanged, skipped"
                )
                continue

            print(
                f"{chart_id}: {feed} "
                f"({len(rows)} rows)"
            )

            print(
                f"Proposed note: {notes}"
            )

            print(
                f"Proposed description: {description or '(blank)'}"
            )

            print(
                f"Data source: {SOURCE_NAME}"
            )

            if not args.apply:
                print(
                    f"{chart_id}: DRY RUN; "
                    "no API requests"
                )
                continue

            # Read the existing Datawrapper chart.
            chart = api(
                "GET",
                f"/charts/{chart_id}",
                token
            )

            if chart.get("id") != chart_id:
                raise ValueError(
                    f"Unexpected chart ID for {chart_id}"
                )

            metadata = chart.get(
                "metadata"
            ) or {}

            # Update chart notes while preserving other settings.
            annotate = dict(
                metadata.get("annotate") or {}
            )

            annotate["notes"] = notes

            # Update chart description and source attribution.
            describe = dict(metadata.get("describe") or {})
            describe["intro"] = description
            describe["source-name"] = SOURCE_NAME
            describe["source-url"] = SOURCE_URL

            # Assign bar colors by party without changing other visual settings.
            visualize = dict(metadata.get("visualize") or {})

            if feed_type == "candidate" and chart.get("type") == "d3-bars":
                # Update both Datawrapper color settings.
                visualize["custom-colors"] = candidate_colors

                color_category = dict(
                    visualize.get("color-category") or {}
                )
                color_category["map"] = candidate_colors
                visualize["color-category"] = color_category

            # Automatically color in-cell bars in Datawrapper tables.
            if feed_type == "candidate" and chart.get("type") == "tables":
                columns = dict(visualize.get("columns") or {})

                pct_column = dict(columns.get("Pct.") or {})

                # Preserve the existing table formatting.
                pct_column["showAsBar"] = True
                pct_column["customBarColorBy"] = "Candidate"
                pct_column["customColorBy"] = "Candidate"
                pct_column["customColorBarBackground"] = candidate_colors

                columns["Pct."] = pct_column
                visualize["columns"] = columns

                # Update the category color map for table bars.
                color_category = dict(
                    visualize.get("color-category") or {}
                )
                color_category["map"] = candidate_colors
                visualize["color-category"] = color_category

            # Upload the latest candidate results.
            api(
                "PUT",
                f"/charts/{chart_id}/data",
                token,
                raw,
                "text/csv"
            )

            # Update only the metadata sections managed by this script.
            payload = {
                "metadata": {
                    "annotate": annotate,
                    "describe": describe,
                }
            }
            if feed_type == "candidate" and chart.get("type") in ("d3-bars", "tables"):
                payload["metadata"]["visualize"] = visualize

            api(
                "PATCH",
                f"/charts/{chart_id}",
                token,
                json.dumps(payload).encode("utf-8"),
                "application/json"
            )

            # Publish the updated chart.
            api(
                "POST",
                f"/charts/{chart_id}/publish",
                token,
                b"{}",
                "application/json"
            )

            # Save fingerprint only after successful publication.
            state[chart_id] = fingerprint

            save_state(
                state_path,
                state
            )

            print(
                f"{chart_id}: published successfully"
            )

        except (
            OSError,
            ValueError,
            RuntimeError,
            KeyError
        ) as exc:

            print(
                f"{chart_id}: FAILED: {exc}",
                flush=True
            )

            failures.append(chart_id)

    if failures:
        raise SystemExit(
            f'Failed charts: {", ".join(failures)}'
        )


if __name__ == "__main__":
    main()
