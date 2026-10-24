"""Session state: defaults, URL sync and the callbacks widgets share.

Keys (st.session_state):
    selected    adm3_pcode open in the city drawer, or None
    origin      forecast origin week (pandas.Timestamp, a Sunday)
    horizon     forecast week, an int in config.HORIZONS (1 = next week)
    layer       map layer ("Risk" | "Rainfall" | "Flood hazard")
    role        "Resident" | "Health office"
    user        signed-in display name (demo only), or None
    auth_view   "signin" | "signup" (landing card)
    loaded      True once the loading overlay has run this session
    map_version bumped to reset the map's click selection
    page        "Overview" | "Replay" | "Data reliability"
    map_view    "Philippines" | "Luzon" | "Visayas" | "Mindanao", or None to
                zoom to the selected city
    view_nonce  bumped by every view button, so re-clicking re-centres
    flood_alerts {adm3_pcode: forecast week} of Flood alerts switched on by a
                health office (session only, config.FLOOD_ALERT_WEEKS long)
"""

import pandas as pd
import streamlit as st

from app import config

# DEFAULTS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def init_auth_state():
    """Set the sign-in keys once per session (before any data is loaded).

    Returns
    -------
    None. New sessions start signed out on the landing screen.
    """
    ss = st.session_state
    ss.setdefault("user", None)
    ss.setdefault("role", config.DEFAULT_ROLE)
    ss.setdefault("auth_view", "signin")
    ss.setdefault("loaded", False)


def init_state(origins, city_codes):
    """Fill missing session keys from the URL, else from config defaults.

    Parameters
    ----------
    origins : list[pandas.Timestamp]
        Available origin weeks (sorted). Default origin = config.DEFAULT_ORIGIN.
    city_codes : iterable[str]
        Valid adm3_pcodes, used to reject a bad ?sel= value.

    Returns
    -------
    None. Mutates st.session_state once per session; later runs keep the
    user's choices.
    """
    if st.session_state.get("_initialised"):
        return
    qp = st.query_params
    codes = set(city_codes)
    ss = st.session_state
    ss.selected = qp.get("sel") if qp.get("sel") in codes else None
    ss.origin = snap_origin(qp.get("week"), origins) if origins else None
    ss.notice = range_notice(qp.get("week"), origins)
    ss.horizon = parse_horizon(qp.get("h"))
    ss.layer = config.MAP_LAYERS[0]
    ss.map_version = 0
    ss.map_view = None if ss.selected else config.DEFAULT_MAP_VIEW
    ss.view_nonce = 0
    ss.map_handled = ()
    # URL first, then a page already chosen this session, else the Overview.
    ss.page = next((p for p in (qp.get("page"), ss.get("page")) if p in config.PAGES),
                   config.PAGES[0])
    ss._initialised = True


def snap_origin(value, origins):
    """Turn any date-like value into the nearest available origin week.

    Parameters
    ----------
    value : str | date | Timestamp | None
        Requested date.
    origins : list[pandas.Timestamp]
        Available origins (sorted, non-empty).

    Returns
    -------
    pandas.Timestamp
        The latest origin on or before `value` (clamped to the first origin).
        None/unparseable -> config.DEFAULT_ORIGIN (snapped the same way).
    """
    try:
        ts = pd.Timestamp(value) if value is not None else None
    except (ValueError, TypeError):
        ts = None
    if ts is None or pd.isna(ts):
        ts = pd.Timestamp(config.DEFAULT_ORIGIN)
    earlier = [o for o in origins if o <= ts]
    return earlier[-1] if earlier else origins[0]


def range_notice(value, origins):
    """Explain why a requested week was moved to the nearest available one.

    Parameters
    ----------
    value : str | date | Timestamp | None
        Requested week (URL or date picker).
    origins : list[pandas.Timestamp]
        Available origins (sorted).

    Returns
    -------
    str | None
        A short message when `value` is before the first or after the last
        forecast week; None otherwise (or when nothing was requested).
    """
    try:
        ts = pd.Timestamp(value) if value is not None else None
    except (ValueError, TypeError):
        return "That date could not be read, so the default forecast week is shown."
    if ts is None or pd.isna(ts) or not origins:
        return None
    if ts < origins[0]:
        return (f"Forecasts start the week of {origins[0]:%b} {origins[0].day}, "
                f"{origins[0].year}, so that week is shown. Earlier weeks have no forecast "
                "the model had not already seen (it was tested on 2014–2022).")
    if ts > origins[-1] + pd.Timedelta(days=6):
        return (f"The data ends in 2022, so the last forecast week "
                f"({origins[-1]:%b} {origins[-1].day}, {origins[-1].year}) is shown.")
    return None


def parse_horizon(value):
    """Read a horizon from the URL: "1", "2" (or an old "Week 2" link).

    Parameters
    ----------
    value : str | int | None

    Returns
    -------
    int
        A member of config.HORIZONS; the first one when `value` is missing,
        unreadable or not shown.
    """
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    number = int(digits) if digits else None
    return number if number in config.HORIZONS else config.HORIZONS[0]


def horizon_number():
    """Return the selected horizon as an int.

    Returns
    -------
    int
        st.session_state.horizon when it is in config.HORIZONS, else the
        first horizon (1 = next week).
    """
    h = st.session_state.get("horizon")
    return h if h in config.HORIZONS else config.HORIZONS[0]


def share_params():
    """URL parameters that reproduce the current view.

    Returns
    -------
    dict[str, str]
        week (ISO date), h (horizon number), page (the open tab, so a
        reload or shared link lands on it) and sel when a city is open.
    """
    ss = st.session_state
    params = {"week": ss.origin.strftime("%Y-%m-%d"),
              "h": str(horizon_number()), "page": ss.get("page", config.PAGES[0])}
    if ss.selected:
        params["sel"] = ss.selected
    return params


def sync_query_params():
    """Write share_params() into the URL so the address bar is shareable.

    Returns
    -------
    None. Updates st.query_params only when something changed.
    """
    params = share_params()
    if dict(st.query_params) != params:
        st.query_params.from_dict(params)


# CALLBACKS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def select_city(pcode, from_map=False):
    """Open `pcode` in the city drawer (or close the drawer when None).

    Parameters
    ----------
    pcode : str | None
        City to select.
    from_map : bool
        True when the click came from the map itself; otherwise the map's
        own click selection is reset so it cannot re-select a stale city.

    Returns
    -------
    None
    """
    st.session_state.selected = pcode
    # Zoom to the new city; closing the drawer goes back to the whole country.
    st.session_state.map_view = None if pcode else config.DEFAULT_MAP_VIEW
    if not from_map:
        st.session_state.map_version += 1
        st.session_state.map_handled = ()


def set_map_view(name):
    """Show one of the quick map views (the city drawer stays open).

    Parameters
    ----------
    name : str
        A key of config.MAP_VIEWS.

    Returns
    -------
    None. Also bumps view_nonce so clicking the current view again
    re-centres a map the user has panned.
    """
    st.session_state.map_view = name
    st.session_state.view_nonce = st.session_state.get("view_nonce", 0) + 1


def step_origin(weeks, origins):
    """Move the origin week forward/back, clamped to available origins.

    Parameters
    ----------
    weeks : int
        +1 / -1.
    origins : list[pandas.Timestamp]

    Returns
    -------
    None
    """
    i = origins.index(st.session_state.origin) + weeks
    st.session_state.origin = origins[max(0, min(i, len(origins) - 1))]
    st.session_state.notice = None


def jump_to_case_study(origin, city, origins):
    """Jump to a case study on the Overview: set the week and open its city.

    Parameters
    ----------
    origin : str
        ISO date of the case-study origin week.
    city : str
        adm3_pcode to select.
    origins : list[pandas.Timestamp]
        Available origins; an origin outside them snaps to the nearest one
        and sets a notice saying so.

    Returns
    -------
    None
    """
    st.session_state.origin = snap_origin(origin, origins)
    st.session_state.horizon = config.HORIZONS[0]
    st.session_state.notice = range_notice(origin, origins)
    st.session_state.page = "Overview"
    select_city(city)


# FLOOD ALERT (session only) +++++++++++++++++++++++++++++++++++++++++++++++++

def flood_alert_start(pcode):
    """The forecast week a city's Flood alert was switched on for, or None.

    Parameters
    ----------
    pcode : str

    Returns
    -------
    pandas.Timestamp | None
        From st.session_state.flood_alerts ({pcode: week}); never saved
        beyond this session.
    """
    return st.session_state.get("flood_alerts", {}).get(pcode)


def toggle_flood_alert(pcode, week, key):
    """Switch a city's Flood alert on (from `week`) or off, as the toggle says.

    Parameters
    ----------
    pcode : str
    week : pandas.Timestamp
        The forecast week shown when the toggle was clicked.
    key : str
        Session key of the toggle (its new value: on / off).

    Returns
    -------
    None. Updates st.session_state.flood_alerts.
    """
    alerts = dict(st.session_state.get("flood_alerts", {}))
    if st.session_state.get(key):
        alerts[pcode] = pd.Timestamp(week)
    else:
        alerts.pop(pcode, None)
    st.session_state.flood_alerts = alerts
