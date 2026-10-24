"""The Replay tab (DESIGN_V3 §2): step through a past outbreak, week by week.

An "Outbreak event" dropdown (Navotas 2018, Typhoon Washi, Iloilo 2011-12), play / step
controls and a week slider, then three aligned panels on one time axis (rain,
reported cases, the level the app would have shown) and a "What happened"
card whose entries are computed from the data (src/replay.py, wording in
app/content/replay_text.py).

Only out-of-sample forecasts are shown: the modeling team's stage 6 "as of
then" fits, trained on earlier years and retrained each January. Washi and
Iloilo are before the Overview's 2014-2022 forecasts, so they come from the
same stage 6 fits, not from alerts.csv, and say so.
"""

import time

import pandas as pd
import streamlit as st

from app import config
from app.components.city_chart import replay_panels_figure
from app.components.ui import esc, level_badge
from app.content.replay_text import (BEFORE_2014, RAIN_NOTE, entry_text, span,
                                     summary_text)
from app.data import city_total_cases, load_rain_late, load_replay
from app.state import jump_to_case_study, select_city
from src.replay import panel_window, season_table, what_happened

# STATE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def week_key(season):
    """Session key holding a season's selected week.

    Parameters
    ----------
    season : dict
        A config.REPLAY_SEASONS entry.

    Returns
    -------
    str
    """
    return f"replay_week_{season['event']}"


def step_week(key, weeks, delta):
    """Move a season's selected week by `delta` weeks, clamped to the season.

    Parameters
    ----------
    key : str
        Session key of the selected week (week_key).
    weeks : list[pandas.Timestamp]
        Every week of the season, sorted.
    delta : int

    Returns
    -------
    None. Stops playback too, so a manual step is never overridden.
    """
    ss = st.session_state
    i = weeks.index(ss[key]) + delta
    ss[key] = weeks[max(0, min(i, len(weeks) - 1))]
    if ss.get("replay_playing"):       # the timer is removed by a full run
        ss.replay_playing = False
        ss.replay_full_rerun = True


def toggle_play(key, weeks):
    """Start or stop playback (starting from the end restarts at the first week).

    Parameters
    ----------
    key : str
        Session key of the selected week.
    weeks : list[pandas.Timestamp]

    Returns
    -------
    None
    """
    ss = st.session_state
    ss.replay_playing = not ss.get("replay_playing", False)
    if ss.replay_playing and ss[key] == weeks[-1]:
        ss[key] = weeks[0]
    ss.replay_last = time.time()
    ss.replay_full_rerun = True    # the timer is set up by a full run


def _season_changed():
    """Stop playback when another season is picked.

    Returns
    -------
    None
    """
    st.session_state.replay_playing = False


def advance_if_due(key, weeks, now=None):
    """While playing, move to the next week once per config.REPLAY_PLAY_SECONDS.

    Parameters
    ----------
    key : str
        Session key of the selected week.
    weeks : list[pandas.Timestamp]
    now : float | None
        Current time (time.time() if None; a parameter for tests).

    Returns
    -------
    bool
        True when playback just reached the last week (and stopped).
    """
    ss = st.session_state
    if not ss.get("replay_playing"):
        return False
    now = time.time() if now is None else now
    if now - ss.get("replay_last", 0) < 0.8 * config.REPLAY_PLAY_SECONDS:
        return False
    ss.replay_last = now
    i = weeks.index(ss[key])
    if i + 1 < len(weeks):
        ss[key] = weeks[i + 1]
    if ss[key] == weeks[-1]:
        ss.replay_playing = False
        return True
    return False


# HTML +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def entries_html(entries, selected):
    """The dated "What happened" list; entries after the selected week are faded.

    Parameters
    ----------
    entries : list[dict]
        src.replay.what_happened entries.
    selected : pandas.Timestamp
        The forecast week shown.

    Returns
    -------
    str
    """
    rows = []
    for e in entries:
        title, body = entry_text(e)
        later = " leap-wh-later" if pd.Timestamp(e["week"]) > pd.Timestamp(selected) else ""
        rows.append(
            f'<div class="leap-wh{later}"><i style="background:{config.REPLAY_DOT_COLORS[e["kind"]]}">'
            f'</i><div><div class="leap-wh-date">{esc(span(e["week"]))}</div>'
            f'<div class="leap-wh-title">{esc(title)}</div>'
            f'<div class="leap-wh-text">{esc(body)}</div></div></div>')
    return "".join(rows)


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _replay_body(table, season, origins):
    """The part of the tab that updates on its own while playing (a fragment).

    Parameters
    ----------
    table : pandas.DataFrame
        src.replay.season_table output.
    season : dict
        A config.REPLAY_SEASONS entry.
    origins : list[pandas.Timestamp]
        Overview weeks with a forecast (for the "Open this week" button).

    Returns
    -------
    None
    """
    ss = st.session_state
    weeks = list(table.week_start)
    key = week_key(season)
    if ss.pop("replay_full_rerun", False):
        st.rerun()
    ss.setdefault(key, weeks[0])
    if advance_if_due(key, weeks):
        st.rerun()
    selected = ss[key]
    row = table[table.week_start == selected].iloc[0]
    entries, summary = what_happened(table, city_total_cases(season["city"]))

    left, right = st.columns([2.1, 1], gap="medium")
    with left, st.container(key="replaycard"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.button("", icon=":material/pause:" if ss.get("replay_playing")
                      else ":material/play_arrow:", key="replay_play", on_click=toggle_play,
                      args=(key, weeks), help="Pause" if ss.get("replay_playing") else "Play")
            st.button("", icon=":material/chevron_left:", key="replay_back", on_click=step_week,
                      args=(key, weeks, -1), disabled=selected == weeks[0], help="Previous week")
            st.button("", icon=":material/chevron_right:", key="replay_fwd", on_click=step_week,
                      args=(key, weeks, 1), disabled=selected == weeks[-1], help="Next week")
            st.html(f'<div class="leap-replay-showing">Showing the forecast for '
                    f'<b>{esc(span(selected))}</b></div>', width="content")
            st.html(level_badge(row.level_1 or config.NO_FORECAST_LEVEL), width="content")
        st.select_slider("Week", options=weeks, key=key, format_func=lambda d: f"{d:%b} {d.day}",
                         label_visibility="collapsed")
        window = table[table.week_start.isin(panel_window(weeks, selected))]
        st.plotly_chart(replay_panels_figure(window, selected), key="replay_panels", theme=None,
                        config={"displayModeBar": False})
        notes = [RAIN_NOTE] + ([BEFORE_2014] if season["event"] in config.REPLAY_THREE_YEAR_EVENTS
                               else [])
        st.html('<div class="leap-panel-sub">' + esc(" ".join(notes)) + "</div>")
        if pd.Timestamp(selected) in set(origins):
            st.button("Open this week on the Overview", key="replay_open",
                      on_click=jump_to_case_study, args=(selected, season["city"], origins),
                      type="tertiary", icon=":material/arrow_forward:", icon_position="right")
    with right, st.container(key="whathappened"):
        st.html('<div class="leap-card-title">What happened</div>'
                f'<div class="leap-card-sub">{esc(season["title"])}. Computed from the data.'
                '</div>' + entries_html(entries, selected)
                + f'<div class="leap-wh-summary">{esc(summary_text(summary))}</div>')
        if season.get("flood_alert"):
            st.button("About the Flood alert", key="replay_flood", on_click=_flood_alert,
                      args=(season,), type="tertiary", icon=":material/flood:",
                      icon_position="right")


def _flood_alert(season):
    """Open the season's city on the Overview and say where the Flood alert is.

    Parameters
    ----------
    season : dict
        A config.REPLAY_SEASONS entry.

    Returns
    -------
    None
    """
    select_city(season["city"])
    st.session_state.page = "Overview"
    st.session_state.notice = (
        f"The Flood alert is a switch in the city drawer for {config.FLOOD_ALERT_ROLE.lower()} "
        f"users (account menu → I am a: {config.FLOOD_ALERT_ROLE}). It lasts "
        f"{config.FLOOD_ALERT_WEEKS} weeks and never changes the forecast level.")


def render_replay(origins):
    """Draw the Replay tab.

    Parameters
    ----------
    origins : list[pandas.Timestamp]
        Overview weeks with a forecast.

    Returns
    -------
    None. Shows what to run when replay_weekly.csv is missing.
    """
    ss = st.session_state
    replay, info = load_replay()
    rain = load_rain_late()
    if replay.empty or "rain_mm_7d_late" not in rain:
        st.html('<div class="leap-page-h">Replay</div><div class="leap-coming">The Replay needs '
                "the modeling team's case-study forecasts (replay_weekly.csv) and IMERG Late "
                "rain. Run <code>python scripts/import_analysis_outputs.py</code>.</div>")
        return
    seasons = config.REPLAY_SEASONS
    with st.container(horizontal=True, vertical_alignment="bottom", wrap=False):
        title = st.empty()
        picked = st.selectbox("Outbreak event", range(len(seasons)), key="replay_season",
                              format_func=lambda i: seasons[i]["label"],
                              on_change=_season_changed, width=380)
        season = seasons[picked or 0]
        title.html(f'<div><div class="leap-page-h">{esc(season["title"])}</div>'
                   f'<div class="leap-page-sub">{esc(config.REPLAY_SUBTITLE)}</div></div>')
    table = season_table(replay, rain, season)
    if table.empty:
        st.html('<div class="leap-coming">No forecasts for this outbreak event in replay_weekly.csv.</div>')
        return
    playing = ss.get("replay_playing", False)
    st.fragment(run_every=config.REPLAY_PLAY_SECONDS if playing else None)(_replay_body)(
        table, season, origins)
