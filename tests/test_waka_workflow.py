"""Exercise the actual embedded workflow script with synthetic credentials/data."""

import contextlib
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/waka-readme.yml").read_text(encoding="utf-8")
SCRIPT = textwrap.dedent(re.search(
    r"        shell: python\n        run: \|\n(.*?)(?=\n      - name:|\Z)",
    WORKFLOW,
    flags=re.DOTALL,
).group(1))
TOKEN = "waka_tok_unit_test_only"
ORIGINAL = "Profile intro\n<!--START_SECTION:waka-->old stats<!--END_SECTION:waka-->\nFooter\n"


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 31, 12, tzinfo=tz)


def summaries():
    return {
        "data": [
            {
                "range": {"date": f"2026-10-{day}"},
                "languages": [{"name": "Python", "total_seconds": 3600}],
            }
            for day in range(24, 31)
        ],
        "cumulative_total": {"seconds": 7 * 3600},
    }


def response(payload):
    result = io.BytesIO(json.dumps(payload).encode())
    result.status = 200
    return result


class WakaWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.readme = Path(temporary.name) / "README.md"
        self.readme.write_text(ORIGINAL, encoding="utf-8")
        self.output = io.StringIO()
        self.http = self.enterContext(patch("urllib.request.urlopen"))
        self.http.return_value = response(summaries())
        self.sleep = self.enterContext(patch("time.sleep"))
        self.enterContext(patch("pathlib.Path", return_value=self.readme))
        self.enterContext(patch("datetime.datetime", FixedDatetime))
        # Fixed test date/offset; no system tzdata dependency on Windows.
        # These tests do not validate the IANA timezone database.
        self.zone = self.enterContext(patch(
            "zoneinfo.ZoneInfo", return_value=timezone(timedelta(hours=-3))
        ))

    def run_script(self, token=TOKEN):
        with patch.dict(os.environ, {"WAKATIME_OAUTH_TOKEN": token}, clear=True):
            with contextlib.redirect_stdout(self.output):
                exec(compile(SCRIPT, "waka-readme.yml", "exec"), {})

    def test_workflow_uses_dedicated_oauth_secret(self):
        self.assertIn(
            "WAKATIME_OAUTH_TOKEN: ${{ secrets.WAKATIME_OAUTH_TOKEN }}", WORKFLOW
        )
        self.assertNotIn("secrets.WAKATIME_API_KEY", WORKFLOW)

    def test_missing_token_fails_before_network_and_preserves_readme(self):
        with self.assertRaisesRegex(SystemExit, "WAKATIME_OAUTH_TOKEN"):
            self.run_script("")
        self.http.assert_not_called()
        self.assertEqual(self.readme.read_text(encoding="utf-8"), ORIGINAL)

    def test_legacy_key_is_rejected_without_exposure(self):
        legacy = "synthetic-legacy-api-key"
        with self.assertRaisesRegex(SystemExit, "OAuth") as error:
            self.run_script(legacy)
        self.http.assert_not_called()
        self.assertNotIn(legacy, str(error.exception) + self.output.getvalue())
        self.assertEqual(self.readme.read_text(encoding="utf-8"), ORIGINAL)

    def test_bearer_request_and_same_seven_day_window(self):
        self.run_script("  " + TOKEN + "  ")
        request = self.http.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TOKEN)
        url = urlsplit(request.full_url)
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.netloc, "api.wakatime.com")
        self.assertEqual(url.path, "/api/v1/users/current/summaries")
        self.assertEqual(parse_qs(url.query), {
            "start": ["2026-10-24"], "end": ["2026-10-30"],
            "timezone": ["America/Sao_Paulo"],
        })
        self.assertNotIn(TOKEN, request.full_url + self.output.getvalue())
        self.zone.assert_called_once_with("America/Sao_Paulo")
        updated = self.readme.read_text(encoding="utf-8")
        self.assertIn("Total Time: 7 hrs 0 mins", updated)
        self.assertTrue(updated.startswith("Profile intro\n"))
        self.assertTrue(updated.endswith("\nFooter\n"))

    def test_auth_failure_preserves_readme_without_retry(self):
        for code in (401, 403):
            with self.subTest(code=code):
                self.http.reset_mock()
                self.http.side_effect = HTTPError("https://example.test", code, "", {}, None)
                with self.assertRaisesRegex(SystemExit, "read_summaries") as error:
                    self.run_script()
                self.http.assert_called_once()
                self.sleep.assert_not_called()
                self.assertIn("WAKATIME_OAUTH_TOKEN", str(error.exception))
                self.assertNotIn(TOKEN, str(error.exception))
                self.assertEqual(self.readme.read_text(encoding="utf-8"), ORIGINAL)

    def test_transient_failure_retries_then_updates(self):
        self.http.side_effect = [
            HTTPError("https://example.test", 503, "", {}, None),
            response(summaries()),
        ]
        self.run_script()
        self.assertEqual(self.http.call_count, 2)
        self.sleep.assert_called_once_with(15)
        self.assertIn("Total Time: 7 hrs 0 mins", self.readme.read_text(encoding="utf-8"))

    def test_incomplete_response_preserves_readme(self):
        payload = summaries()
        payload["data"].pop()
        self.http.return_value = response(payload)
        with self.assertRaisesRegex(SystemExit, "incompleto"):
            self.run_script()
        self.assertEqual(self.readme.read_text(encoding="utf-8"), ORIGINAL)


if __name__ == "__main__":
    unittest.main()
