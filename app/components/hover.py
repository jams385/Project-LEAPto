"""Hover labels shared by the map and every chart, so they all look alike.

One style (dark box, thin light border, left-aligned, readable Inter) is set
by `style_hover(fig)`. The text is built from small helpers that return None
for a missing value, so a label never shows "nan" or "None".
"""

import pandas as pd

from app import config
from src.views import usual_week_text

# STYLE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

HOVERLABEL = dict(
    bgcolor="#0B1E33", bordercolor="rgba(255, 255, 255, 0.45)", align="left",
    font=dict(family="Inter, system-ui, sans-serif", size=13, color="#FFFFFF"),
    namelength=0)  # never prefix the text with the trace name


def style_hover(fig):
    """Give a figure the shared hover-label style.

    Parameters
    ----------
    fig : plotly.graph_objects.Figure

    Returns
    -------
    plotly.graph_objects.Figure
        The same figure, with the styled hover label (dark background, thin
        border, left-aligned, no trace-name prefix).
    """
    fig.update_layout(hoverlabel=HOVERLABEL)
    return fig


# TEXT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def number(value, digits=0, unit=""):
    """A number for a label, or None when it is missing.

    Parameters
    ----------
    value : float | int | None
    digits : int
        Decimals shown.
    unit : str
        Appended as is (" mm", "%", "×").

    Returns
    -------
    str | None
        "109 mm"; None for None / NaN, so callers can skip the line.
    """
    if value is None or pd.isna(value):
        return None
    return f"{value:,.{digits}f}{unit}"


def hover_lines(*lines):
    """Join hover lines with line breaks, leaving out the empty ones.

    Parameters
    ----------
    *lines : str | None
        Lines of text (HTML allowed: <b>, <i>, <span>); None and "" are skipped.

    Returns
    -------
    str
    """
    return "<br>".join(line for line in lines if line)


def level_line(level):
    """The level with a marker in its colour.

    Parameters
    ----------
    level : str | None
        A shown alert level.

    Returns
    -------
    str | None
        '● Warning' with the dot coloured by config.LEVEL_COLORS; None when
        there is no level.
    """
    if not isinstance(level, str) or not level:
        return None
    color = config.LEVEL_COLORS.get(level, config.LEVEL_COLORS[config.CASE_SIGNAL_LEVEL])
    return f'<span style="color:{color}">●</span> {level}'


def city_hover(row, base_rate=None, layer="Risk"):
    """The map's hover text for one city.

    Parameters
    ----------
    row : namedtuple
        Snapshot row; any of alert_level, outbreak_prob, confidence,
        rain_week_mm, rain_usual_mm, rain_status, latest_cases, hazard_pct may be missing.
    base_rate : float | None
        Share of all city-weeks that are outbreak weeks (for "≈N× a usual week").
    layer : str
        The active map layer; "Rainfall" adds the city's usual rain and "Flood
        hazard" the flood-hazard share.

    Returns
    -------
    str
        Bold city name; the level with its coloured marker; "≈N× a usual
        week" (Watch / Warning with a chance) or, for case-signal and
        lower-confidence cities, their short note instead; rain last week
        against the city's usual; reported cases in the latest week; the
        city's usual rain on the Rainfall layer, the high flood-hazard share on
        the Flood hazard layer; and an italic
        "Click for details". Lines whose value is missing are left out.
    """
    get = lambda name: getattr(row, name, None)  # noqa: E731
    level, confidence = get("alert_level"), get("confidence")
    if confidence in ("case_signal", "lower"):
        # Short note instead of a multiplier.
        note = config.CONFIDENCE_NOTES[confidence].capitalize()
    else:
        text = usual_week_text(level, get("outbreak_prob"), base_rate)
        note = text if text and text.startswith(("≈", "over")) else None
    rain = number(get("rain_week_mm"), 0, " mm")
    status = get("rain_status")
    rain_line = (f"Rain last week: {rain}" + (f" ({status.lower()})" if isinstance(status, str)
                                               and status else "")) if rain else None
    usual = number(get("rain_usual_mm"), 0, " mm")
    cases = number(get("latest_cases"), 0)
    hazard = number(get("hazard_pct"), 0, "%")
    return hover_lines(
        f"<b>{get('city_name')}</b>", level_line(level), note, rain_line,
        f"Usual for this week: {usual}" if usual and layer == "Rainfall" else None,
        f"Reported cases, latest week: {cases}" if cases else None,
        f"High flood-hazard area: {hazard}" if hazard and layer == "Flood hazard" else None,
        "<i>Click for details</i>")


def city_hovers(snap, base_rate=None, layer="Risk"):
    """Hover text for every city of a snapshot, in row order.

    Parameters
    ----------
    snap : pandas.DataFrame
        src.views snapshot.
    base_rate : float | None
    layer : str

    Returns
    -------
    list[str]
        One text per row; [] for an empty snapshot.
    """
    return [city_hover(r, base_rate, layer) for r in snap.itertuples()]


def week_title(week, *, year=True):
    """A bold hover title for a week, "Week of Oct 23" / "Week of Oct 23, 2022".

    Parameters
    ----------
    week : pandas.Timestamp
    year : bool

    Returns
    -------
    str
    """
    stamp = pd.Timestamp(week)
    text = f"Week of {stamp:%b} {stamp.day}" + (f", {stamp.year}" if year else "")
    return f"<b>{text}</b>"
