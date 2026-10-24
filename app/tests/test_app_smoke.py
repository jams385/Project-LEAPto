"""End-to-end smoke tests of the Streamlit app (no browser) via AppTest.

Each edge case must render a message, never raise or show a traceback.
The Overview follows docs/DESIGN_V3.md: title + dated sub-line, situation
line, map, "All covered cities", and the city drawer as a right-hand column.
"""

from pathlib import Path

import shutil

import pandas as pd

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import config
from app.components.forecast_bar import horizon_label

APP = str(Path(__file__).resolve().parents[1] / "main.py")
TIMEOUT = 60
CITIES = ["PH015518000", "PH034919000", "PH050506000", "PH063022000", "PH072230000",
          "PH083747000", "PH097332000", "PH104305000", "PH112402000", "PH137401000",
          "PH137503000", "PH137603000"]


# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def run_app(signed_in=True, role=None, **query):
    """Run app/main.py once, optionally signed in and with URL query params.

    Parameters
    ----------
    signed_in : bool
        Pre-set a demo user and skip the loading overlay.
    role : str | None
        Pre-set the role ("Resident" / "Health office").
    **query : str
        URL parameters (city, week, h, sel).

    Returns
    -------
    AppTest
        The finished run.
    """
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    if signed_in:
        at.session_state["user"] = "Tester"
        at.session_state["loaded"] = True
    if role:
        at.session_state["role"] = role
    for key, value in query.items():
        at.query_params[key] = value
    return at.run()


def assert_clean(at):
    """Fail if the run raised or showed an error box.

    Parameters
    ----------
    at : AppTest

    Returns
    -------
    None
    """
    assert not at.exception
    assert not at.error, [e.value for e in at.error]


def html_text(at):
    """All st.html bodies of a run joined into one string (for assertions).

    Parameters
    ----------
    at : AppTest

    Returns
    -------
    str
    """
    return " ".join(getattr(el.proto, "body", "") for el in at.get("html"))


def drawer_open(at):
    """Whether the city drawer is on screen.

    Parameters
    ----------
    at : AppTest

    Returns
    -------
    bool
    """
    return any(b.key == "close_panel" for b in at.button)


@pytest.fixture(autouse=True)
def fresh_caches():
    """Clear st.cache_data so a monkeypatched path is really re-read."""
    st.cache_data.clear()
    yield
    st.cache_data.clear()


# Removed by SPEC_V2 §2 / DESIGN_V3: none of these may appear anywhere.
RETIRED_TEXT = ("Risk score", "Est. cases", "of 100", "VERY HIGH", "MODERATE", "Wk 4",
                "Week 4", "next 4 weeks", "Limited data", "Get alerts", "Weekly bulletin",
                "Cities that need attention", "View details")


def assert_no_retired_text(at):
    """Fail if any retired score / case-count / tier / v2 wording is rendered.

    Parameters
    ----------
    at : AppTest

    Returns
    -------
    None
    """
    text = html_text(at) + " ".join(str(b.label) for b in at.button)
    for retired in RETIRED_TEXT:
        assert retired not in text, retired


# OVERVIEW +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_landing_renders_signed_out():
    at = run_app(signed_in=False)
    assert_clean(at)
    assert "Welcome back" in html_text(at)


def test_overview_title_dates_and_honesty_note():
    at = run_app(week="2022-10-23", city="PH063022000")
    assert_clean(at)
    text = html_text(at)
    assert config.OVERVIEW_TITLE in text
    # Dates come from the selected week, never from today.
    assert "Forecast for <b class=\"leap-date\">Oct 23–29, 2022</b>" in text
    assert "Rain data to <b class=\"leap-date\">Oct 22, 2022</b>" in text
    assert "Cases to <b class=\"leap-date\">Oct 15, 2022</b>" in text
    assert "Past data, 2008–2022" in text
    assert "from Dec 29, 2013 to Dec 31, 2022" in text          # hover note
    assert "Next week (<b>Oct 23–29, 2022</b>):" in text and "at Warning" in text
    assert "Forecast, not confirmed cases" in text and "Data 2008–2022" in text
    assert "·" not in text
    assert at.session_state["page"] == "Overview" and not drawer_open(at)
    assert_no_retired_text(at)


def test_city_list_sorted_by_level_with_notes():
    at = run_app(week="2022-10-23", city="PH063022000")
    assert_clean(at)
    text = html_text(at)
    assert "All covered cities" in text and "Your city" not in text
    picks = [b for b in at.button if (b.key or "").startswith("pick_")]
    assert len(picks) == 12
    order = {lvl: i for i, lvl in enumerate(config.DISPLAY_LEVELS)}
    snap = {r: lvl for r, lvl in zip(*_snapshot_levels("2022-10-23", 1))}
    ranks = [order[snap[b.key[len("pick_"):]]] for b in picks]
    assert ranks == sorted(ranks)                                # most urgent first
    for note in ("Metro Manila", "lower confidence", "too few cases to forecast"):
        assert note in text, note


def _snapshot_levels(week, horizon):
    """(pcodes, levels) of the app's snapshot, read the same way the app does."""
    import pandas as pd

    from app.data import snapshot
    snap = snapshot(pd.Timestamp(week), horizon)
    return snap.adm3_pcode.tolist(), snap.alert_level.tolist()


def test_horizon_toggle_labels_carry_dates():
    import pandas as pd
    origin = pd.Timestamp("2022-10-23")
    assert horizon_label(1, origin) == "Next week (Oct 23–29)"
    assert horizon_label(2, origin) == "In 2 weeks (Oct 30–Nov 5)"
    assert config.HORIZONS == (1, 2)


def test_list_click_opens_drawer_and_click_again_closes():
    at = run_app(week="2018-07-15")
    at.button(key="pick_PH137503000").click().run()
    assert_clean(at)
    assert at.session_state["selected"] == "PH137503000" and drawer_open(at)
    assert at.session_state["map_view"] is None                   # map zooms to the city
    at.button(key="pick_PH137503000").click().run()
    assert at.session_state["selected"] is None and not drawer_open(at)


def test_close_button_closes_drawer():
    at = run_app(sel="PH063022000")
    assert drawer_open(at)
    at.button(key="close_panel").click().run()
    assert_clean(at)
    assert at.session_state["selected"] is None and not drawer_open(at)


def test_drawer_in_design_v3_order():
    at = run_app(week="2018-07-15", sel="PH137503000", role="Health office")
    assert_clean(at)
    text = html_text(at)
    parts = ["City of Navotas", "Metro Manila</div><div class=\"leap-dnote\">standard confidence", "leap-dmeaning",
             "Rain last week", "Cases, latest week", "Unusual at",
             "Rain and risk, last 6 weeks + forecast", "Risk usually peaks 2 weeks after "
             "heavy rain.", "Do now", "Focus barangays", "Why this level",
             "Reported cases vs outbreak line", "How reliable is this"]
    positions = [text.index(p) for p in parts]
    assert positions == sorted(positions)
    assert text.count('<span class="leap-dbrgy-rank">') >= 3
    assert "For: Health office" in text and "Because " in text
    assert any(d.label == "Download city brief" for d in at.get("download_button"))
    assert any(e.label == "More details" for e in at.expander)
    assert_no_retired_text(at)


@pytest.mark.parametrize("h", config.HORIZONS)
@pytest.mark.parametrize("pcode", CITIES)
def test_every_city_and_horizon_renders(pcode, h):
    at = run_app(week="2022-10-23", sel=pcode, h=str(h))
    assert_clean(at)
    assert at.session_state["horizon"] == h and drawer_open(at)
    text = html_text(at)
    assert "Do now" in text and "Focus barangays" in text
    assert_no_retired_text(at)


def test_case_signal_city_shows_the_count_not_a_level():
    at = run_app(week="2022-10-23", sel="PH072230000")             # Mandaue
    assert_clean(at)
    text = html_text(at)
    assert "CASE SIGNAL ONLY" in text
    assert "Too few cases here to forecast a level" in text
    assert "or more reported cases in a week is unusual here" in text
    assert "Cebu</div><div class=\"leap-dnote\">too few cases to forecast" in text
    assert "Few reported cases in this city (39 in 2008–2022)" in text


def test_lower_confidence_city_says_so():
    at = run_app(week="2022-10-23", sel="PH083747000")             # Tacloban
    assert_clean(at)
    text = html_text(at)
    assert "Leyte</div><div class=\"leap-dnote\">lower confidence" in text
    assert "Lower confidence: in testing on 2014–2022" in text
    assert "(score 0.68," in text                                  # city_confidence.csv auc


def test_compare_section_has_a_read_only_table_and_no_csv():
    at = run_app()
    assert_clean(at)
    assert any(e.label.startswith("Compare all cities") for e in at.expander)
    assert len(at.dataframe) == 1 and len(at.dataframe[0].value) == 12
    assert not any("CSV" in d.label for d in at.get("download_button"))
    assert "Select a row" not in html_text(at) and "CSV" not in config.COMPARE_LABEL


# PAGES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.mark.parametrize("page, marker", [
    ("Replay", "Navotas, June–August 2018"),
    ("Data reliability", "How often each level was right"),
])
def test_other_tabs(page, marker):
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.session_state["page"] = page
    at.run()
    assert_clean(at)
    assert marker in html_text(at)
    assert config.PAGES == ("Overview", "Replay", "Data reliability")


def test_reliability_lists_sources_and_data_driven_groups():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.session_state["page"] = "Data reliability"
    at.run()
    text = html_text(at)
    assert "Data sources" in text and "Confidence per city" in text
    assert "Legazpi City, Mandaue City, Palayan City had fewer than 5 outbreak weeks" in text
    assert "Cagayan de Oro City, Tacloban City are marked" in text
    assert "Levels come from the modeling team: Warning = a forecast chance in the top 5%" in text
    assert "placeholder cut-offs" not in text
    assert "Baseline, model pending" not in text.split("How often each level was right")[1][:300]


def replay_app(**state):
    """A signed-in app on the Replay tab (extra session state via **state)."""
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.session_state["page"] = "Replay"
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def test_replay_opens_on_navotas_with_the_three_panels_and_what_happened():
    at = replay_app()
    assert_clean(at)
    text = html_text(at)
    assert config.REPLAY_SUBTITLE in text and "Showing the forecast for <b>Jun 3–9, 2018</b>" in text
    assert "What happened" in text and "Heaviest rain" in text
    assert "330 mm of rain in the week of Jun 10–16, 2018" in text
    assert "about 3 weeks before case reports" in text
    assert [s["event"] for s in config.REPLAY_SEASONS] == ["navotas", "washi", "iloilo"]
    assert at.selectbox(key="replay_season").value == 0
    assert at.selectbox(key="replay_season").label == "Outbreak event"
    assert len(at.get("plotly_chart")) == 1


def test_the_open_tab_is_kept_in_the_url_so_a_reload_lands_on_it():
    at = replay_app()
    assert at.query_params["page"] == ["Replay"] or at.query_params["page"] == "Replay"
    at = reliability_app()
    assert "Data reliability" in str(at.query_params["page"])
    assert at.segmented_control(key="page").value == "Data reliability"


def test_extra_info_sections_are_collapsed_with_a_title_and_a_description():
    for label in (config.COMPARE_LABEL, config.RELIABILITY_MORE_LABEL):
        title, _, rest = label.partition("  :gray[")
        assert title and rest.endswith("]") and "·" not in label
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.run()
    assert any(e.label == config.COMPARE_LABEL for e in at.expander)


@pytest.mark.parametrize("idx, last_week", [(0, "2018-08-26"), (1, "2012-02-26"),
                                            (2, "2012-12-23")])
def test_every_season_steps_from_start_to_end(idx, last_week):
    at = replay_app(replay_season=idx)
    assert_clean(at)
    event = config.REPLAY_SEASONS[idx]["event"]
    key = f"replay_week_{event}"
    first = at.session_state[key]
    assert at.button(key="replay_back").disabled                     # at the start
    seen = [first]
    while not at.button(key="replay_fwd").disabled:
        at.button(key="replay_fwd").click().run()
        assert_clean(at)
        seen.append(at.session_state[key])
    assert seen[-1] == pd.Timestamp(last_week) and len(seen) > 12
    assert all(b - a == pd.Timedelta(weeks=1) for a, b in zip(seen, seen[1:]))   # every week
    assert "Showing the forecast for" in html_text(at)


def test_play_advances_one_week_at_a_time_and_stops_at_the_end():
    at = replay_app(replay_playing=True, replay_last=0.0)
    assert_clean(at)
    assert at.session_state["replay_week_navotas"] == pd.Timestamp("2018-06-10")
    at.session_state["replay_last"] = 0.0
    at.run()
    assert at.session_state["replay_week_navotas"] == pd.Timestamp("2018-06-17")
    at = replay_app(replay_playing=True, replay_last=0.0,
                    replay_week_navotas=pd.Timestamp("2018-08-19"))
    assert at.session_state["replay_week_navotas"] == pd.Timestamp("2018-08-26")
    assert at.session_state["replay_playing"] is False               # stopped at the last week


def test_pause_and_season_change_stop_playback():
    at = replay_app()
    at.button(key="replay_play").click().run()
    assert_clean(at)
    assert at.session_state["replay_playing"] is True
    at.button(key="replay_play").click().run()
    assert at.session_state["replay_playing"] is False
    at.session_state["replay_playing"] = True
    at.selectbox(key="replay_season").select(1).run()
    assert at.session_state["replay_playing"] is False


def test_washi_is_a_miss_with_a_flood_alert_link():
    at = replay_app(replay_season=1, replay_week_washi=pd.Timestamp("2012-01-01"))
    assert_clean(at)
    text = html_text(at)
    assert "554 reported cases, 42 times the outbreak line" in text
    assert "did not foresee it" in text and "No lead time is claimed" in text
    assert "774 cases in 5 weeks" in text and "73%" in text
    assert "less certain" in text                                    # 2011 seasons say so
    at.button(key="replay_flood").click().run()
    assert at.session_state["page"] == "Overview" and "Flood alert is a switch" in html_text(at)


def test_navotas_replay_opens_the_week_on_the_overview():
    at = replay_app(replay_week_navotas=pd.Timestamp("2018-07-08"))
    assert not any(b.key == "replay_flood" for b in at.button)       # only Washi has the link
    at.button(key="replay_open").click().run()
    assert_clean(at)
    assert at.session_state["page"] == "Overview"
    assert at.session_state["origin"] == pd.Timestamp("2018-07-08")
    assert at.session_state["selected"] == "PH137503000" and drawer_open(at)


def test_iloilo_and_washi_weeks_before_2014_cannot_open_the_overview():
    at = replay_app(replay_season=2)
    assert not any(b.key == "replay_open" for b in at.button)
    assert "missed at its start" in html_text(at)


def test_replay_without_the_file_says_what_to_run(monkeypatch, tmp_path):
    shutil.copy(config.MODEL_OUTPUTS_DIR / "alerts.csv", tmp_path / "alerts.csv")
    monkeypatch.setattr(config, "MODEL_OUTPUTS_DIR", tmp_path)
    at = replay_app()
    assert not at.exception
    assert "import_analysis_outputs.py" in html_text(at)


def test_search_opens_the_drawer_from_any_tab():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.session_state["page"] = "Replay"
    at.run()
    at.selectbox(key="search").select("PH112402000").run()
    assert_clean(at)
    assert at.session_state["page"] == "Overview"
    assert at.session_state["selected"] == "PH112402000" and drawer_open(at)


@pytest.mark.parametrize("h, expected", [("2", 2), ("Week 2", 2), ("Week 3", 1), ("Wk 4", 1),
                                         ("nope", 1)])
def test_horizon_from_url(h, expected):
    at = run_app(h=h)
    assert_clean(at)
    assert at.session_state["horizon"] == expected


# EDGE CASES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.mark.parametrize("week", ["2014-12-28", "2020-12-27"])   # MW53 weeks (no case data)
def test_week_53_origins_render(week):
    at = run_app(week=week, sel="PH063022000")
    assert_clean(at)


def test_washi_week_snaps_to_first_forecast_with_notice():
    at = run_app(week="2011-12-18", sel="PH104305000")             # Cagayan de Oro
    assert_clean(at)
    text = html_text(at)
    assert "Forecasts start the week of Dec 29, 2013" in text
    assert "Cagayan de Oro City" in text and drawer_open(at)
    assert "No forecast for the week of" not in text


def test_navotas_june_2018():
    at = run_app(week="2018-06-17", sel="PH137503000")
    assert_clean(at)
    text = html_text(at)
    assert "Forecast for <b class=\"leap-date\">Jun 17–23, 2018</b>" in text
    # The Jun 10-16 flood week: 279 mm IMERG Final (DESIGN_V3's "330 mm" is IMERG Late).
    assert "Rain last week" in text and "279 mm" in text


def test_week_before_forecast_period_shows_notice():
    at = run_app(week="2009-03-01")
    assert_clean(at)
    assert "Forecasts start the week of Dec 29, 2013" in html_text(at)


def test_last_week_in_2_weeks_says_no_forecast():
    at = run_app(week="2022-12-25", h="2", sel="PH063022000", city="PH063022000")
    assert_clean(at)
    text = html_text(at)
    assert "No forecast for the week of Jan 1–7, 2023" in text
    assert "No forecast for this week" in text                     # drawer reason
    assert "NO FORECAST" in text


def test_non_reporting_week_says_no_report():
    at = run_app(week="2020-05-03", sel="PH137503000", city="PH137503000")
    assert_clean(at)
    text = html_text(at)
    assert "NO REPORT" in text and "This week was flagged as non-reporting." in text
    assert "flagged as non-reporting), so recent cases can" in text
    assert "Follow up with disease reporting units" not in text   # resident view


def test_week_after_data_end_shows_notice():
    at = run_app(week="2024-06-02")
    assert_clean(at)
    assert "data ends in 2022" in html_text(at)


def test_unreadable_week_and_city_fall_back():
    at = run_app(week="not-a-date", city="PH000000000", sel="nope")
    assert_clean(at)
    assert "home_city" not in at.session_state
    assert at.session_state["selected"] is None


def test_missing_model_and_baseline_files_show_message(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MODEL_OUTPUTS_DIR", tmp_path / "none")
    monkeypatch.setattr(config, "PROCESSED_DIR", config.PROCESSED_DIR)  # keep parquet files
    import src.load_outputs as lo
    real = lo.load_with_fallback

    def no_files(filename, columns, validator, **kwargs):
        kwargs.update(model_dir=tmp_path / "none", processed_dir=tmp_path / "none")
        return real(filename, columns, validator, **kwargs)

    monkeypatch.setattr(lo, "load_with_fallback", no_files)
    at = run_app()
    assert not at.exception
    assert any("No forecasts are available" in e.value and "alerts.csv" in e.value
               for e in at.error)


def test_missing_processed_data_shows_message(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path)
    at = run_app()
    assert not at.exception
    assert any("A data file is missing" in e.value for e in at.error)


# DATA SOURCES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_model_files_in_use_show_no_fallback_warning():
    at = run_app()
    assert_clean(at)
    assert not any("own data pipeline" in w.value for w in at.warning)


def test_missing_model_files_show_fallback_warning(monkeypatch, tmp_path):
    # Only alerts.csv delivered: cases, rainfall and thresholds fall back, and
    # the confidence groups come from the config fallback.
    shutil.copy(config.MODEL_OUTPUTS_DIR / "alerts.csv", tmp_path / "alerts.csv")
    monkeypatch.setattr(config, "MODEL_OUTPUTS_DIR", tmp_path)
    at = run_app(week="2022-10-23", sel="PH072230000")
    assert_clean(at)
    text = " ".join(w.value for w in at.warning)
    assert "own data pipeline" in text
    assert "Reported cases" in text and "IMERG rainfall" in text
    assert "CASE SIGNAL ONLY" in html_text(at)


# MAP VIEWS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_map_view_buttons():
    at = run_app()
    assert_clean(at)
    assert at.session_state["map_view"] == "Philippines"
    for name in ("Luzon", "Visayas", "Mindanao", "Philippines"):
        at.button(key=f"view_{name}").click().run()
        assert_clean(at)
        assert at.session_state["map_view"] == name
    assert at.session_state["view_nonce"] == 4


def test_view_button_keeps_drawer_open():
    at = run_app(sel="PH063022000")
    assert at.session_state["map_view"] is None          # zoomed to the city
    at.button(key="view_Visayas").click().run()
    assert_clean(at)
    assert at.session_state["selected"] == "PH063022000" and drawer_open(at)
    assert at.session_state["map_view"] == "Visayas"


# DEFAULT WEEK, FLOOD ALERT, BACKGROUND WATCH +++++++++++++++++++++++++++++++++

def test_default_week_has_warning_cities_and_navotas():
    at = run_app()
    assert_clean(at)
    text = html_text(at)
    assert "Forecast for <b class=\"leap-date\">Jul 8–14, 2018</b>" in text
    assert "0</b> at Warning" not in text
    import pandas as pd
    pcodes, levels = _snapshot_levels(config.DEFAULT_ORIGIN, 1)
    assert dict(zip(pcodes, levels))["PH137503000"] == "Warning"       # Navotas


def test_flood_alert_is_for_health_offices_and_never_changes_the_level():
    resident = run_app(sel="PH104305000")
    assert not resident.toggle                                  # no switch for residents
    at = run_app(sel="PH104305000", role="Health office")
    level_before = [b for b in html_text(at).split() if "leap-badge-md" in b]
    key = next(t.key for t in at.toggle if t.key.startswith("flood_"))
    at.toggle(key=key).set_value(True).run()
    assert_clean(at)
    text = html_text(at)
    assert "Flood alert: 4 weeks left" in text and "Flood alert: do now" in text
    assert "Because a major flood was reported; the model can" in text
    assert [b for b in text.split() if "leap-badge-md" in b] == level_before
    at.button(key="step_fwd").click().run()                     # one week later
    assert "Flood alert: 3 weeks left" in html_text(at)
    for _ in range(3):
        at.button(key="step_fwd").click().run()
    assert "Flood alert:" not in html_text(at)                # ran out after 4 weeks


def test_davao_watch_is_background():
    at = run_app(sel="PH112402000")
    text = html_text(at)
    assert "Davao is at Watch about 24 weeks a year, so treat Watch here as background" in text
    assert "treat Watch here as background" not in html_text(run_app(sel="PH137503000"))


# DATA RELIABILITY +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def reliability_app(**state):
    """A signed-in app on the Data reliability tab (extra session state via **state)."""
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.session_state["page"] = "Data reliability"
    for k, v in state.items():
        at.session_state[k] = v
    return at.run()


def test_reliability_has_every_part_of_design_v3_section_3():
    at = reliability_app()
    assert_clean(at)
    text = html_text(at)
    parts = ["How reliable is this?", "We tested the forecasts on 2014–2022", "5,372 city-weeks",
             "What each level has meant", "leap-rel-row", "leap-rel-tile", "What it can",
             "Data sources", "References", "APA 7th"]
    positions = [text.index(p) for p in parts]
    assert positions == sorted(positions)
    assert text.count('class="leap-rel-row"') == 3 and text.count('class="leap-rel-tile"') == 4
    assert text.count('class="leap-ref"') == 6 and "https://doi.org/10.5067/GPM/IMERGDL/DAY/07" in text
    assert text.count("source: ") >= 12                      # a source caption on every block
    assert any(e.label.startswith("More details") for e in at.expander)
    assert 'style="left:6.9' in text or 'style="left:13.' in text   # dashed base-rate line placed


def test_reliability_switches_between_weeks_ahead():
    at = reliability_app()
    assert "Showing the forecast next week." in html_text(at)
    at.session_state["reliability_h"] = 2
    at.run()
    assert_clean(at)
    text = html_text(at)
    assert "Showing the forecast in 2 weeks." in text and "38%" in text and "69%" in text


def test_reliability_shows_pending_when_a_file_is_missing(monkeypatch, tmp_path):
    for f in config.MODEL_OUTPUTS_DIR.glob("*.csv"):
        if f.name not in ("episodes.csv", "rain_gain.csv"):
            shutil.copy(f, tmp_path / f.name)
    monkeypatch.setattr(config, "MODEL_OUTPUTS_DIR", tmp_path)
    at = reliability_app()
    assert_clean(at)
    text = html_text(at)
    assert "started in a Watch week: pending" in text and "(about half)" not in text
    assert "80%" not in text                                 # the flagged-first-week tile
    assert "None" not in text.split("</style>")[0]


def test_reliability_never_shows_canvas_numbers_the_data_contradicts():
    for h in (1, 2):
        text = html_text(reliability_app(reliability_h=h)).split("</style>")[0]
        for stale in ("44%", "73%", "56%", "2 of 3", "2.4×", "falls back to rain"):
            assert stale not in text, stale


def test_landing_has_no_sample_card_or_tagline():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT).run()
    assert_clean(at)
    text = html_text(at)
    assert "Know your leptospirosis risk" in text
    assert "SAMPLE ALERT" not in text and "Floods follow storms" not in text
    assert "leap-sample" not in text and "leap-tagline" not in text


def test_map_has_no_basemap_switch():
    at = run_app()
    assert_clean(at)
    assert not any(s.label == "Basemap" for s in at.get("button_group"))
    assert "basemap" not in at.session_state


@pytest.mark.parametrize("layer", config.MAP_LAYERS)
def test_every_map_layer_renders_with_its_legend_and_no_mode_text(layer):
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.run()
    at.session_state["layer"] = layer          # init_state sets the default on the first run
    at.run()
    assert_clean(at)
    text = html_text(at)
    assert "Showing:" not in text and "Your city" not in text
    assert ('class="leap-key-gradient"' in text) == (layer != "Risk")


# FRESH CLONE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_first_load_replay_and_reliability_have_no_exception():
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["user"], at.session_state["loaded"] = "Tester", True
    at.run()
    assert not at.exception and not at.error                 # Overview on first load
    for page in ("Replay", "Data reliability"):
        at.session_state["page"] = page
        at.run()
        assert not at.exception and not at.error, page


def test_every_runtime_file_is_committed_in_the_repository():
    from app.data import missing_runtime_files
    assert missing_runtime_files() == []


def test_missing_runtime_files_are_named_with_a_fix(tmp_path):
    from app.data import missing_runtime_files
    missing = dict(missing_runtime_files(tmp_path))
    assert set(missing) == set(config.RUNTIME_FILES)
    assert "build_processed.py" in missing["data/processed/cities.geojson"]
    assert "Restore" in missing["static/style.css"]


def test_app_shows_the_missing_file_message_not_a_traceback(monkeypatch):
    monkeypatch.setattr(config, "RUNTIME_FILES", {"data/processed/nope.parquet": "Run the thing."})
    at = run_app()
    assert not at.exception
    assert any("cannot start" in e.value for e in at.error)
    assert any("data/processed/nope.parquet" in m.value and "Run the thing." in m.value
               for m in at.markdown)
