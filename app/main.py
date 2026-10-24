"""LEAPto dashboard entry point.

    streamlit run main.py        (from the app folder)

Flow: landing / sign-in (demo only) -> wave loading overlay -> dashboard.
"""

import logging
import sys
from pathlib import Path

# This folder is the `app` package (its parent goes on sys.path) and also holds src/.
ROOT = Path(__file__).resolve().parent
for _p in (ROOT, ROOT.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import streamlit as st  # noqa: E402

from app import config  # noqa: E402

st.set_page_config(page_title="LEAPto: Leptospirosis risk",
                   page_icon=(str(config.STATIC_DIR / "mark.png")
                              if (config.STATIC_DIR / "mark.png").is_file() else None),
                   layout="wide", initial_sidebar_state="collapsed")

from app.components.auth import render_auth  # noqa: E402
from app.components.header import render_header  # noqa: E402
from app.components.loading import show_loading_while  # noqa: E402
from app.components.overview import render_overview  # noqa: E402
from app.components.reliability import render_reliability  # noqa: E402
from app.components.replay import render_replay  # noqa: E402
from app.components.ui import inject_css  # noqa: E402
from app.data import (city_names, data_status, load_alerts, load_geojson,  # noqa: E402
                      missing_runtime_files, origin_weeks, snapshot)
from app.state import (horizon_number, init_auth_state, init_state,  # noqa: E402
                       sync_query_params)

log = logging.getLogger("leapto")

# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def warm_caches():
    """Load everything the dashboard needs into st.cache_data.

    Returns
    -------
    None. Runs behind the loading overlay; later calls are cache hits.
    """
    load_alerts()
    load_geojson()
    data_status()  # loads every contract part
    for origin in origin_weeks()[-1:]:
        snapshot(origin, 1)


def render_fallback_warning():
    """Visible warning when the app's own pipeline stands in for model files.

    Returns
    -------
    None. Draws nothing when every observed-data part (cases, rainfall,
    flags, thresholds) comes from the modeling team or a labelled placeholder.
    """
    fallbacks = [row["label"] for row in data_status() if row["kind"] == "fallback"]
    if fallbacks:
        st.warning(f"Using the app's own data pipeline for: {', '.join(fallbacks)}. "
                   "The modeling team's files were not found, so these numbers may differ "
                   "from theirs. Run `python scripts/import_analysis_outputs.py` to fix this.",
                   icon=":material/warning:")


# PAGE +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def render_error(err):
    """Friendly error screen used instead of a Python traceback.

    Parameters
    ----------
    err : Exception
        The error raised while building the page.

    Returns
    -------
    None. Shows what to do next; technical details sit in a collapsed box.
    """
    if isinstance(err, FileNotFoundError):
        st.error(f"A data file is missing: {err}. Restore it from the repository, or rebuild "
                 "data/processed/ with `python scripts/build_processed.py` (see the README), "
                 "then reload.")
    else:
        st.error("Something went wrong while preparing the dashboard. Reload the page; if "
                 "it happens again, re-run the data pipeline (see README).")
    with st.expander("Technical details"):
        st.code(f"{type(err).__name__}: {err}", language=None)


def render_missing_files(missing):
    """Name every missing file and how to get it back, instead of a traceback.

    Parameters
    ----------
    missing : list[tuple[str, str]]
        missing_runtime_files output (path, fix).

    Returns
    -------
    None
    """
    st.error("The app cannot start: some of its files are missing.")
    for path, fix in missing:
        st.markdown(f"- `{path}`: {fix}")


def main():
    """Render the app, turning any unexpected data error into a message.

    Returns
    -------
    None. Streamlit's own rerun/stop signals are BaseException subclasses,
    so they pass through this guard untouched.
    """
    missing = missing_runtime_files()
    if missing:
        render_missing_files(missing)
        return
    try:
        render_app()
    except Exception as err:  # noqa: BLE001 - last-resort UI guard, logged below
        log.exception("dashboard failed")
        render_error(err)


def render_app():
    """Render landing, loading or the dashboard depending on session state.

    Returns
    -------
    None. Stops early with a clear message if no forecast source is usable.
    """
    inject_css()
    init_auth_state()
    ss = st.session_state
    if ss.user is None:
        render_auth()
        return
    if not ss.loaded:
        show_loading_while(warm_caches)
        ss.loaded = True

    _, info = load_alerts()
    origins = origin_weeks()
    init_state(origins, city_names())
    if not origins:
        st.error("No forecasts are available: `data/model_outputs/alerts.csv` is missing or "
                 "unreadable. Restore it from the repository, run `python "
                 "scripts/import_analysis_outputs.py` to import the modeling team's alerts, or "
                 "`python scripts/make_baseline_forecast.py` to create the placeholder.")
        st.caption(info["reason"])
        return

    horizon = horizon_number()
    snap = snapshot(ss.origin, horizon)
    geojson, zooms = load_geojson()

    page = render_header()
    render_fallback_warning()

    if page == "Overview":
        render_overview(snap, horizon, info, origins, geojson, zooms)
    elif page == "Replay":
        render_replay(origins)
    else:
        render_reliability(horizon)

    sync_query_params()


main()
