"""Tests for app/logic/reasons.py: built from real columns only, never guessed."""

import numpy as np
import pandas as pd
import pytest

from app import config
from app.logic.reasons import (city_reasons, cases_reason, flood_reason, headline_reason,
                               heavy_rain_reason, lag_window, seasonal_reason)
from src.views import cases_week_start
from src.weeks import week_starts

P = "PH063022000"                                   # Iloilo (standard confidence)
LOW = "PH072230000"                                 # Mandaue (case signal only)
ORIGIN = pd.Timestamp("2015-03-15")                 # 2015 MW11
LATEST = cases_week_start(ORIGIN)                   # latest reported week: Mar 1
BANNED = ("caused by", "will get", "will have", "deadly", "outbreak is coming")


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def weekly(years=range(2011, 2016), weeks=range(1, 53), value=10.0, pcode=P):
    """A city x (year, MW) grid on the Sunday calendar with one constant value."""
    grid = pd.DataFrame([(y, w) for y in years for w in weeks], columns=["mw_year", "mw_week"])
    grid["week_start"] = week_starts(grid.mw_year, grid.mw_week).to_numpy()
    grid["adm3_pcode"] = pcode
    grid["value"] = value
    return grid


def rain_table(last_week_mm=None, two_weeks_mm=None, usual=40.0):
    rain = weekly(value=usual).rename(columns={"value": "rain_mm"})
    for ago, mm in ((1, last_week_mm), (2, two_weeks_mm)):
        if mm is not None:
            rain.loc[rain.week_start == ORIGIN - pd.Timedelta(weeks=ago), "rain_mm"] = mm
    return rain


def cases_table(last_week=0, flag=None, history=0, pcode=P):
    """Cases with `last_week` cases in the latest REPORTED week (2 weeks back)."""
    cases = weekly(value=history, pcode=pcode).rename(columns={"value": "cases"})
    cases["reporting_flag"] = None
    last = cases.week_start == LATEST
    cases.loc[last, "cases"] = last_week
    cases.loc[last, "reporting_flag"] = flag
    return cases


def thresholds_table(value=4.0, pcode=P):
    return weekly(value=value, pcode=pcode).rename(columns={"value": "threshold"})


def flood_table(top_pct=51.0, pcode=P):
    return pd.DataFrame({"adm3_pcode": pcode, "rank": [1, 2],
                         "brgy_name": ["Hinactacan", "Buhang"],
                         "high_hazard_pct": [top_pct, 10.0]})


# SIGNALS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_heavy_rain_states_numbers_and_window():
    r = heavy_rain_reason(rain_table(two_weeks_mm=185.0), P, ORIGIN, (1, 5))
    assert r.kind == "heavy_rain"
    assert r.text.startswith("Heavy rain 2 weeks ago: 185 mm vs a usual 40 mm")
    assert "may raise the chance of an outbreak week for the next 1–5 weeks" in r.text
    assert "IMERG" in r.source


def test_heavy_rain_needs_ratio_and_minimum_mm():
    assert heavy_rain_reason(rain_table(last_week_mm=70.0), P, ORIGIN) is None   # < 2x usual
    small = rain_table(last_week_mm=30.0, usual=5.0)                               # 6x, < 50 mm
    assert heavy_rain_reason(small, P, ORIGIN) is None


def test_heavy_rain_missing_data_is_dropped():
    rain = rain_table(last_week_mm=200.0)
    rain.loc[rain.week_start == ORIGIN - pd.Timedelta(weeks=1), "rain_mm"] = np.nan
    assert heavy_rain_reason(rain, P, ORIGIN) is None
    assert heavy_rain_reason(rain.iloc[0:0], P, ORIGIN) is None


def test_cases_above_and_close_to_the_line():
    above = cases_reason(cases_table(last_week=6), thresholds_table(4.0), P, ORIGIN)
    assert above.text == ("6 cases reported in the latest reported week (from Mar 1), above "
                          "that week's outbreak line (more than 4).")
    close = cases_reason(cases_table(last_week=3), thresholds_table(4.0), P, ORIGIN)
    assert "close to" in close.text
    assert cases_reason(cases_table(last_week=2), thresholds_table(4.0), P, ORIGIN) is None


def test_cases_reason_dropped_for_non_reporting_or_missing_line():
    flagged = cases_table(last_week=9, flag="non_reporting")
    assert cases_reason(flagged, thresholds_table(), P, ORIGIN) is None
    no_line = thresholds_table().assign(threshold=np.nan)
    assert cases_reason(cases_table(last_week=9), no_line, P, ORIGIN) is None


def test_seasonal_counts_earlier_years_only():
    cases = cases_table(history=0)
    # 2013 MW10-12 above the line (5 > 4); 2015's own weeks never count
    cases.loc[(cases.mw_year == 2013) & cases.mw_week.between(10, 12), "cases"] = 5
    cases.loc[(cases.mw_year == 2015) & cases.mw_week.between(10, 12), "cases"] = 50
    r = seasonal_reason(cases, thresholds_table(4.0), P, ORIGIN)
    assert r.text == ("Seasonal pattern: in 2011–2014, 3 of 12 weeks around this time of "
                      "year were outbreak weeks here.")


def test_flood_needs_a_largely_flooded_barangay():
    assert "Hinactacan has 51%" in flood_reason(flood_table(51.0), P).text
    assert flood_reason(flood_table(30.0), P) is None
    assert flood_reason(None, P) is None


def test_lag_window_from_curve_and_fallback():
    curve = pd.DataFrame({"lag_weeks": range(8), "rr_p95": 1.2,
                          "rr_p95_lower": [0.9, 1.2, 1.6, 1.5, 1.3, 1.1, 0.97, 0.92]})
    assert lag_window(curve) == (1, 5)
    assert lag_window(None) == config.LAG_WINDOW_FALLBACK


# ALL REASONS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def reasons(pcode=P, level="Warning", **kw):
    args = dict(rain_weekly=rain_table(last_week_mm=150.0), cases=cases_table(last_week=6),
                thresholds=thresholds_table(4.0), flood_rank=flood_table())
    args.update(kw)
    return city_reasons(pcode, level, ORIGIN, ORIGIN, **args)


def test_full_set_in_order_without_seasonal():
    kinds = [r.kind for r in reasons()]
    assert kinds == ["heavy_rain", "cases", "flood"]          # seasonal only as fallback
    assert headline_reason(reasons()).kind == "heavy_rain"


def test_seasonal_is_the_fallback():
    out = reasons(rain_weekly=rain_table(), cases=cases_table(last_week=0))
    assert [r.kind for r in out] == ["seasonal", "flood"]


def test_missing_inputs_are_dropped_never_guessed():
    out = reasons(rain_weekly=rain_table().iloc[0:0], cases=cases_table(last_week=0),
                  thresholds=thresholds_table().iloc[0:0], flood_rank=None)
    assert out == []
    assert headline_reason(out) is None


def test_non_reporting_week_drops_cases_and_says_so():
    out = reasons(cases=cases_table(last_week=9, flag="non_reporting"))
    kinds = [r.kind for r in out]
    assert "cases" not in kinds and "no_report" in kinds
    assert headline_reason(out).kind == "no_report"
    nr = reasons(level=config.NO_REPORT_LEVEL)
    assert nr[0].kind == "no_report"                          # the level's own note leads


def test_cases_reason_ignores_the_unreported_last_week():
    # Cases for the week just before the forecast are not reported yet.
    cases = cases_table(last_week=0)
    cases.loc[cases.week_start == ORIGIN - pd.Timedelta(weeks=1), "cases"] = 50
    assert cases_reason(cases, thresholds_table(4.0), P, ORIGIN) is None


def test_case_signal_city_says_so_first():
    out = reasons(pcode=LOW, level=config.CASE_SIGNAL_LEVEL, group="case_signal",
                  rain_weekly=rain_table(last_week_mm=150.0).assign(adm3_pcode=LOW),
                  cases=cases_table(last_week=1, history=0, pcode=LOW),
                  thresholds=thresholds_table(4.0, pcode=LOW), flood_rank=flood_table(pcode=LOW))
    assert out[0].kind == "case_signal"
    assert out[0].text.startswith("Few reported cases in this city (1 in 2008–2022), too few "
                                  "to forecast a level.")
    assert headline_reason(out).kind == "case_signal"


def test_lower_confidence_note_quotes_auc_but_never_leads():
    out = reasons(group="lower", auc=0.588)
    assert out[0].kind == "lower_confidence"
    assert "(score 0.59, where 0.5 is guessing and 1 is perfect)" in out[0].text
    assert headline_reason(out).kind == "heavy_rain"           # the signal leads
    only_note = reasons(group="lower", rain_weekly=rain_table().iloc[0:0],
                        cases=cases_table().iloc[0:0], thresholds=thresholds_table().iloc[0:0],
                        flood_rank=None)
    assert headline_reason(only_note).kind == "lower_confidence"
    assert reasons(group="lower", auc=None)[0].text.endswith("than in most cities.")


def test_standard_city_has_no_confidence_note():
    assert not {r.kind for r in reasons()} & {"case_signal", "lower_confidence"}


def test_no_forecast_has_only_its_note():
    out = reasons(level=config.NO_FORECAST_LEVEL)
    assert [r.kind for r in out] == ["no_forecast"]


@pytest.mark.parametrize("level", ["Warning", "Normal", config.CASE_SIGNAL_LEVEL])
def test_wording_never_overclaims(level):
    text = " ".join(r.text for r in reasons(level=level)).lower()
    assert not any(b in text for b in BANNED)
    assert "may" in text and "people" not in text
