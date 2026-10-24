"""The city drawer (DESIGN_V3 §1): a right-hand column on the Overview.

Opened by clicking a city in the list or on the map. Top to bottom:
    1. Name, province and confidence note (two lines), level badge (+ "Flood alert" chip), close;
       health offices get a Flood alert toggle (config.FLOOD_ALERT_WEEKS weeks,
       session only; adds flood actions, never changes the level)
    2. Meaning sentence on a tint of the level's colour (+ one SEEN reason);
       Davao-like cities (config.WATCH_BACKGROUND_CITIES) add how often they
       are at Watch
    3. Tiles: "Rain last week" and "Cases, latest week" ("Unusual at N or more")
    4. Rain and risk, last 6 weeks + forecast (mini chart with a level strip)
    5. Do now: 2-3 actions for level x role, each with "because"
    6. Focus barangays: top 3 by Project NOAH high flood-hazard share
    7. Download city brief
then a collapsed "More details": every reason with its source, the larger
rain -> risk chart, reported cases vs the outbreak line, the other flood-
prone barangays, every suggested action and the track record.
Forecasts, observed data and suggested actions carry distinct tags.
"""

import pandas as pd
import streamlit as st

from app import config
from app.components.city_chart import mini_risk_figure, rain_risk_figure, rainfall_cases_figure
from app.components.ui import esc, fmt_count, fmt_span, level_badge, level_color
from app.content.actions import flood_actions, select_actions
from app.data import (case_signal, level_text, load_alerts, load_flood_rank, load_lag_curve,
                      load_processed, load_thresholds, snapshot_reasons)
from app.logic.reasons import headline_reason
from app.state import flood_alert_start, select_city, toggle_flood_alert
from src.brief import build_city_brief
from src.views import (city_horizons, city_timeseries, flood_alert_weeks_left, heavy_rain_mm,
                       lag_caption, level_sentence, peak_caption, place_label, risk_timeline,
                       top_flood_barangays, watch_weeks_per_year)

TAGS = {
    "forecast": '<span class="leap-tag leap-tag-forecast">FORECAST</span>',
    "observed": '<span class="leap-tag leap-tag-observed">OBSERVED</span>',
    "seen": '<span class="leap-tag leap-tag-observed">SEEN</span>',
    "action": '<span class="leap-tag leap-tag-action">SUGGESTED</span>',
}
# Reasons already said elsewhere in the drawer (meaning sentence / header).
SAID_ABOVE = ("case_signal", "lower_confidence")


# HTML PIECES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def place_city(r):
    """Short city name for sentences: "Davao City" -> "Davao".

    Parameters
    ----------
    r : pandas.Series
        Snapshot row (city_name).

    Returns
    -------
    str
    """
    name = str(r.city_name)
    return name[:-len(" City")] if name.endswith(" City") else name


def heading(title, sub="", tag=""):
    """A drawer section heading with an optional one-line explanation.

    Parameters
    ----------
    title : str
    sub : str
    tag : str
        Optional TAGS entry shown beside the title.

    Returns
    -------
    str
    """
    sub_html = f'<div class="leap-dsub">{esc(sub)}</div>' if sub else ""
    return f'<div class="leap-dh">{esc(title)}{tag}</div>{sub_html}'


def header_html(r):
    """Name, then the province and the confidence note on two lines.

    Parameters
    ----------
    r : pandas.Series
        Snapshot row.

    Returns
    -------
    str
    """
    note = config.CONFIDENCE_NOTES.get(r.confidence, config.CONFIDENCE_NOTES["standard"])
    return (f'<div class="leap-dname">{esc(r.city_name)}</div>'
            f'<div class="leap-dnote">{esc(place_label(r.province))}</div>'
            f'<div class="leap-dnote">{esc(note)}</div>')


def meaning_html(r, sentence, reason):
    """The meaning sentence on a tint of the level colour, plus one SEEN line.

    Parameters
    ----------
    r : pandas.Series
        Snapshot row (alert_level).
    sentence : str
        src.views.level_sentence output.
    reason : Reason | None
        One signal seen in the data (not repeated from the header).

    Returns
    -------
    str
    """
    seen = (f'<div class="leap-dseen">{TAGS["seen"]}{esc(reason.text)}</div>'
            if reason else "")
    return (f'<div class="leap-dmeaning" style="--level:{level_color(r.alert_level)}">'
            f'{TAGS["forecast"]}{esc(sentence)}{seen}</div>')


def tiles_html(r):
    """ "Rain last week" and "Cases, latest week" tiles.

    Parameters
    ----------
    r : pandas.Series
        Snapshot row (rain_week_mm, rain_status, cases_week, latest_cases,
        latest_flag, unusual_at).

    Returns
    -------
    str
        Missing values read "–" with a short reason.
    """
    # Rain is known one week later than cases (the reporting delay).
    rain_week = pd.Timestamp(r.cases_week) + pd.Timedelta(weeks=config.CASES_REPORT_DELAY_WEEKS)
    has_rain = not pd.isna(r.rain_week_mm)
    rain_value = f"{r.rain_week_mm:.0f} mm" if has_rain else "–"
    rain_sub = (r.rain_status or "No usual to compare") if has_rain else "No rainfall data"
    n, line = r.latest_cases, r.unusual_at
    if r.latest_flag:
        case_sub = "Week flagged as non-reporting"
    elif pd.isna(line):
        case_sub = "No outbreak line for this week"
    else:
        case_sub = f"Unusual at {int(line)} or more"
    unusual = not pd.isna(n) and not pd.isna(line) and not r.latest_flag and n >= line
    flag_cls = " leap-dtile-alert" if unusual else ""
    return (f'<div class="leap-ptiles">'
            f'<div class="leap-ptile"><div class="leap-tile-label">Rain last week</div>'
            f'<div class="leap-tile-value">{esc(rain_value)}</div>'
            f'<div class="leap-tile-sub">{esc(rain_sub)}</div>'
            f'<div class="leap-dtile-date">{esc(fmt_span(rain_week))}</div>'
            f'<div class="leap-dtile-date">NASA IMERG</div></div>'
            f'<div class="leap-ptile{flag_cls}"><div class="leap-tile-label">Cases, latest '
            f'week</div><div class="leap-tile-value">{esc(fmt_count(n))}</div>'
            f'<div class="leap-tile-sub">{esc(case_sub)}</div>'
            f'<div class="leap-dtile-date">{esc(fmt_span(r.cases_week))}</div>'
            f'<div class="leap-dtile-date">Reports arrive a week late</div></div></div>')


def flood_chip_html(weeks_left):
    """The "Flood alert" chip shown beside the level while an alert is on.

    Parameters
    ----------
    weeks_left : int
        flood_alert_weeks_left output (0 = off).

    Returns
    -------
    str
        "" when off.
    """
    if not weeks_left:
        return ""
    left = "1 week left" if weeks_left == 1 else f"{weeks_left} weeks left"
    return f'<span class="leap-flood-chip">Flood alert: {left}</span>'


def actions_html(actions):
    """Suggested actions, each with its "because".

    Parameters
    ----------
    actions : list[dict]

    Returns
    -------
    str
    """
    items = "".join(f'<li>{esc(a["text"])}<small>Because {esc(a["because"])}.</small></li>'
                    for a in actions)
    return f'<ul class="leap-actions">{items}</ul>'


def barangays_html(barangays, start=1):
    """Ranked flood-prone barangays: "1  Name ....... 78% of area".

    Parameters
    ----------
    barangays : pandas.DataFrame
        src.views.top_flood_barangays rows (brgy_name, high_hazard_pct).
    start : int
        Rank of the first row.

    Returns
    -------
    str
    """
    if barangays.empty:
        return '<div class="leap-panel-note">No barangay flood-hazard data for this city.</div>'
    rows = "".join(
        f'<div class="leap-dbrgy"><span class="leap-dbrgy-rank">{i}</span>'
        f'<span class="leap-brgy-name" title="{esc(b.brgy_name)}">{esc(b.brgy_name)}</span>'
        f'<span class="leap-dbrgy-pct">{b.high_hazard_pct:.0f}% of area</span></div>'
        for i, b in enumerate(barangays.itertuples(), start))
    return f'<div class="leap-dbrgys">{rows}</div>'


def reasons_html(reasons, level):
    """Every reason with its source, plus an honest note for Normal cities.

    Parameters
    ----------
    reasons : list[Reason]
    level : str

    Returns
    -------
    str
        A "no clear signal" line when the list is empty.
    """
    if not reasons:
        return '<div class="leap-reason">No clear signal in the data we have for this week.</div>'
    rows = "".join(f'<div class="leap-reason">{esc(r.text)}'
                   f'<small>Source: {esc(r.source)}</small></div>' for r in reasons)
    signals = {r.kind for r in reasons} & {"heavy_rain", "cases"}
    if level == "Normal" and signals:
        rows += ('<div class="leap-reason-note">The model still puts this city at Normal: '
                 'these signals alone were not enough to raise the chance of an outbreak '
                 'week.</div>')
    return rows


def _open_reliability():
    """Close the drawer and switch to the Data reliability page.

    Returns
    -------
    None
    """
    st.session_state.page = "Data reliability"
    select_city(None)


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def render_city_drawer(snap, info, horizon):
    """Draw the drawer for st.session_state.selected.

    Parameters
    ----------
    snap : pandas.DataFrame
        Current src.views snapshot.
    info : dict
        Alerts source info (kind, model_version) for the brief.
    horizon : int
        The forecast week shown (config.HORIZONS).

    Returns
    -------
    None. Shows a short message if the city has no row.
    """
    ss = st.session_state
    rows = snap[snap.adm3_pcode == ss.selected]
    if rows.empty:
        st.write("This city is not in the current forecast.")
        return
    r = rows.iloc[0]
    alerts, _ = load_alerts()
    data = load_processed()
    levels = level_text(horizon)
    level = levels[r.alert_level]
    signal = case_signal()
    reasons = snapshot_reasons(ss.origin, horizon).get(r.adm3_pcode, [])
    flood = top_flood_barangays(load_flood_rank(), r.adm3_pcode)
    names = flood.brgy_name.tolist()
    actions = select_actions(r.alert_level, ss.role, horizon, reasons, names)
    lag = load_lag_curve()[0]
    when = config.HORIZON_NAMES.get(horizon, f"In {horizon} weeks").lower()
    target = ss.origin + pd.Timedelta(weeks=horizon - 1)
    weeks_left = flood_alert_weeks_left(flood_alert_start(r.adm3_pcode), target)
    flood_todo = flood_actions(names) if weeks_left else []

    with st.container(key="panel"):
        # 1. Header
        with st.container(key="dhead", horizontal=True, vertical_alignment="top", wrap=False):
            st.html(header_html(r))
            st.html(f'<div class="leap-dbadges">{level_badge(r.alert_level)}'
                    f'{flood_chip_html(weeks_left)}</div>', width="content")
            st.button("", icon=":material/close:", key="close_panel", on_click=select_city,
                      args=(None,), help="Close")
        if ss.role == config.FLOOD_ALERT_ROLE:
            key = f"flood_{r.adm3_pcode}_{target:%Y%m%d}"
            st.toggle("Flood alert", value=bool(weeks_left), key=key,
                      on_change=toggle_flood_alert, args=(r.adm3_pcode, target, key),
                      help=f"Switch on after a major flood. Lasts {config.FLOOD_ALERT_WEEKS} weeks "
                           "from this forecast week and adds flood actions. The forecast level "
                           "does not change.")

        # 2. Meaning
        sentence = level_sentence(r.alert_level, level, r.outbreak_prob, r.unusual_at)
        seen = headline_reason([x for x in reasons if x.kind not in SAID_ABOVE])
        st.html(meaning_html(r, sentence, seen))
        if r.adm3_pcode in config.WATCH_BACKGROUND_CITIES:
            n = watch_weeks_per_year(alerts, r.adm3_pcode, horizon)
            if not pd.isna(n):
                st.html('<div class="leap-dnote leap-dbackground">'
                        + esc(config.WATCH_BACKGROUND_TEXT.format(city=place_city(r), n=round(n)))
                        + '</div>')

        # 3. Tiles
        st.html(tiles_html(r))

        # 4. Rain and risk, last 6 weeks + forecast
        heavy = heavy_rain_mm(data["rain_weekly"], r.adm3_pcode)
        mini = risk_timeline(data["rain_weekly"], alerts, r.adm3_pcode, ss.origin,
                             level["base_rate"], weeks_back=config.DRAWER_PAST_WEEKS,
                             heavy_mm=heavy, case_signal=signal)
        st.html(heading(f"Rain and risk, last {config.DRAWER_PAST_WEEKS} weeks + forecast"))
        st.plotly_chart(mini_risk_figure(mini), key="mini_chart", theme=None,
                        config={"displayModeBar": False})
        st.html(f'<div class="leap-panel-sub">{esc(peak_caption(lag))} Bars: rain (dark = '
                f'this city\'s wettest 5% of weeks). Strip: the level shown each week; '
                f'outlined = forecast.</div>')

        # 5. Do now (Flood alert actions first while one is on)
        if flood_todo:
            st.html(heading("Flood alert: do now", "Switched on by the health office; the "
                            "forecast level above is unchanged.", TAGS["action"])
                    + actions_html(flood_todo))
        st.html(heading("Do now", f"For: {ss.role} (change in your account menu). "
                                  f"Forecast for {when}.", TAGS["action"])
                + actions_html(actions[:config.DRAWER_ACTIONS]))

        # 6. Focus barangays
        st.html(heading("Focus barangays", "Largest share of area at high flood hazard "
                                           "(Project NOAH, 100-year flood)")
                + barangays_html(flood.head(config.DRAWER_BARANGAYS)))

        # 7. Download city brief
        source = (f"Model: {info['model_version']}" if info["kind"] == "model"
                  else config.BASELINE_BANNER)
        brief = build_city_brief(r.to_dict(),
                                 city_horizons(alerts, r.adm3_pcode, ss.origin, signal,
                                               config.HORIZONS),
                                 flood_todo + actions, role=ss.role, origin_week=ss.origin,
                                 source_label=source, levels=levels, horizon=horizon,
                                 barangays=flood, lag_text=lag_caption(lag), reasons=reasons)
        st.download_button("Download city brief", data=brief.encode("utf-8"),
                           file_name=f"leapto_brief_{r.city_name.replace(' ', '_')}_"
                                     f"{ss.origin:%Y-%m-%d}.md",
                           mime="text/markdown", icon=":material/download:",
                           type="primary", key="brief", on_click="ignore", width="stretch")

        with st.expander("More details", key="more_details"):
            render_more_details(r, alerts, data, level, reasons, flood, actions, lag, heavy,
                                signal)


def render_more_details(r, alerts, data, level, reasons, flood, actions, lag, heavy, signal):
    """The drawer's collapsed "More details" section.

    Parameters
    ----------
    r : pandas.Series
        Snapshot row.
    alerts : pandas.DataFrame
    data : dict
        app.data.load_processed output.
    level : dict
        level_text(horizon)[r.alert_level].
    reasons : list[Reason]
    flood : pandas.DataFrame
        Top flood-prone barangays (all ranks kept).
    actions : list[dict]
        Every suggested action for this city.
    lag : pandas.DataFrame
        lag_response.csv.
    heavy : float
        The city's heavy-rain line (mm).
    signal : frozenset[str]
        Case-signal cities.

    Returns
    -------
    None
    """
    ss = st.session_state
    st.html(heading("Why this level", "What we're seeing in the data. These signals fit the "
                    "forecast; they are not a full explanation of the model.", TAGS["seen"])
            + reasons_html(reasons, r.alert_level))

    timeline = risk_timeline(data["rain_weekly"], alerts, r.adm3_pcode, ss.origin,
                             level["base_rate"], heavy_mm=heavy, case_signal=signal)
    st.html(heading("Rain and risk compared with a usual week", lag_caption(lag)))
    st.plotly_chart(rain_risk_figure(timeline, heavy), key="rain_risk", theme=None,
                    config={"displayModeBar": False})
    st.html('<div class="leap-panel-sub">Bars: OBSERVED weekly rain, last 10 weeks; dark bars '
            'are this city\'s heaviest rain weeks. Line: FORECAST chance of an outbreak week '
            'compared with a usual week.</div>')

    st.html(heading("Reported cases vs outbreak line", "Observed: cases reported each week "
                    "(DOH PIDSR). A week above the red line counts as an outbreak week.",
                    TAGS["observed"]))
    series = city_timeseries(data["cases"], data["rain_weekly"], load_thresholds(),
                             r.adm3_pcode, ss.origin, weeks_ahead=len(config.HORIZONS))
    st.plotly_chart(rainfall_cases_figure(series, ss.origin, show_rain=False),
                    key="cases_chart", theme=None, config={"displayModeBar": False})

    more = flood.iloc[config.DRAWER_BARANGAYS:]
    if not more.empty:
        share = (f" {r.hazard_pct:.0f}% of the whole city is high flood hazard."
                 if not pd.isna(r.hazard_pct) else "")
        st.html(heading("More flood-prone barangays", "Next in line for advisories and "
                        "doxycycline PEP." + share)
                + barangays_html(more, start=config.DRAWER_BARANGAYS + 1))

    if len(actions) > config.DRAWER_ACTIONS:
        st.html(heading("More suggested actions", tag=TAGS["action"])
                + actions_html(actions[config.DRAWER_ACTIONS:]))

    track = ""
    if level["track"]:
        track = f'<div class="leap-reason">{esc(level["track"])}</div>'
    st.html(heading("How reliable is this", "How often this level was right in testing "
                    "(2014–2022), and what limits this forecast.") + track
            + '<div class="leap-reason-note">The cases tile shows the latest reported week: '
              'reports arrive about a week late, so the forecast uses cases up to two weeks '
              'before the forecast week.</div>')
    st.button("See how reliable the forecasts are", key="open_reliability",
              on_click=_open_reliability, icon=":material/insights:", type="tertiary")
