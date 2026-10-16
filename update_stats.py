"""Collect public distribution counters and publish static statistics artifacts."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCHEMA_VERSION = 1
SOURCE_LABELS = {
    "pypi": "PyPI downloads",
    "docker": "Docker Hub pulls",
    "ghcr": "GHCR downloads",
    "npm": "npm downloads",
}


def format_num(number: int) -> str:
    """Format an exact counter for a compact badge."""
    if number >= 999_950:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1000:
        return f"{number / 1000:.1f}k"
    return str(number)


def validate_count(value: object) -> int:
    """Reject absent, negative, boolean, and noninteger counters."""
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer counter")
    return value


def timestamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: object = None) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    """Replace a published file atomically after its contents are complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, content: object) -> None:
    write_text(path, json.dumps(content, indent=2, sort_keys=True) + "\n")


def load_config(path: Path) -> dict:
    config = read_json(path)
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Unsupported projects.json schema")
    projects = config.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise ValueError("Configure at least one project")
    if config.get("primary_project") not in projects:
        raise ValueError("primary_project must identify a configured project")
    for project_id, project in projects.items():
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project_id):
            raise ValueError("Project IDs must be safe lowercase file names")
        if not isinstance(project, dict) or not isinstance(project.get("name"), str):
            raise ValueError("Every project needs a name")
        sources = project.get("sources")
        if not isinstance(sources, dict) or not sources:
            raise ValueError("Every project needs at least one source")
        for source_id, source in sources.items():
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", source_id):
                raise ValueError("Source IDs must be safe lowercase file names")
            if not isinstance(source, dict):
                raise ValueError("Each source must be an object")
            required = {
                "pypi": ["package"],
                "docker": ["repository"],
                "ghcr": ["owner", "repository", "package"],
                "npm": ["package", "start_date"],
            }.get(source.get("kind"))
            if required is None or any(
                not isinstance(source.get(key), str) or not source[key].strip()
                for key in required
            ):
                raise ValueError(
                    f"Invalid source configuration: {project_id}/{source_id}"
                )
            if source["kind"] == "npm":
                date.fromisoformat(source["start_date"])
    return config


def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = (
        "bsm-stats/1.0 (+https://github.com/DMedina559/bsm-stats)"
    )
    return session


class GHCRParser(HTMLParser):
    """Read the count adjacent to GitHub's Total downloads label."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.candidates: list[str] = []
        self.collect_heading = False
        self.seen_label = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.seen_label and tag in ("h2", "h3"):
            self.collect_heading = True
            title = dict(attrs).get("title")
            if title:
                self.candidates.append(title)

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if re.search(r"Total\s+downloads\s*$", " ".join(self.parts[-6:]), re.I):
            self.seen_label = True
        if self.collect_heading:
            self.candidates.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.collect_heading and tag in ("h2", "h3"):
            self.collect_heading = False
            self.seen_label = False


def parse_ghcr(html: str) -> int:
    parser = GHCRParser()
    parser.feed(html)
    for candidate in parser.candidates:
        value = unescape(candidate).strip()
        if re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", value):
            return int(value.replace(",", ""))
    raise ValueError("GHCR total downloads counter was not found or was not exact")


def fetch_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=(10, 30))
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object from the statistics provider")
    return data


def collect_source(
    session: requests.Session, source: dict, now: datetime
) -> tuple[int, str]:
    """Return an exact counter and its counting basis."""
    kind = source["kind"]
    if kind == "pypi":
        data = fetch_json(
            session,
            f"https://pepy.tech/api/v2/projects/{quote(source['package'], safe='')}",
        )
        return validate_count(data["total_downloads"]), "provider_lifetime"
    if kind == "docker":
        repository = quote(source["repository"], safe="/")
        data = fetch_json(
            session, f"https://hub.docker.com/v2/repositories/{repository}/"
        )
        return validate_count(data["pull_count"]), "provider_lifetime"
    if kind == "ghcr":
        owner, repository, package = (
            quote(source[key], safe="") for key in ("owner", "repository", "package")
        )
        response = session.get(
            f"https://github.com/{owner}/{repository}/pkgs/container/{package}",
            timeout=(10, 30),
        )
        response.raise_for_status()
        return parse_ghcr(response.text), "provider_lifetime"
    # npm exposes date ranges rather than a lifetime counter. Sum bounded yearly
    # ranges from an explicit project baseline through yesterday's completed UTC day.
    start = date.fromisoformat(source["start_date"])
    last = now.date() - timedelta(days=1)
    if start > last:
        raise ValueError("npm start_date must precede the current UTC date")
    total = 0
    while start <= last:
        end = min(start + timedelta(days=364), last)
        package = quote(source["package"], safe="")
        data = fetch_json(
            session, f"https://api.npmjs.org/downloads/point/{start}:{end}/{package}"
        )
        if data.get("start") != str(start) or data.get("end") != str(end):
            raise ValueError("npm returned an incomplete date range")
        total += validate_count(data["downloads"])
        start = end + timedelta(days=1)
    return total, f"since:{source['start_date']}"


def source_identity(source: dict) -> dict:
    """Avoid reusing a counter after its package or counting window changes."""
    return {key: value for key, value in source.items() if key != "label"}


def snapshot(project: dict) -> dict:
    return {
        "total": project["total"],
        "status": project["status"],
        "sources": {
            key: {
                field: value[field]
                for field in ("count", "status", "sampled_at", "identity", "decreased")
            }
            for key, value in project["sources"].items()
        },
    }


def comparable(current: dict, previous: dict | None) -> bool:
    if (
        not previous
        or current["status"] != "fresh"
        or previous.get("status") != "fresh"
    ):
        return False
    before = previous.get("sources", {})
    if set(before) != set(current["sources"]):
        return False
    return all(
        before[key].get("identity") == source["identity"]
        and before[key].get("count") is not None
        and source["count"] >= before[key]["count"]
        and not source["decreased"]
        for key, source in current["sources"].items()
    )


def growth_for(project: dict, project_id: str, history: dict, today: date) -> dict:
    growth = {}
    for label, days in (("daily", 1), ("weekly", 7), ("monthly", 30)):
        target = today - timedelta(days=days)
        previous = history.get(str(target), {}).get("projects", {}).get(project_id)
        # Suppress growth across any known counter correction, identity change,
        # or missing observation; endpoints alone can hide a reset and recovery.
        interval = [
            history.get(str(target + timedelta(days=offset)), {})
            .get("projects", {})
            .get(project_id)
            for offset in range(days + 1)
        ]
        valid = all(
            comparable(right, left)
            for left, right in zip(interval, interval[1:])
            if right
        ) and all(interval)
        growth[label] = (
            project["total"] - previous["total"]
            if valid and comparable(project, previous)
            else None
        )
    return growth


def badge(count: int | None, label: str, status: str) -> dict:
    return {
        "schemaVersion": 1,
        "label": label,
        "message": format_num(count) if count is not None else "unavailable",
        "color": "orange" if status == "fresh" else "lightgrey",
    }


def export_history(root: Path, history: dict) -> None:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["date", "project", "source", "count", "status", "sampled_at", "decreased"]
    )
    for day, entry in sorted(history.items()):
        for project_id, project in sorted(entry["projects"].items()):
            for source_id, source in sorted(project["sources"].items()):
                writer.writerow(
                    [
                        day,
                        project_id,
                        source_id,
                        source["count"],
                        source["status"],
                        source["sampled_at"],
                        source["decreased"],
                    ]
                )
    write_text(root / "history.csv", output.getvalue())


def run(root: Path, session: requests.Session, now: datetime) -> dict:
    config = load_config(root / "projects.json")
    previous = read_json(root / "stats.json", {})
    if previous and previous.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported stats.json schema; migrate before collecting")
    now = now.astimezone(timezone.utc)
    stamp = timestamp(now)
    projects = {}
    for project_id, project in config["projects"].items():
        sources = {}
        old_project = previous.get("projects", {}).get(project_id, {})
        for source_id, settings in project["sources"].items():
            old = old_project.get("sources", {}).get(source_id, {})
            identity = source_identity(settings)
            if old.get("identity") != identity:
                old = {}
            try:
                count, basis = collect_source(session, settings, now)
                source = {
                    "count": count,
                    "status": "fresh",
                    "sampled_at": stamp,
                    "error": None,
                    "basis": basis,
                    "decreased": (old.get("count") is not None and count < old["count"])
                    or (
                        bool(old.get("decreased"))
                        and str(old.get("attempted_at", "")).startswith(str(now.date()))
                    ),
                }
            except (
                requests.RequestException,
                ValueError,
                KeyError,
                TypeError,
            ) as error:
                source = {
                    "count": old.get("count"),
                    "status": (
                        "stale" if old.get("count") is not None else "unavailable"
                    ),
                    "sampled_at": old.get("sampled_at"),
                    "error": f"{type(error).__name__}: {error}"[:500],
                    "basis": old.get("basis"),
                    "decreased": bool(old.get("decreased"))
                    and str(old.get("attempted_at", "")).startswith(str(now.date())),
                }
            source.update(
                identity=identity,
                label=settings.get("label", SOURCE_LABELS[settings["kind"]]),
                attempted_at=stamp,
            )
            sources[source_id] = source
        known = all(source["count"] is not None for source in sources.values())
        fresh = all(source["status"] == "fresh" for source in sources.values())
        projects[project_id] = {
            "name": project["name"],
            "url": project.get("url"),
            "sources": sources,
            "total": (
                sum(source["count"] for source in sources.values()) if known else None
            ),
            "status": "fresh" if fresh else ("stale" if known else "unavailable"),
        }
    history = {}
    for path in sorted((root / "history").glob("????-??.json")):
        month = read_json(path)
        if month.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported history schema: {path.name}")
        history.update(month["days"])
    today = now.date()
    history[str(today)] = {
        "collected_at": stamp,
        "projects": {key: snapshot(value) for key, value in projects.items()},
    }
    for project_id, project in projects.items():
        project["growth"] = growth_for(project, project_id, history, today)
        milestones = (
            1_000,
            5_000,
            10_000,
            25_000,
            50_000,
            100_000,
            250_000,
            500_000,
            1_000_000,
        )
        total = project["total"]
        project["milestones"] = {
            "reached": max(
                (value for value in milestones if total is not None and total >= value),
                default=None,
            ),
            "next": next(
                (value for value in milestones if total is not None and total < value),
                None,
            ),
        }
    stats = {
        "schema_version": SCHEMA_VERSION,
        "collected_at": stamp,
        "primary_project": config["primary_project"],
        "projects": projects,
        "status": (
            "fresh"
            if all(project["status"] == "fresh" for project in projects.values())
            else "degraded"
        ),
        "history": sorted({f"history/{day[:7]}.json" for day in history}),
    }
    # Do not replace the legacy badge with an incomplete first collection.
    primary = projects[config["primary_project"]]
    if primary["total"] is not None:
        write_json(
            root / "downloads.json",
            badge(primary["total"], "Downloads", primary["status"]),
        )
    elif not (root / "downloads.json").exists():
        write_json(root / "downloads.json", badge(None, "Downloads", "unavailable"))
    for project_id, project in projects.items():
        write_json(
            root / "badges" / f"{project_id}.json",
            badge(project["total"], "Downloads / pulls", project["status"]),
        )
        for source_id, source in project["sources"].items():
            write_json(
                root / "badges" / f"{project_id}-{source_id}.json",
                badge(source["count"], source["label"], source["status"]),
            )
    month = str(today)[:7]
    write_json(
        root / "history" / f"{month}.json",
        {
            "schema_version": SCHEMA_VERSION,
            "days": {
                day: value
                for day, value in sorted(history.items())
                if day.startswith(month)
            },
        },
    )
    export_history(root, history)
    write_json(root / "stats.json", stats)
    return stats


def summary(stats: dict) -> str:
    lines = [
        f"## Distribution statistics: {stats['status']}",
        "",
        f"Collection attempt: {stats['collected_at']}",
        "",
        "| Project | Source | Count | Status | Last success |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for project_id, project in stats["projects"].items():
        for source_id, source in project["sources"].items():
            warning = " (counter decreased)" if source["decreased"] else ""
            lines.append(
                f"| {project_id} | {source_id} | {source['count'] if source['count'] is not None else '—'} | {source['status']}{warning} | {source['sampled_at'] or 'never'} |"
            )
    failures = [
        f"- `{project_id}/{source_id}`: {source['error'].replace(chr(10), ' ').replace(chr(13), ' ')}"
        for project_id, project in stats["projects"].items()
        for source_id, source in project["sources"].items()
        if source["error"]
    ]
    if failures:
        lines.extend(["", "### Collection errors", "", *failures])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit unsuccessfully after saving degraded observations",
    )
    args = parser.parse_args()
    with create_session() as session:
        stats = run(args.root, session, datetime.now(timezone.utc))
    report = summary(stats)
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(report)
    if args.strict and stats["status"] != "fresh":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
