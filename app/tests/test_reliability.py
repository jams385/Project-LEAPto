"""Tests for the Data reliability facts (src/reliability.py) and wording.

Besides unit tests, "claim" tests check that every number and descriptive phrase
the page can show is backed by the final outputs (and by the modeling team's
own summary files when ../analysis is present): a phrase such as "about
a third" must appear only where the number supports it.
"""

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import config
from app.content.reliability_text import cant_do, intro, row_text, tiles
from src.contract import load_part
from src.reliability import (auc_pair, calibration_top, case_counts, city_groups_named,
                             episode_share, event_peak, first_week_flagged, fraction_phrase,
                             lead_weeks_range, level_rows, no_report_weeks, normal_blip_share,
                             out_of_ten, rain_gain_split, evaluation_period)

_BASE = config.ANALYSIS_DIR_DEFAULT
_BASE = _BASE / "analysis" if (_BASE / "analysis" / "output").is_dir() else _BASE
ANALYSIS = _BASE / "output" / "stage5"
PEND = config.PENDING_TEXT


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def metrics_table():
    """A small track record: 1000 weeks, 100 outbreak weeks (base rate 10%)."""
    return pd.DataFrame({
        "horizon": [1, 1, 1, 2, 2, 2],
        "alert_level": ["Normal", "Watch", "Warning"] * 2,
        "n_weeks": [800, 150, 50] * 2, "n_outbreaks": [20, 45, 35] * 2,
        "hit_rate": [0.025, 0.30, 0.70] * 2, "base_rate": [0.10] * 6,
        "lift": [0.25, 3.0, 7.0] * 2, "capture_rate": [1.0, 0.80, 0.35] * 2})


def episodes_table():
    rows = []
    for h in (1, 2):
        for kind, n in (("2+ weeks", (2, 6, 2)), ("single week", (9, 3, 1))):
            for level, k in zip(("Normal", "Watch", "Warning"), n):
                rows.append({"horizon": h, "episode": kind, "alert_level": level, "n": k,
                             "share": k / sum(n)})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def real():
    names = {"metrics": "level_metrics", "episodes": "episodes", "auc": "auc",
             "rain_gain": "rain_gain", "alerts": "alerts", "replay": "replay",
             "flags": "reporting_flags", "cases": "cases", "conf": "city_confidence"}
    return {k: load_part(v)[0] for k, v in names.items()}


# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.mark.parametrize("x, phrase", [(0.343, "a third"), (0.368, "a third"), (0.516, "half"),
                                       (0.292, None), (0.40, None), (0.76, "three quarters"),
                                       (None, None), (np.nan, None)])
def test_fraction_phrase_only_when_the_number_supports_it(x, phrase):
    assert fraction_phrase(x) == phrase


@pytest.mark.parametrize("x, text", [(0.711, "7 in 10"), (0.694, "7 in 10"), (0.5, "5 in 10"),
                                     (None, None)])
def test_out_of_ten(x, text):
    assert out_of_ten(x) == text


# FACTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_level_rows_split_outbreak_weeks_by_level():
    rows = {r["level"]: r for r in level_rows(metrics_table(), 1)}
    assert list(rows) == ["Warning", "Watch", "Normal"]
    assert rows["Warning"]["own_capture"] == pytest.approx(0.35)
    assert rows["Watch"]["own_capture"] == pytest.approx(0.45)       # 0.80 - 0.35
    assert rows["Normal"]["own_capture"] == pytest.approx(0.20)      # 20 of 100 outbreak weeks
    assert rows["Warning"]["share_of_weeks"] == pytest.approx(0.05)
    assert rows["Watch"]["weeks_per_city_year"] == pytest.approx(150 / (1000 / 52.1786), rel=1e-3)
    assert sum(r["own_capture"] for r in rows.values()) == pytest.approx(1.0)
    assert level_rows(None, 1) == [] and level_rows(metrics_table().iloc[0:0], 1) == []
    assert level_rows(metrics_table()[metrics_table().alert_level != "Watch"], 1) == []


def test_episode_facts():
    ep = episodes_table()
    assert episode_share(ep, 1, "Watch") == pytest.approx(0.6)
    assert first_week_flagged(ep, 1) == pytest.approx(0.8)
    assert normal_blip_share(ep, 1) == pytest.approx(9 / 11)          # 9 single, 2 multi-week
    assert episode_share(ep, 3, "Watch") is None and first_week_flagged(None, 1) is None
    assert normal_blip_share(ep.iloc[0:0], 1) is None


def test_lead_is_forecast_weeks_plus_the_reporting_delay():
    assert lead_weeks_range(1) == (1 + config.CASES_REPORT_DELAY_WEEKS,) * 2
    assert lead_weeks_range(2)[0] == 2 + config.CASES_REPORT_DELAY_WEEKS
    assert lead_weeks_range() == (2, 3)


def test_rain_gain_split_uses_the_interval_not_the_gain():
    gain = pd.DataFrame({"horizon": [1, 2, 3, 4], "gain_per_week": [0.03, 0.02, 0.014, 0.005],
                         "lo": [0.006, 0.006, -0.0003, -0.007], "hi": [0.05, 0.04, 0.03, 0.02]})
    out = rain_gain_split(gain)
    assert out["clear"] == [1, 2] and out["unclear"] == [3, 4]
    assert rain_gain_split(None) is None


def test_test_period_uses_the_doh_year_of_a_week():
    alerts = pd.DataFrame({"target_week": pd.to_datetime(["2013-12-29", "2022-12-25"]),
                           "observed_outbreak": [False, True]})
    out = evaluation_period(alerts, metrics_table(), 1)
    assert (out["first_year"], out["last_year"], out["city_weeks"]) == (2014, 2022, 1000)
    assert evaluation_period(None, None, 1) == {"first_year": None, "last_year": None,
                                          "city_weeks": None}


def test_calibration_top_compares_forecast_with_outcome():
    alerts = pd.DataFrame({"horizon": 1, "outbreak_prob": [0.6, 0.7, 0.8, 0.9, 0.1],
                           "observed_outbreak": pd.array([True, False, True, False, False],
                                                         dtype="boolean")})
    out = calibration_top(alerts, 1)
    assert out == {"weeks": 4, "forecast": pytest.approx(0.75), "observed": pytest.approx(0.5)}
    assert calibration_top(alerts, 2) is None and calibration_top(None, 1) is None


def test_other_facts():
    conf = pd.DataFrame({"adm3_pcode": ["A", "B", "C", "D"], "outbreak_weeks": [30, 20, 2, 40],
                         "auc": [0.62, 0.80, 0.5, 0.70]})
    out = city_groups_named(conf, {"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"})
    assert out == {"lower": [("Alpha", 0.62)], "case_signal": [("Gamma", 2)]}   # 0.70 is standard
    cases = pd.DataFrame({"week_start": pd.to_datetime(["2013-12-29", "2014-01-05", "2014-01-12"]),
                          "mw_year": [2014, 2014, 2014], "cases": [0, 1, 9]})
    assert case_counts(cases, 2014) == {"median": 1.0, "share_le2": pytest.approx(2 / 3)}
    assert case_counts(None, 2014) is None and case_counts(cases, None) is None
    assert no_report_weeks(pd.DataFrame({"flag": ["a"] * 3}), cases) == {"flagged": 3, "total": 3}
    assert no_report_weeks(None, cases) is None
    replay = pd.DataFrame({"event": "washi", "horizon": 1, "observed_cases": [4.0, 554.0],
                           "threshold": [1.0, 13.0], "alert_level": ["Watch", "Normal"],
                           "target_week": pd.to_datetime(["2011-12-18", "2012-01-01"])})
    peak = event_peak(replay, "washi")
    assert peak["cases"] == 554 and peak["level"] == "Normal" and peak["times"] == pytest.approx(554 / 13)
    assert event_peak(replay, "none") is None


# PENDING ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_missing_inputs_show_pending_never_a_guess():
    t = tiles([], None, auc_pair(None, 1), None, 1)
    assert t[0]["big"] == PEND and t[1]["big"] == PEND and t[3]["big"] == PEND
    assert PEND in t[2]["extra"] and PEND in t[3]["sub"]
    text = " ".join(b["text"] for b in cant_do([], None, None, None, None, None))
    assert text.count(PEND) == 5 and "None" not in text and "nan" not in text
    assert PEND in intro({"first_year": None, "last_year": None, "city_weeks": None})
    rows = level_rows(metrics_table(), 1)
    head, detail = row_text(rows[1], None, None, "next week")
    assert PEND in detail                                   # Watch row without episodes.csv
    assert "None" not in head + detail


# CLAIMS AGAINST THE FINAL OUTPUTS ++++++++++++++++++++++++++++++++++++++++++

def page_text(real, h):
    """Every sentence the page builds for horizon h, as one string."""
    rows = level_rows(real["metrics"], h)
    parts = [intro(evaluation_period(real["alerts"], real["metrics"], h))]
    for r in rows:
        parts += row_text(r, episode_share(real["episodes"], h, "Watch"),
                          normal_blip_share(real["episodes"], h), "x")
    for t in tiles(rows, first_week_flagged(real["episodes"], h), auc_pair(real["auc"], h),
                   rain_gain_split(real["rain_gain"]), h):
        parts += [t["big"], t["sub"], t["extra"]]
    names = dict(zip(real["conf"].adm3_pcode, real["conf"].city))
    for b in cant_do(rows, case_counts(real["cases"], 2014), calibration_top(real["alerts"], h),
                     city_groups_named(real["conf"], names),
                     no_report_weeks(real["flags"], real["cases"]),
                     event_peak(real["replay"], config.REPLAY_EVENT_WASHI)):
        parts += [b["title"], b["text"]]
    return " ".join(parts)


def test_next_week_claims_match_the_data(real):
    text = page_text(real, 1)
    assert "tested the forecasts on 2014–2022" in text and "5,372 city-weeks" in text
    assert "Caught 34%, about a third, of all outbreak weeks" in text          # Warning
    assert "a further 37%, about a third, of outbreak weeks (71% with Warning)" in text
    assert "52% (about half) of multi-week outbreaks started in a Watch week" in text
    assert "About 6.1× a usual week" in text and "About 2.3× a usual week" in text
    assert "7 in 10" in text and "80%" in text and "0.77" in text and "0.67" in text
    assert "Even at Warning, 58% of weeks passed without an outbreak" in text
    assert "29% of all outbreak weeks still fell in Normal weeks" in text
    assert "87% of the outbreaks that began in a Normal week lasted a single week" in text
    assert "top 5% of forecasts" in text and "next 15% of forecasts" in text
    assert "the 84 weeks forecast at 50% or more averaged 67%, and 57% became" in text


def test_in_two_weeks_claims_only_use_phrases_the_numbers_support(real):
    text = page_text(real, 2)
    assert "Caught 29% of all outbreak weeks" in text and "about a quarter" not in text
    assert "a further 40%" in text and "about a third, of outbreak weeks" not in text
    assert "50% (about half)" in text and "75%" in text and "3 weeks" in text


def test_canvas_numbers_the_data_does_not_support_never_appear(real):
    for h in (1, 2):
        text = page_text(real, h)
        for stale in ("44%", "17%", "73%", "56%", "2 of 3", "2.4×", "1–2 wks", "falls back",
                      "only about 1%", "Most outbreaks begin", "Zamboanga", "Weeks flagged"):
            assert stale not in text, stale
        assert "None" not in text and "nan" not in text and "{" not in text
        assert not any(b in text.lower() for b in ("caused by", "will get", "deadly"))


def test_rain_claim_matches_the_comparison_file(real):
    out = rain_gain_split(real["rain_gain"])
    assert out["clear"] == [1, 2] and out["unclear"] == [3, 4]
    t = tiles(level_rows(real["metrics"], 1), 0.8, auc_pair(real["auc"], 1), out, 1)
    assert "Rain clearly improves forecasts at 1 and 2 weeks ahead; at 3 and 4 weeks" in t[2]["extra"]


@pytest.mark.skipif(not (ANALYSIS / "risk_levels_summary.csv").exists(),
                    reason="../analysis not available")
def test_numbers_equal_the_modeling_teams_own_summary(real):
    theirs = pd.read_csv(ANALYSIS / "risk_levels_summary.csv")
    theirs = theirs[(theirs.version == "V1") & (theirs.group == "All cities")]
    for h in (1, 2):
        mine = {r["level"]: r for r in level_rows(real["metrics"], h)}
        for r in theirs[theirs.h == h].itertuples():
            assert mine[r.level]["rate"] == pytest.approx(r.outbreak_rate, abs=1e-6)
            assert mine[r.level]["weeks"] == r.weeks
            assert mine[r.level]["lift"] == pytest.approx(r.outbreak_rate / r.base_rate, abs=1e-4)
            assert mine[r.level]["own_capture"] == pytest.approx(r.share_of_outbreak_weeks,
                                                                 abs=1e-6)
            # weeks a year per city: ours uses tested weeks / 52.18; theirs 106 city-years
            if r.level != "Normal":      # theirs counts 106 city-years, ours weeks / 52.18
                assert mine[r.level]["weeks_per_city_year"] == pytest.approx(
                    r.weeks_per_city_year, abs=0.3)
    overall = pd.read_csv(ANALYSIS / "risk_levels_overall.csv")
    overall = overall[(overall.version == "V1") & (overall.group == "All cities")]
    for r in overall.itertuples():
        mine = level_rows(real["metrics"], r.h)
        assert mine[1]["cum_capture"] == pytest.approx(r.caught_watch_or_warning, abs=1e-6)
        assert mine[0]["cum_capture"] == pytest.approx(r.caught_warning, abs=1e-6)
    eps = pd.read_csv(ANALYSIS / "risk_levels_episodes.csv")
    for h in (1, 2):
        row = eps[(eps.version == "V1") & (eps.h == h) & (eps.episode == "2+ weeks")
                  & (eps.level == "Normal")]
        assert first_week_flagged(real["episodes"], h) == pytest.approx(1 - row.share.iloc[0])
