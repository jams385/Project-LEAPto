"""Forecast controls on the Overview: the horizon toggle ("Next week (Oct
23–29)" / "In 2 weeks (Oct 30–Nov 5)") and the week stepper (◀, date, ▶).

The data end in 2022, so the forecast week is always chosen here; the app
never assumes today's date. Case studies live on the Replay page.
"""

import pandas as pd
import streamlit as st

from app import config
from app.components.ui import fmt_span
from app.state import range_notice, snap_origin, step_origin

# CALLBACKS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _on_pick_origin(key, origins):
    """Snap a picked date to the nearest available origin week.

    Parameters
    ----------
    key : str
        Session key of the date_input that changed.
    origins : list[pandas.Timestamp]

    Returns
    -------
    None
    """
    st.session_state.origin = snap_origin(st.session_state[key], origins)
    st.session_state.notice = range_notice(st.session_state[key], origins)


# DATES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def target_week(origin, horizon):
    """First day of the forecast week for a horizon.

    Parameters
    ----------
    origin : pandas.Timestamp
        Forecast origin (Sunday); horizon 1 is the week that starts on it.
    horizon : int

    Returns
    -------
    pandas.Timestamp
    """
    return pd.Timestamp(origin) + pd.Timedelta(weeks=horizon - 1)


def horizon_label(horizon, origin):
    """Toggle text: "Next week (Oct 23–29)".

    Parameters
    ----------
    horizon : int
        A member of config.HORIZONS.
    origin : pandas.Timestamp

    Returns
    -------
    str
    """
    name = config.HORIZON_NAMES.get(horizon, f"In {horizon} weeks")
    return f"{name} ({fmt_span(target_week(origin, horizon), year=False)})"


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def render_horizon_toggle():
    """The forecast-week toggle, one button per config.HORIZONS entry.

    Returns
    -------
    None. Writes st.session_state.horizon (an int).
    """
    origin = st.session_state.origin
    with st.container(key="htoggle", width="content"):
        st.segmented_control("Forecast week", config.HORIZONS, key="horizon", required=True,
                             label_visibility="collapsed",
                             format_func=lambda h: horizon_label(h, origin))


def render_week_stepper(origins):
    """◀ / ▶ one week and a date picker for the week the forecast is made.

    Parameters
    ----------
    origins : list[pandas.Timestamp]
        Available origin weeks (sorted, non-empty).

    Returns
    -------
    None. Writes st.session_state.origin via callbacks.
    """
    ss = st.session_state
    first, last = origins[0], origins[-1]
    with st.container(key="fbar", horizontal=True, vertical_alignment="center",
                      width="content"):
        st.html('<div class="leap-fc-label"><span>WEEK OF</span></div>', width="content")
        st.button("", icon=":material/chevron_left:", key="step_back", on_click=step_origin,
                  args=(-1, origins), disabled=ss.origin <= first, help="One week earlier")
        key = f"origin_picker_{ss.origin:%Y%m%d}"
        st.date_input("Forecast made in the week of", value=ss.origin.date(),
                      min_value=first.date(), max_value=last.date(), key=key,
                      on_change=_on_pick_origin, args=(key, origins), format="YYYY-MM-DD",
                      width=130, label_visibility="collapsed",
                      help=(f"Pick any week from {first:%b} {first.day}, {first.year} to "
                            f"{last:%b} {last.day}, {last.year}. It snaps to the Sunday that "
                            "starts the week."))
        st.button("", icon=":material/chevron_right:", key="step_fwd", on_click=step_origin,
                  args=(1, origins), disabled=ss.origin >= last, help="One week later")
