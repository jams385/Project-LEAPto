"""Small HTML helpers shared by the components (badges, numbers, CSS)."""

import functools
import html

import pandas as pd
import streamlit as st

from app import config

# STYLES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def inject_css():
    """Inject app/static/style.css as a page stylesheet.

    st.html wraps a .css file in <style> and sends it to Streamlit's event
    container, so it takes no space in the layout. The file must not contain
    a less-than sign, or the frontend sanitiser drops the whole stylesheet.

    Reads
    -----
    app/static/style.css.

    Returns
    -------
    None. Silently skips if the file is missing (the app still works, just
    with Streamlit's default look).
    """
    css = _read_css()
    if css:
        st.html(f"<style>{css}</style>")


@functools.lru_cache(maxsize=1)
def _read_css():
    """Read app/static/style.css once per server process.

    Returns
    -------
    str
        File contents, or "" if the file is missing.
    """
    path = config.STATIC_DIR / "style.css"
    return path.read_text(encoding="utf-8") if path.exists() else ""


# FORMATTING +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def esc(text):
    """HTML-escape any value for safe inline rendering.

    Parameters
    ----------
    text : Any

    Returns
    -------
    str
    """
    return html.escape(str(text))


def level_color(level):
    """Colour for an alert level (grey for None/unknown).

    Parameters
    ----------
    level : str | None

    Returns
    -------
    str
        Hex colour from config.LEVEL_COLORS.
    """
    return config.LEVEL_COLORS.get(level, config.LEVEL_COLORS[config.CASE_SIGNAL_LEVEL])


def level_badge(level, size="md"):
    """Pill badge showing the alert level in its colour.

    Parameters
    ----------
    level : str | None
        None renders "Case signal only". "No report" gets a hatched badge.
    size : str
        "md", "sm" or "lg" (CSS modifier).

    Returns
    -------
    str
        HTML snippet.
    """
    level = level or config.CASE_SIGNAL_LEVEL
    hatch = " leap-badge-hatched" if level == config.NO_REPORT_LEVEL else ""
    return (f'<span class="leap-badge leap-badge-{size}{hatch}" '
            f'style="--level:{level_color(level)}">{esc(level.upper())}</span>')


def fmt_count(value):
    """Format a reported weekly count.

    Parameters
    ----------
    value : float | None

    Returns
    -------
    str
        Whole number with thousands separator, or "–" for missing.
    """
    return "–" if value is None or pd.isna(value) else f"{value:,.0f}"


def fmt_threshold(value):
    """Outbreak line in plain words: "more than 2 cases".

    Parameters
    ----------
    value : float | None
        Epidemic threshold, cases per 7 days.

    Returns
    -------
    str
        "more than N case(s)" with N rounded down (a week needs a whole number
        of cases above the threshold), or "not available".
    """
    if value is None or pd.isna(value):
        return "not available"
    n = int(value)
    return f"more than {n} case" + ("" if n == 1 else "s")


def fmt_week(ts):
    """Format a week start like "Dec 18, 2011".

    Parameters
    ----------
    ts : pandas.Timestamp

    Returns
    -------
    str
    """
    ts = pd.Timestamp(ts)
    return f"{ts:%b} {ts.day}, {ts.year}"  # no %-d: unsupported on Windows


def fmt_range(start, end):
    """Format a date range like "Dec 18 – Jan 14, 2012".

    Parameters
    ----------
    start, end : pandas.Timestamp

    Returns
    -------
    str
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    left = f"{start:%b} {start.day}" + (f", {start.year}" if start.year != end.year else "")
    return f"{left} – {end:%b} {end.day}, {end.year}"


def fmt_span(start, end=None, year=True):
    """Format a week as a short span: "Oct 23–29, 2022" or "Oct 30–Nov 5".

    Parameters
    ----------
    start : pandas.Timestamp
        First day (a Sunday).
    end : pandas.Timestamp | None
        Last day; start + 6 days if None.
    year : bool
        Append the end year.

    Returns
    -------
    str
    """
    start = pd.Timestamp(start)
    end = start + pd.Timedelta(days=6) if end is None else pd.Timestamp(end)
    right = f"{end.day}" if end.month == start.month else f"{end:%b} {end.day}"
    left = f"{start:%b} {start.day}" + (f", {start.year}" if year and start.year != end.year
                                        else "")
    return f"{left}–{right}" + (f", {end.year}" if year else "")


def fmt_day(ts, year=True):
    """Format one day: "Oct 22, 2022" (or "Oct 22").

    Parameters
    ----------
    ts : pandas.Timestamp
    year : bool

    Returns
    -------
    str
    """
    ts = pd.Timestamp(ts)
    return f"{ts:%b} {ts.day}" + (f", {ts.year}" if year else "")
