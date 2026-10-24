"""The Overview (DESIGN_V3 §1): "what do I need to know, and where?".

Top: the title, a sub-line with the forecast week and how far the rain and
case data reach (always past dates from the data, never today's), a
hoverable note on the data period, the forecast-week controls, then the
situation line and the always-visible honesty note. Below: the map, the
city drawer when a city is open, and "All covered cities" sorted by level.
Clicking a city in the list or on the map opens the drawer and highlights
the city in both places. "Compare all cities" (chart + read-only table) sits collapsed
underneath.
"""

import pandas as pd
import streamlit as st

from app import config
from app.components.all_cities import render_compare
from app.components.city_details import render_city_drawer
from app.components.city_map import render_map
from app.components.forecast_bar import (render_horizon_toggle, render_week_stepper,
                                         target_week)
from app.components.legend import render_legend
from app.components.ui import esc, fmt_day, fmt_span, level_badge, level_color
from app.components.city_details import flood_chip_html
from app.state import flood_alert_start, select_city
from src.views import cases_week_start, flood_alert_weeks_left, place_label

# WORDING ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# Situation-line labels per level (Warning / Watch / Normal always shown).
COUNT_LABELS = {
    "Warning": "at Warning",
    "Watch": "at Watch",
    "Normal": "Normal",
    config.CASE_SIGNAL_LEVEL: "case signal only",
    config.NO_REPORT_LEVEL: "no report",
    config.NO_FORECAST_LEVEL: "no forecast",
}


def data_range_tip(origins):
    """Hover text explaining which weeks the app can show.

    Parameters
    ----------
    origins : list[pandas.Timestamp]
        Weeks with a forecast (sorted, non-empty).

    Returns
    -------
    str
    """
    first, last = origins[0], origins[-1]
    return (f"LEAPto runs on Project CCHAIN data (2008–2022). Forecasts exist for weeks from "
            f"{fmt_day(first)} to {fmt_day(last + pd.Timedelta(days=6))}: the years the "
            "model was tested on, each forecast using only earlier data. Every date on this "
            "page is a past week in that period, not today.")


def title_html(origin, horizon, n_cities, origins):
    """Title and the dated sub-line.

    Parameters
    ----------
    origin : pandas.Timestamp
        Forecast origin (the week "next week" starts).
    horizon : int
        Selected forecast week.
    n_cities : int
        Cities covered.
    origins : list[pandas.Timestamp]
        Weeks with a forecast (for the hover note).

    Returns
    -------
    str
        "Leptospirosis risk after rainfall" and a sub-line of "12 cities",
        "Forecast for [Oct 23–29, 2022]", "Rain data to [Oct 22, 2022]",
        "Cases to [Oct 15, 2022]" and "⚠ Past data, 2008–2022", spaced apart,
        with the dates emphasised and the last item hoverable (also
        focusable for keyboard users).
    """
    rain_to = pd.Timestamp(origin) - pd.Timedelta(days=1)
    cases_to = cases_week_start(origin) + pd.Timedelta(days=6)
    tip = esc(data_range_tip(origins))
    return (f'<h1 class="leap-title">{esc(config.OVERVIEW_TITLE)}</h1>'
            f'<div class="leap-subline"><span>{n_cities} cities</span>'
            f'<span>Forecast for <b class="leap-date">'
            f'{esc(fmt_span(target_week(origin, horizon)))}</b></span>'
            f'<span>Rain data to <b class="leap-date">{esc(fmt_day(rain_to))}</b></span>'
            f'<span>Cases to <b class="leap-date">{esc(fmt_day(cases_to))}</b></span>'
            f'<span class="leap-tip" tabindex="0">'
            f'<span class="leap-tip-chip">⚠ Past data, 2008–2022</span>'
            f'<span class="leap-tip-body" role="tooltip">{tip}</span></span></div>')


def situation_html(snap, horizon, origin, info):
    """The situation line and the always-visible honesty note.

    Parameters
    ----------
    snap : pandas.DataFrame
        Current src.views snapshot.
    horizon : int
        Selected forecast week.
    origin : pandas.Timestamp
        Forecast origin.
    info : dict
        Alerts source info (kind), for the "Baseline, model pending" tag.

    Returns
    -------
    str
        "Next week (Oct 23–29, 2022): ● 3 at Warning ● 1 at Watch ● 5 Normal
        ● 3 case signal only", then "FORECAST", "Forecast, not confirmed
        cases" and "Data 2008–2022" as separate spans (spaced apart).
    """
    name = config.HORIZON_NAMES.get(horizon, f"In {horizon} weeks")
    counts = snap.alert_level.value_counts()
    parts = []
    for level, label in COUNT_LABELS.items():
        n = int(counts.get(level, 0))
        if n or level in config.ALERT_LEVELS:
            parts.append(f'<span class="leap-count" style="--level:{level_color(level)}">'
                         f'<i></i><b>{n}</b> {esc(label)}</span>')
    pending = (f'<span class="leap-pending">{esc(config.BASELINE_BANNER)}</span>'
               if info.get("kind") != "model" else "")
    return (f'<div class="leap-situation-row"><div class="leap-situation">{esc(name)} '
            f'(<b>{esc(fmt_span(target_week(origin, horizon)))}</b>):</div>'
            f'<div class="leap-counts">{"".join(parts)}</div>'
            f'<div class="leap-honesty"><span class="leap-tag leap-tag-forecast">FORECAST</span>'
            f'<span>{esc(config.HONESTY_NOTE)}</span>'
            f'<span class="leap-honesty-period">{esc(config.DATA_PERIOD)}</span>'
            f'{pending}</div></div>')


def city_note(r):
    """The small note under a city's name: province, or its confidence note.

    Parameters
    ----------
    r : namedtuple
        Snapshot row (province, confidence).

    Returns
    -------
    str
        "Metro Manila" / "Pangasinan" for standard cities, else
        config.CONFIDENCE_NOTES ("lower confidence", "too few cases to
        forecast").
    """
    if r.confidence in (None, "standard"):
        return place_label(r.province)
    return config.CONFIDENCE_NOTES.get(r.confidence, "")


def list_order(snap):
    """Cities in list order: by level (most urgent first), then chance, then name.

    Parameters
    ----------
    snap : pandas.DataFrame

    Returns
    -------
    pandas.DataFrame
        Sorted copy.
    """
    order = {lvl: i for i, lvl in enumerate(config.DISPLAY_LEVELS)}
    return (snap.assign(_o=snap.alert_level.map(order).fillna(len(order)),
                        _p=snap.outbreak_prob.fillna(-1))
            .sort_values(["_o", "_p", "city_name"], ascending=[True, False, True])
            .drop(columns=["_o", "_p"]))


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def render_city_list(snap, horizon):
    """ "All covered cities": one clickable row per city, sorted by level.

    Parameters
    ----------
    snap : pandas.DataFrame
    horizon : int

    Returns
    -------
    None. Clicking a name opens the drawer (select_city); the open city's
    row is highlighted (its container key starts with "crowsel_").
    """
    ss = st.session_state
    target = target_week(ss.origin, horizon)
    with st.container(key="citylist"):
        st.html(f'<div class="leap-list-head"><span>All covered cities</span>'
                f'<small>{esc(config.HORIZON_NAMES.get(horizon, ""))}</small></div>')
        for r in list_order(snap).itertuples():
            selected = r.adm3_pcode == ss.selected
            key = f"{'crowsel' if selected else 'crow'}_{r.adm3_pcode}"
            with st.container(key=key, horizontal=True, vertical_alignment="center",
                              wrap=False, gap="small"):
                with st.container(gap=None):
                    st.button(r.city_name, key=f"pick_{r.adm3_pcode}", type="tertiary",
                              on_click=select_city, args=(None if selected else r.adm3_pcode,),
                              help="Close details" if selected else "Open details")
                    st.html(f'<div class="leap-crow-note">{esc(city_note(r))}</div>')
                chip = flood_chip_html(flood_alert_weeks_left(flood_alert_start(r.adm3_pcode),
                                                               target))
                st.html(f'<div class="leap-dbadges">{level_badge(r.alert_level, "sm")}{chip}'
                        '</div>', width="content")


def render_notices(snap, horizon, origin):
    """Notices under the controls: week moved, or no forecast at this horizon.

    Parameters
    ----------
    snap : pandas.DataFrame
    horizon : int
    origin : pandas.Timestamp

    Returns
    -------
    None
    """
    ss = st.session_state
    if ss.get("notice"):
        st.html(f'<div class="leap-notice">{esc(ss.notice)}</div>')
    if (snap.alert_level == config.NO_FORECAST_LEVEL).all():
        week = fmt_span(target_week(origin, horizon))
        st.html(f'<div class="leap-notice">No forecast for the week of {esc(week)}: the '
                f'forecasts end in December 2022. '
                f'{esc(config.HORIZON_NAMES[config.HORIZONS[0]])} is available.</div>')


def render_overview(snap, horizon, info, origins, geojson, zooms):
    """Draw the whole Overview.

    Parameters
    ----------
    snap : pandas.DataFrame
        Current snapshot.
    horizon : int
        Selected forecast week.
    info : dict
        Alerts source info.
    origins : list[pandas.Timestamp]
        Weeks with a forecast.
    geojson, zooms
        From app.data.load_geojson.

    Returns
    -------
    None. Columns are [map, list], or [map, drawer, list] with a city open.
    """
    ss = st.session_state
    with st.container(key="ovtop", horizontal=True, vertical_alignment="bottom",
                      gap="medium", wrap=False):
        st.html(title_html(ss.origin, horizon, len(snap), origins))
        render_horizon_toggle()
    with st.container(key="ovsit", horizontal=True, vertical_alignment="center",
                      gap="medium", wrap=False):
        render_week_stepper(origins)
        st.html(situation_html(snap, horizon, ss.origin, info))
    render_notices(snap, horizon, ss.origin)

    if ss.selected:
        map_col, drawer_col, list_col = st.columns(config.LAYOUT_OVERVIEW_DRAWER, gap="medium")
    else:
        (map_col, list_col), drawer_col = st.columns(config.LAYOUT_OVERVIEW, gap="medium"), None
    with map_col:
        with st.container(key="mapwrap"):
            render_map(snap, geojson, zooms, height=config.MAP_HEIGHT_OVERVIEW_PX,
                       key_prefix="map_overview")
            render_legend(snap, ss.layer)
    if drawer_col is not None:
        with drawer_col:
            render_city_drawer(snap, info, horizon)
    with list_col:
        render_city_list(snap, horizon)
    render_compare(snap, horizon)
