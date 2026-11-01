"""Render the public WakaTime activity calendar as an SVG for the profile README."""

import json
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_ID = "13ba27f0-fb5f-46cf-ad72-5c001ac27bef"
API_URL = f"https://wakatime.com/api/v1/users/{USER_ID}/insights/days/public"
OUTPUT = Path("assets/wakatime-activity.svg")

CELL = 10
PITCH = 13
LEFT = 30
TOP = 21
HEIGHT = 132
TEXT_COLOR = "#c9d1d9"
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

# The public endpoint reports each day as one of these rounded totals.
LEVELS = (
    (0, "#161b22"),
    (10800, "#36526C"),
    (28800, "#527DA4"),
    (36000, "#8BAAC5"),
    (43200, "#B4C7D9"),
)
TOP_COLOR = "#EBEDF0"
PALETTE = tuple(color for _, color in LEVELS) + (TOP_COLOR,)


def color_for(total):
    for limit, color in LEVELS:
        if total <= limit:
            return color
    return TOP_COLOR


def parse_days(payload):
    days = payload.get("data", {}).get("days")
    if not isinstance(days, list) or len(days) < 360:
        raise SystemExit("Resposta sem o calendário anual. O gráfico foi preservado.")
    return [(date.fromisoformat(day["date"]), float(day["total"])) for day in days]


def fetch_days():
    request = Request(
        API_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "github-wakatime-readme",
        },
    )

    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                return parse_days(json.load(response))
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504):
                raise SystemExit(
                    f"WakaTime retornou HTTP {error.code}. O gráfico foi preservado."
                ) from None
        except (URLError, TimeoutError, ValueError):
            pass

        if attempt < 2:
            time.sleep(15 * (attempt + 1))

    raise SystemExit("Não foi possível consultar o WakaTime. O gráfico foi preservado.")


def position(first_sunday, day):
    """Return the column and row of a day. Rows run from Sunday to Saturday."""
    offset = (day - first_sunday).days
    return offset // 7, offset % 7


def label(x, y, text, anchor="start"):
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}">{text}</text>'


def cell(x, y, color):
    return (
        f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" '
        f'rx="2" fill="{color}"/>'
    )


def month_labels(days, first_sunday, width):
    labels = []
    last_month = None
    last_x = -PITCH * 3

    for day, _ in days:
        column, row = position(first_sunday, day)
        if row != 0 or day.month == last_month:
            continue

        last_month = day.month
        x = LEFT + column * PITCH
        if x - last_x >= PITCH * 3 and x + PITCH * 2 <= width:
            labels.append(label(x, 13, f"{day:%b}"))
            last_x = x

    return labels


def render(days):
    first_day = days[0][0]
    first_sunday = first_day - timedelta(days=(first_day.weekday() + 1) % 7)
    columns = position(first_sunday, days[-1][0])[0] + 1
    width = LEFT + columns * PITCH

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{HEIGHT}" '
        f'viewBox="0 0 {width} {HEIGHT}" role="img" '
        'aria-label="WakaTime coding activity over the last year">',
        f'<rect width="{width}" height="{HEIGHT}" fill="#000"/>',
        f'<g font-family="{FONT}" font-size="12" fill="{TEXT_COLOR}">',
        *month_labels(days, first_sunday, width),
    ]

    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(label(0, TOP + row * PITCH + CELL - 1, name))

    legend_x = width - 42 - len(PALETTE) * PITCH
    parts.append(label(legend_x - 6, HEIGHT - 2, "Less", "end"))
    parts.append(label(width - 34, HEIGHT - 2, "More"))
    parts.append("</g>")

    for index, color in enumerate(PALETTE):
        parts.append(cell(legend_x + index * PITCH, HEIGHT - CELL - 1, color))

    for day, total in days:
        column, row = position(first_sunday, day)
        x = LEFT + column * PITCH
        y = TOP + row * PITCH
        parts.append(cell(x, y, color_for(total)))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    svg = render(fetch_days())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8", newline="\n")
    print(f"Gráfico atualizado: {OUTPUT}")


if __name__ == "__main__":
    main()
