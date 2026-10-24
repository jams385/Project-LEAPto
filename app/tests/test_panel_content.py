"""Tests for the city-drawer content: actions, brief, forecast weeks, series."""

import pandas as pd
import pytest

from app import config
from app.content.actions import FLOOD_BECAUSE, flood_actions, select_actions
from app.logic.reasons import Reason
from src.brief import build_city_brief
from src.views import city_horizons, city_timeseries, level_descriptions

ORIGIN = pd.Timestamp("2015-03-01")
BANNED = ("caused by", "will get", "deadly", "outbreak is coming")
# Never state a forecast number of people (SPEC_V2 §6).
RETIRED = ("predicted", "est. cases", "risk score", "95% range", "very high")


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.fixture
def alerts():
    levels = {1: "Normal", 2: "Watch", 3: "Warning"}
    rows = [("A", ORIGIN, h, ORIGIN + pd.Timedelta(weeks=h - 1), 0.1 * h, levels[h])
            for h in (3, 1, 2)]
    return pd.DataFrame(rows, columns=["adm3_pcode", "origin_week", "horizon", "target_week",
                                       "outbreak_prob", "alert_level"])


@pytest.fixture
def city_row():
    return {"city_name": "Alpha City", "province": "P", "region": "Region VII",
            "alert_level": "Warning", "forecast_level": "Warning", "rank": 2,
            "outbreak_prob": 0.29, "threshold": 2.5, "cases_week": ORIGIN - pd.Timedelta(weeks=2),
            "latest_cases": 3.0, "latest_flag": None, "unusual_at": 3.0, "rain_week_mm": 120.0,
            "rain_status": "Wetter than usual", "hazard_pct": 12.0, "confidence": "lower",
            "target_week": ORIGIN + pd.Timedelta(weeks=2)}


# ACTIONS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def texts(actions):
    return [a["text"] for a in actions]


RAIN = Reason("heavy_rain", "Heavy rain last week: 150 mm vs a usual 40 mm.", "IMERG")
CASES = Reason("cases", "6 cases reported last week, above the line.", "PIDSR")
FLOOD = Reason("flood", "Flood-prone area: Salisay has 50%.", "NOAH")


@pytest.mark.parametrize("level", [*config.DISPLAY_LEVELS, None])
@pytest.mark.parametrize("role", config.ROLES)
@pytest.mark.parametrize("horizon", config.ALERT_HORIZONS)
def test_every_level_role_horizon_has_safe_actions_with_because(level, role, horizon):
    actions = select_actions(level, role, horizon, [RAIN, CASES, FLOOD], ["Salisay"])
    assert actions
    for a in actions:
        assert a["text"] and a["because"]
        assert "{" not in a["text"] + a["because"]
    text = " ".join(a["text"] + " " + a["because"] for a in actions).lower()
    assert not any(b in text for b in BANNED)
    assert " mg" not in text and "dose" not in text           # never dosing details


def test_warning_health_office_core_actions():
    out = texts(select_actions("Warning", "Health office", 1, (), ["Salisay", "Mangin"]))
    assert out[0] == ("Pre-position doxycycline PEP per DOH guidelines in the most flood-prone "
                      "barangays (Salisay and Mangin).")
    assert any(t.startswith("Issue public advisories") for t in out)
    assert any(t.startswith("Alert health facilities") for t in out)


def test_watch_and_normal_actions():
    watch = texts(select_actions("Watch", "Health office", 1))
    assert watch[0].startswith("Check doxycycline PEP stock")
    assert any("advisory messages" in t for t in watch)
    assert any("next forecast" in t for t in watch)
    assert select_actions("Normal", "Health office")[0]["text"].startswith("Routine surveillance")


def test_week_3_is_preparation_only():
    out = select_actions("Warning", "Health office", 3, (), ["Salisay"])
    assert all(a["text"].startswith(("Prepare", "Draft", "Check")) for a in out)
    assert "less certain" in out[0]["because"]
    assert not any("Act now" in a["text"] for a in out)
    watch3 = select_actions("Watch", "Health office", 3)
    assert all("Week 3 is less certain" in a["because"] for a in watch3)


def test_reasons_move_relevant_actions_up_and_explain_them():
    plain = select_actions("Warning", "Health office", 1)
    rain = select_actions("Warning", "Health office", 1, [RAIN])
    assert rain[0]["text"].startswith("Issue public advisories")         # boosted first
    assert rain[0]["because"].startswith("heavy rain fell recently")
    assert plain[0]["text"].startswith("Pre-position")
    cases = select_actions("Warning", "Health office", 1, [CASES])
    assert cases[0]["text"].startswith("Alert health facilities")
    assert "outbreak line" in cases[0]["because"]


def test_do_now_shows_only_the_top_three():
    full = select_actions("Warning", "Health office", 1, [RAIN])
    top = select_actions("Warning", "Health office", 1, [RAIN], limit=config.DRAWER_ACTIONS)
    assert len(top) == 3 and top == full[:3] and len(full) > 3


def test_case_signal_actions_watch_the_count():
    first = select_actions(config.CASE_SIGNAL_LEVEL, "Health office")[0]
    assert first["text"].startswith("Check each week's reported case count")
    assert "too few cases here to forecast a level" in first["because"]


def test_when_wording_follows_horizon_names():
    watch = select_actions("Watch", "Health office", 2)[0]["because"]
    assert watch.endswith("in 2 weeks")


def test_barangays_named_top_three_only():
    places = ["Salisay", "Mangin", "Bonuan Binloc", "Herrero"]
    first = select_actions("Warning", "Health office", 1, (), places)[0]["text"]
    assert "(Salisay, Mangin and Bonuan Binloc)" in first and "Herrero" not in first
    general = select_actions("Warning", "Health office", 1)[0]["text"]
    assert general.endswith("most flood-prone barangays.")


def test_no_report_and_unknown_levels():
    assert "non-reporting" in select_actions(config.NO_REPORT_LEVEL, "Health office")[0][
        "because"]
    assert select_actions(None, "Health office") == select_actions(
        config.CASE_SIGNAL_LEVEL, "Health office")
    assert select_actions("Warning", "Mayor") == select_actions("Warning", "Resident")


# BRIEF ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_brief_contents(alerts, city_row):
    brief = build_city_brief(city_row, city_horizons(alerts, "A", ORIGIN),
                             [{"text": "Do this.", "because": "it helps"}],
                             role="Resident", origin_week=ORIGIN,
                             source_label=config.BASELINE_BANNER,
                             levels=level_descriptions(None, 3), horizon=3,
                             reasons=[Reason("cases", "3 cases last week.", "PIDSR")])
    assert brief.startswith("# Alpha City")
    assert "## In 3 weeks (week of Mar 15, 2015)" in brief
    assert "Confidence: lower confidence*" in brief and "·" not in brief
    # The sentence uses this city's own multiplier: 0.29 / 0.068 ≈ 4×.
    assert "Alert level: **Warning**. Outbreak week is about 4×" in brief
    assert "≈4× usual risk" in brief and "more than 2.5 reported cases" in brief  # 0.29/0.068
    assert "2008–2022" in brief and "not a diagnosis" in brief
    assert config.FORECAST_SCOPE_NOTE in brief
    assert "- Cases in the latest reported week (week from Feb 15): 3 (unusual at 3 or more)" \
        in brief
    assert "- Next week (Mar 1): Normal" in brief and "- In 2 weeks (Mar 8): Watch" in brief
    assert "- Do this. Because it helps." in brief
    assert "## What we're seeing (observed data)" in brief
    assert "- 3 cases last week. *Source: PIDSR.*" in brief
    lower = brief.lower()
    assert not any(b in lower for b in BANNED + RETIRED)


def test_brief_lists_barangays_and_lag_finding(alerts, city_row):
    brgys = pd.DataFrame({"brgy_name": ["Salisay", "Mangin"], "high_hazard_pct": [49.9, 33.7]})
    brief = build_city_brief(city_row, city_horizons(alerts, "A", ORIGIN), [],
                             role="Health office", origin_week=ORIGIN, source_label="x",
                             levels=level_descriptions(None, 1), barangays=brgys,
                             lag_text="Heavy rain raises risk +41% the next week.")
    assert "## Most flood-prone barangays" in brief
    assert "1. Salisay: 50% of its area is high hazard" in brief
    assert "*Heavy rain raises risk +41% the next week.*" in brief
    assert "- In 3 weeks (Mar 15): Warning, ≈4× a usual week" in brief


def test_brief_case_signal_city_and_missing_values(city_row):
    city_row.update(alert_level=config.CASE_SIGNAL_LEVEL, rain_week_mm=None, rain_status=None,
                    outbreak_prob=float("nan"), latest_flag="non_reporting",
                    target_week=pd.NaT, confidence="case_signal", unusual_at=2.0)
    empty = pd.DataFrame(columns=["horizon"])
    brief = build_city_brief(city_row, empty, [], role="Health office", origin_week=ORIGIN,
                             source_label="x", levels=level_descriptions(None, 1))
    assert "## Next week (week of Mar 1, 2015)" in brief
    assert "Model estimate (low confidence): Warning" in brief
    assert "2 or more reported cases in a week is unusual here" in brief
    assert "too few cases to forecast*" in brief and "non-reporting" in brief
    assert "not available" in brief and "No forecast available" in brief
    assert "usual risk" not in brief


# SERIES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_city_horizons_sorted_case_signal_and_empty(alerts):
    out = city_horizons(alerts, "A", ORIGIN)
    assert out.horizon.tolist() == [1, 2, 3]
    assert out.alert_level.tolist() == ["Normal", "Watch", "Warning"]
    assert city_horizons(alerts, "A", ORIGIN, horizons=(1, 2)).horizon.tolist() == [1, 2]
    low = "PH072230000"
    assert set(city_horizons(alerts.assign(adm3_pcode=low), low, ORIGIN, {low}).alert_level) \
        == {config.CASE_SIGNAL_LEVEL}
    assert city_horizons(alerts, "Z", ORIGIN).empty


def test_city_timeseries_has_no_forecast_counts():
    weeks = pd.date_range(ORIGIN - pd.Timedelta(weeks=3), ORIGIN + pd.Timedelta(weeks=2),
                          freq="7D")
    cases = pd.DataFrame({"adm3_pcode": "A", "week_start": weeks,
                          "cases": pd.array([1, 2, None, 4, 5, 6], dtype="Int64"),
                          "reporting_flag": [None, None, "non_reporting", None, None, None]})
    rain = pd.DataFrame({"adm3_pcode": "A", "week_start": weeks, "rain_mm": 10.0})
    thr = pd.DataFrame({"adm3_pcode": "A", "week_start": weeks, "threshold": 3.0})
    s = city_timeseries(cases, rain, thr, "A", ORIGIN, weeks_back=3)
    assert len(s) == 6
    assert s.is_future.tolist() == [False] * 3 + [True] * 3
    assert s.cases.isna().sum() == 1                    # gap stays NaN, not 0
    assert s.reporting_flag.tolist()[2] == "non_reporting"
    assert not any("predicted" in c for c in s.columns)


def test_flood_actions_say_why_and_name_places():
    out = flood_actions(["Salisay", "Mangin"])
    assert len(out) == 3 and all(a["because"] == FLOOD_BECAUSE for a in out)
    assert "see Washi" in FLOOD_BECAUSE and "(Salisay and Mangin)" in out[1]["text"]
    assert "{" not in " ".join(a["text"] for a in flood_actions())
