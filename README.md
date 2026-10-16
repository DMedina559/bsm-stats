# BSM distribution statistics

Public downloads and container pulls for Bedrock Server Manager. The daily collector publishes exact counters, source health, daily history, Shields.io endpoints, and a static dashboard.

**These numbers measure distribution events, not unique users, active installations, or running servers.** Package downloads and container pulls have different counting rules. Repeat downloads, CI, bots, caches, and provider corrections can affect them. The combined count is a convenience measure for one project; unrelated BSM projects are never summed together.

## Published data

| Path | Contents |
| --- | --- |
| `downloads.json` | Existing combined Shields.io badge for the primary project; its URL and label remain compatible |
| `stats.json` | Schema version, collection time, per-project exact counts, source health, growth, and milestones |
| `badges/<project>.json` | Combined badge for an individual project |
| `badges/<project>-<source>.json` | Per-source badge |
| `history/YYYY-MM.json` | Daily snapshots grouped by UTC month |
| `history.csv` | All retained per-source daily observations, including health and last success time |

The legacy badge is available at:

```text
https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FDMedina559%2Fbsm-stats%2Fmain%2Fdownloads.json
```

Use another published JSON path in the Shields endpoint URL for a project or source badge. Shields and upstream hosting can cache badge responses; the dashboard shows collection timestamps directly.

## Collection and failure handling

The scheduled workflow runs daily at **06:17 UTC** and can also be started manually on `main`. GitHub schedules can be delayed. A collection attempt:

1. Fetches each configured source with connect/read timeouts and at most three retries for transient failures, including HTTP 429 and selected 5xx responses. Retry delays are bounded and provider `Retry-After` values cannot suspend the job indefinitely.
2. Checks HTTP success, parses the response, and requires a nonnegative integer counter. Missing fields, booleans, malformed JSON, login pages, and unrecognized GHCR markup are failures, not zero downloads.
3. Preserves that source's last successful value and timestamp on failure. A never-collected source has a null count. A changed package or counting window cannot inherit another source's value.
4. Publishes health, exact counts, daily history, exports, and badges using atomic file replacement. The workflow commits changed artifacts before reporting degraded collection as a failed run.

Source health is `fresh`, `stale` (a previous successful value is retained), or `unavailable` (no successful value). The overall status is `fresh` or `degraded`. A project's total is null until all configured counts are known; a total that includes retained counts is marked stale. Zero is accepted when the provider actually returns zero.

Fresh badges are orange; stale or unavailable badges are grey. On the first incomplete collection, an existing legacy `downloads.json` is preserved unchanged because there is no exact baseline from which to rebuild it. Check `stats.json` or the dashboard for source health during this transition. Badge endpoints are static and cannot change color if the scheduler stops; the dashboard independently marks sources stale after 36 hours.

Provider counter decreases are accepted, marked `decreased`, and shown in the workflow summary and dashboard. Do not silently clamp counters upward: providers may legitimately correct their data. Decreases within the same UTC day remain flagged through subsequent attempts that day.

### Sources

| Kind | Provider | Meaning / limitation |
| --- | --- | --- |
| `pypi` | `https://pepy.tech/api/v2/projects/<package>` | PePy's reported total PyPI downloads; provider availability, access policies, and historical coverage can change |
| `docker` | `https://hub.docker.com/v2/repositories/<owner>/<image>/` | Docker Hub's reported repository pull count |
| `ghcr` | GitHub's public container package page | Reported total downloads; HTML parsing is isolated and rejects missing or abbreviated counts |
| `npm` | `https://api.npmjs.org/downloads/point/<start>:<end>/<package>` | Downloads from an explicit configured date through yesterday UTC, summed over disjoint ranges of at most 365 days; not an inferred lifetime count |

All configured sources are public and unauthenticated. No token is sent to a statistics provider. If a provider changes its API or requires authentication, collection becomes degraded until the collector is deliberately updated.

### History, growth, and milestones

Each UTC day stores its latest collection attempt, including preserved source counts and their original timestamps. Repeated runs update that day's snapshot rather than appending duplicate days. Older months are retained indefinitely.

Growth compares 1, 7, and 30 days, with every intervening daily observation required to be fresh and comparable. Missing dates, stale/unavailable counts, counter decreases, package changes, and source additions/removals suppress growth for affected windows. This deliberately favors a gap over presenting several days of accumulated downloads as one day's activity. A 30-day window is not a calendar month.

Milestones report the latest known count's highest reached threshold and the next threshold. These are informational; stale data does not imply a newly confirmed milestone event.

Exact history starts with the new collector. Historical rounded badges are retained in Git, but are **not** converted into fabricated exact counts or source breakdowns.

## Run locally

Requires Python 3.11 or newer. CI checks Python **3.11 and 3.14**.

```sh
python -m venv .venv
# Activate .venv using the command for your shell.
python -m pip install -r requirements.txt
python update_stats.py
python -m unittest discover -s tests -v
```

Use `python update_stats.py --strict` to exit unsuccessfully after saving a degraded observation. Without `--strict`, handled source failures are saved and summarized; unexpected failures still exit unsuccessfully. `--root /path/to/data` selects a directory containing `projects.json` and its output artifacts.

The collection workflow uses the default behavior so it can commit retained values, then explicitly fails if collection was degraded. Commit and push failures are not suppressed. Scheduled/manual publication is serialized; tests on superseded commits are canceled.

## Configure additional BSM projects

Edit `projects.json`. Each project has its own sources and total. `primary_project` selects the legacy badge's project. Project/source IDs must be safe lowercase file names; their identity includes the package, provider, and counting window.

The default configuration tracks the main server manager plus `bsm-api-client`, `bsm-cli`, and `bsm-test-utils` as independent projects. Their PePy counters were verified during implementation. Additional projects follow the same pattern:

```json
"bsm-api-client": {
  "name": "BSM API Client",
  "url": "https://github.com/DMedina559/bsm-api-client",
  "sources": {
    "pypi": {"kind": "pypi", "package": "bsm-api-client"}
  }
}
```

For a published frontend or API-client npm package, use its actual registry name and an explicit baseline:

```json
"npm": {
  "kind": "npm",
  "package": "@your-scope/your-package",
  "start_date": "2026-10-01"
}
```

Do not add an unpublished package or compare a configured npm window with a lifetime total without accounting for that difference. Retired projects and source badges remain in historical files; the current config determines what the dashboard displays. Removing a published badge file is a separate deliberate compatibility decision.

## Dashboard

The dashboard is plain HTML, CSS, and JavaScript with no third-party scripts, analytics, API keys, or build dependencies. It vendors the frontend's actual BSM Default semantic tokens, density styles, and brand assets, with matching cards, tables, controls, and compact breadcrumb header. System/dark/light mode and Comfort/Compact density preferences are saved locally when browser storage is available. Vendored asset attribution and its source revision are included in `web/THIRD_PARTY_NOTICES.md`. It includes project selection, 30/90-day and custom ranges, cumulative source/combined charts, source health, milestone/growth cards, an accessible exact-count table, and JSON/CSV downloads. Chart lines break across gaps, failures, corrections, and changed sources. History JSON export follows the selected project and date range; CSV exports the complete dataset.

After collecting statistics:

```sh
python scripts/build_site.py
python -m http.server 8000 --directory dist/site
```

Open `http://localhost:8000`. Serve over HTTP rather than opening `index.html` directly, because the page fetches its JSON data using relative URLs. The build script only permits output within the repository's `dist/` directory and packages the dashboard together with published data.

The **Dashboard** workflow builds a downloadable Pages artifact on relevant `main` updates, after the collection workflow (including degraded collections), or manually. It checks out trusted `main` contents, not code from a triggering branch.

Public deployment is optional and controlled by the `ENABLE_PAGES` repository variable. The workflow builds a downloadable artifact even when deployment is disabled.

## Tests

Python tests use isolated temporary directories and simulated providers; they never update committed statistics or require live provider access. Fixtures cover supported GHCR page structures. Tests exercise outages, malformed responses, counter corrections, recovery, daily/monthly history, identity changes, multiple projects, legacy badge compatibility, and publication.

For the dashboard logic, use Node.js 22 or newer:

```sh
node --check web/app.js
node --test tests/dashboard.test.cjs
```

The JavaScript tests verify date filtering, freshness aging, and chart gaps/corrections. Live provider checks should be reviewed separately because provider outages are operational failures, not deterministic test failures.
