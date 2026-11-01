"""Exercise the activity chart with synthetic public WakaTime data."""

import io
import json
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import wakatime_activity as activity  # noqa: E402


FIRST_DAY = date(2025, 11, 2)  # A Sunday.


def payload(totals=None):
    totals = totals or {}
    days = [FIRST_DAY + timedelta(days=index) for index in range(365)]
    return {
        "data": {
            "days": [
                {"date": day.isoformat(), "total": totals.get(day, 0)}
                for day in days
            ]
        }
    }


def response(content):
    return io.BytesIO(json.dumps(content).encode())


class ActivityChartTests(unittest.TestCase):
    def test_public_totals_map_to_the_six_wakatime_colors(self):
        totals = (0, 10800, 28800, 36000, 43200, 43201)
        self.assertEqual(
            tuple(activity.color_for(total) for total in totals), activity.PALETTE
        )

    def test_chart_uses_reference_size_and_grid(self):
        svg = activity.render(activity.parse_days(payload()))
        self.assertIn('width="719" height="132"', svg)
        self.assertIn('<rect x="30" y="21" width="10"', svg)
        self.assertIn('<rect x="30" y="99" width="10"', svg)
        self.assertEqual(svg.count('rx="2"'), 365 + len(activity.PALETTE))

    def test_a_day_is_drawn_in_its_week_and_weekday_cell(self):
        wednesday = FIRST_DAY + timedelta(days=10)
        svg = activity.render(activity.parse_days(payload({wednesday: 43201})))
        self.assertIn(f'<rect x="43" y="60" width="10" height="10" rx="2" fill="{activity.TOP_COLOR}"/>', svg)

    def test_chart_starting_midweek_keeps_the_weekday_rows(self):
        days = [(date(2025, 11, 5) + timedelta(days=index), 0) for index in range(365)]
        svg = activity.render(days)
        self.assertIn('<rect x="30" y="60" width="10"', svg)
        self.assertNotIn('<rect x="30" y="21" width="10"', svg)

    def test_month_labels_follow_the_calendar(self):
        svg = activity.render(activity.parse_days(payload()))
        self.assertLess(svg.index(">Nov<"), svg.index(">Dec<"))
        self.assertLess(svg.index(">Dec<"), svg.index(">Jan<"))
        self.assertIn('<text x="30" y="13" text-anchor="start">Nov</text>', svg)

    def test_incomplete_calendar_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "preservado"):
            activity.parse_days({"data": {"days": []}})
        with self.assertRaisesRegex(SystemExit, "preservado"):
            activity.parse_days({"error": "Not found."})

    def test_transient_failure_retries_then_returns_days(self):
        with patch.object(activity, "urlopen") as http, patch("time.sleep") as sleep:
            http.side_effect = [
                HTTPError("https://example.test", 503, "", {}, None),
                response(payload()),
            ]
            days = activity.fetch_days()
        self.assertEqual(len(days), 365)
        sleep.assert_called_once_with(15)

    def test_permanent_failure_stops_without_retry(self):
        with patch.object(activity, "urlopen") as http, patch("time.sleep") as sleep:
            http.side_effect = HTTPError("https://example.test", 404, "", {}, None)
            with self.assertRaisesRegex(SystemExit, "HTTP 404"):
                activity.fetch_days()
        http.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
