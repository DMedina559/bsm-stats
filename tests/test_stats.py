"""Exercise collection, outage recovery, publication, and history contracts."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import requests

import update_stats as stats

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)


def response(data=None, text="", status=200):
    result = Mock(text=text)
    result.json.return_value = data
    result.raise_for_status.side_effect = (
        requests.HTTPError(f"HTTP {status}") if status >= 400 else None
    )
    return result


class CollectorTests(unittest.TestCase):
    def test_ghcr_saved_markup(self):
        for filename, count in (("ghcr.html", 12345), ("ghcr-changed.html", 98765)):
            with self.subTest(filename=filename):
                self.assertEqual(
                    stats.parse_ghcr((ROOT / "tests/fixtures" / filename).read_text()),
                    count,
                )

    def test_ghcr_rejects_missing_and_rounded_counters(self):
        for html in (
            '<h3 title="123">Other downloads</h3>',
            "<span>Total downloads</span><h3>1.2k</h3>",
            '<span>Total downloads</span><h3 title="-1">-1</h3>',
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                stats.parse_ghcr(html)

    def test_invalid_counts(self):
        for value in (None, -1, True, 1.2, "42", {}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stats.validate_count(value)
        self.assertEqual(stats.validate_count(0), 0)

    def test_formatting_boundaries(self):
        for value, expected in (
            (0, "0"),
            (999, "999"),
            (1000, "1.0k"),
            (97200, "97.2k"),
            (999950, "1.0M"),
            (1000000, "1.0M"),
        ):
            self.assertEqual(stats.format_num(value), expected)

    def test_http_failures_are_not_parsed(self):
        session = Mock()
        session.get.return_value = response({"pull_count": 100}, status=429)
        with self.assertRaises(requests.HTTPError):
            stats.collect_source(
                session, {"kind": "docker", "repository": "owner/image"}, NOW
            )
        session.get.return_value.json.assert_not_called()
        self.assertEqual(session.get.call_args.kwargs["timeout"], (10, 30))

    def test_retry_policy_is_bounded(self):
        with stats.create_session() as session:
            retry = session.get_adapter("https://").max_retries
            self.assertEqual(retry.total, 3)
            self.assertIn(429, retry.status_forcelist)
            self.assertFalse(retry.respect_retry_after_header)

    def test_npm_sums_disjoint_ranges_and_encodes_scope(self):
        session = Mock()
        session.get.side_effect = [
            response({"downloads": 100, "start": "2025-01-01", "end": "2025-12-31"}),
            response({"downloads": 50, "start": "2026-01-01", "end": "2026-10-15"}),
        ]
        value, basis = stats.collect_source(
            session,
            {"kind": "npm", "package": "@bsm/client", "start_date": "2025-01-01"},
            NOW,
        )
        self.assertEqual((value, basis), (150, "since:2025-01-01"))
        self.assertIn("%40bsm%2Fclient", session.get.call_args.args[0])

    def test_npm_rejects_incomplete_ranges(self):
        session = Mock()
        session.get.return_value = response(
            {"downloads": 100, "start": "2026-10-01", "end": "2026-10-14"}
        )
        with self.assertRaises(ValueError):
            stats.collect_source(
                session,
                {"kind": "npm", "package": "client", "start_date": "2026-10-01"},
                NOW,
            )

    def test_nonobject_json_is_a_source_failure(self):
        session = Mock()
        session.get.return_value = response([])
        with self.assertRaises(ValueError):
            stats.collect_source(
                session,
                {"kind": "npm", "package": "client", "start_date": "2026-10-01"},
                NOW,
            )


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = json.loads((ROOT / "projects.json").read_text())
        self.config["projects"] = {
            "bedrock-server-manager": self.config["projects"]["bedrock-server-manager"]
        }
        self.save_config()
        self.session = Mock()

    def save_config(self):
        (self.root / "projects.json").write_text(json.dumps(self.config))

    def collect(self, pypi=100, docker=50, ghcr=10, now=NOW):
        self.session.get.side_effect = [
            (
                pypi
                if isinstance(pypi, Exception)
                else response({"total_downloads": pypi})
            ),
            (
                docker
                if isinstance(docker, Exception)
                else response({"pull_count": docker})
            ),
            (
                ghcr
                if isinstance(ghcr, Exception)
                else response(
                    text=f'<span>Total downloads</span><h3 title="{ghcr}">{ghcr}</h3>'
                )
            ),
        ]
        return stats.run(self.root, self.session, now)

    def project(self, result):
        return result["projects"]["bedrock-server-manager"]

    def test_exact_counts_history_csv_and_badges(self):
        result = self.collect()
        self.assertEqual(result["status"], "fresh")
        self.assertEqual(self.project(result)["total"], 160)
        history = stats.read_json(self.root / "history/2026-10.json")
        self.assertEqual(len(history["days"]), 1)
        self.assertIn(
            "2026-10-16,bedrock-server-manager,pypi,100,fresh",
            (self.root / "history.csv").read_text(),
        )
        self.assertEqual(
            stats.read_json(self.root / "downloads.json")["message"], "160"
        )
        self.assertEqual(len(list((self.root / "badges").glob("*.json"))), 4)

    def test_partial_outage_preserves_source_and_timestamp(self):
        self.collect()
        result = self.collect(
            pypi=requests.Timeout("source unavailable"),
            docker=60,
            now=NOW + timedelta(days=1),
        )
        project = self.project(result)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(project["total"], 170)
        self.assertEqual(project["sources"]["pypi"]["status"], "stale")
        self.assertEqual(project["sources"]["pypi"]["sampled_at"], stats.timestamp(NOW))
        self.assertIsNone(project["growth"]["daily"])
        self.assertEqual(
            stats.read_json(self.root / "downloads.json")["color"], "lightgrey"
        )

    def test_first_outage_keeps_legacy_badge(self):
        legacy = {
            "schemaVersion": 1,
            "label": "Downloads",
            "message": "97.2k",
            "color": "orange",
        }
        stats.write_json(self.root / "downloads.json", legacy)
        result = self.collect(pypi=requests.Timeout())
        self.assertIsNone(self.project(result)["total"])
        self.assertEqual(stats.read_json(self.root / "downloads.json"), legacy)

    def test_total_outage_does_not_publish_zero(self):
        self.collect()
        result = self.collect(
            pypi=requests.Timeout(), docker=requests.Timeout(), ghcr=requests.Timeout()
        )
        self.assertEqual(self.project(result)["total"], 160)
        self.assertEqual(
            stats.read_json(self.root / "downloads.json")["message"], "160"
        )

    def test_first_outage_without_legacy_is_unavailable(self):
        self.collect(pypi=requests.Timeout())
        self.assertEqual(
            stats.read_json(self.root / "downloads.json")["message"], "unavailable"
        )

    def test_malformed_response_preserves_old_count(self):
        self.collect()
        result = self.collect(pypi=True)
        self.assertEqual(self.project(result)["sources"]["pypi"]["count"], 100)
        self.assertEqual(self.project(result)["sources"]["pypi"]["status"], "stale")

    def test_recovery_has_gap_then_resumes_growth(self):
        self.collect()
        self.collect(pypi=requests.Timeout(), now=NOW + timedelta(days=1))
        recovered = self.collect(pypi=150, now=NOW + timedelta(days=2))
        self.assertIsNone(self.project(recovered)["growth"]["daily"])
        following = self.collect(pypi=160, now=NOW + timedelta(days=3))
        self.assertEqual(self.project(following)["growth"]["daily"], 10)

    def test_counter_decrease_is_recorded_and_growth_suppressed(self):
        self.collect()
        result = self.collect(pypi=90, now=NOW + timedelta(days=1))
        project = self.project(result)
        self.assertTrue(project["sources"]["pypi"]["decreased"])
        self.assertEqual(project["sources"]["pypi"]["count"], 90)
        self.assertIsNone(project["growth"]["daily"])

    def test_month_rollover_and_complete_growth_windows(self):
        for offset in range(31):
            result = self.collect(pypi=100 + offset, now=NOW + timedelta(days=offset))
        self.assertEqual(
            self.project(result)["growth"], {"daily": 1, "weekly": 7, "monthly": 30}
        )
        self.assertEqual(len(result["history"]), 2)
        self.assertTrue((self.root / "history/2026-10.json").exists())

    def test_same_day_run_replaces_snapshot(self):
        self.collect()
        self.collect(pypi=120, now=NOW + timedelta(hours=1))
        days = stats.read_json(self.root / "history/2026-10.json")["days"]
        self.assertEqual(len(days), 1)
        self.assertEqual(
            days["2026-10-16"]["projects"]["bedrock-server-manager"]["total"], 180
        )

    def test_identity_changes_do_not_reuse_old_counter(self):
        self.collect()
        self.config["projects"]["bedrock-server-manager"]["sources"]["pypi"][
            "package"
        ] = "another-package"
        self.save_config()
        result = self.collect(pypi=requests.Timeout())
        self.assertIsNone(self.project(result)["sources"]["pypi"]["count"])

    def test_multiple_projects_are_not_aggregated(self):
        self.config["projects"]["client"] = {
            "name": "BSM client",
            "sources": {"pypi": {"kind": "pypi", "package": "bsm-api-client"}},
        }
        self.save_config()
        self.session.get.side_effect = [
            response({"total_downloads": 100}),
            response({"pull_count": 50}),
            response(text="<span>Total downloads</span><h3>10</h3>"),
            response({"total_downloads": 25}),
        ]
        result = stats.run(self.root, self.session, NOW)
        self.assertEqual(result["projects"]["client"]["total"], 25)
        self.assertEqual(self.project(result)["total"], 160)
        self.assertEqual(
            stats.read_json(self.root / "downloads.json")["message"], "160"
        )

    def test_invalid_config_does_not_touch_existing_output(self):
        self.collect()
        original = (self.root / "stats.json").read_text()
        self.config["primary_project"] = "missing"
        self.save_config()
        with self.assertRaises(ValueError):
            stats.run(self.root, self.session, NOW)
        self.assertEqual((self.root / "stats.json").read_text(), original)

    def test_same_day_correction_cannot_be_hidden_by_recovery(self):
        self.collect()
        self.collect(pypi=90, now=NOW + timedelta(days=1))
        result = self.collect(pypi=120, now=NOW + timedelta(days=1, hours=1))
        self.assertTrue(self.project(result)["sources"]["pypi"]["decreased"])
        self.assertIsNone(self.project(result)["growth"]["daily"])

    def test_build_packages_real_outputs(self):
        from scripts.build_site import build

        self.collect()
        import shutil

        shutil.copytree(ROOT / "web", self.root / "web")
        build(self.root, self.root / "dist/site")
        self.assertTrue((self.root / "dist/site/index.html").exists())
        self.assertTrue((self.root / "dist/site/history/2026-10.json").exists())
        self.assertEqual(
            stats.read_json(self.root / "dist/site/stats.json")["status"], "fresh"
        )
        with self.assertRaises(ValueError):
            build(self.root, self.root)
        with self.assertRaises(ValueError):
            build(self.root, self.root / "web")

    def test_missing_days_prevent_growth(self):
        self.collect()
        result = self.collect(pypi=150, now=NOW + timedelta(days=7))
        self.assertIsNone(self.project(result)["growth"]["weekly"])

    def test_strict_cli_saves_degraded_observation_before_failure(self):
        from unittest.mock import patch

        self.session.get.side_effect = requests.Timeout("offline")
        environment = patch.dict(stats.os.environ, {"GITHUB_STEP_SUMMARY": ""})
        environment.start()
        self.addCleanup(environment.stop)
        context = Mock()
        context.__enter__ = Mock(return_value=self.session)
        context.__exit__ = Mock(return_value=False)
        with patch.object(stats, "create_session", return_value=context), patch(
            "sys.argv", ["update_stats.py", "--root", str(self.root), "--strict"]
        ):
            with self.assertRaises(SystemExit) as caught:
                stats.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertEqual(
            stats.read_json(self.root / "stats.json")["status"], "degraded"
        )


if __name__ == "__main__":
    unittest.main()
