"""Tests for src/views.py: levels, ranking, observed context, snapshot and wording."""

import numpy as np
import pandas as pd
import pytest

from app import config
from src.views import (flood_alert_weeks_left, watch_weeks_per_year, RAIN_ABOUT, RAIN_DRIER, RAIN_WETTER, RAIN_WETTEST, SNAPSHOT_COLUMNS,
                       TIMELINE_COLUMNS, case_signal_cities, cases_week_start, city_group,
                       city_snapshot, confidence_groups, display_levels, fmt_times,
                       heavy_rain_mm, lag_caption, latest_cases, level_descriptions,
                       level_rank, level_sentence, peak_caption, place_label, rain_context,
                       rank_cities, risk_timeline, risk_vs_usual, top_flood_barangays,
                       trend_summary, usual_risk_text)

# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

ORIGIN = pd.Timestamp("2015-03-01")
LOW = "PH072230000"                         # Mandaue: case signal only (also in the fallback)
LATEST = cases_week_start(ORIGIN)           # latest reported week: 2015-02-15
# A: standard, B: lower confidence, LOW: too few outbreak weeks.
CONF = pd.DataFrame({"adm3_pcode": ["A", "B", LOW], "outbreak_weeks": [40, 20, 3],
                     "auc": [0.8, 0.6, 0.9]})


@pytest.fixture
def cities():
    return pd.DataFrame({"adm3_pcode": ["A", "B", LOW], "city_name": ["Alpha", "Beta", "Gamma"],
                         "province": ["P", "Q", "R"],
                         "region": ["Region VII", "Region I", "Region V"],
                         "lat": [10.0, 16.0, 13.0], "lon": [124.0, 120.0, 123.0]})


@pytest.fixture
def alerts():
    """A: Watch now, Warning in week 3; B: Normal; LOW: Warning (but low-data)."""
    rows = []
    for origin, a_level in [(ORIGIN - pd.Timedelta(days=7), "Normal"), (ORIGIN, "Watch")]:
        for h in (1, 2, 3):
            target = origin + pd.Timedelta(weeks=h - 1)
            level = "Warning" if (origin == ORIGIN and h == 3) else a_level
            rows.append(("A", origin, h, target, 0.15 if level == "Watch" else 0.3,
                         2.5, level, 2.0))
            rows.append(("B", origin, h, target, 0.02, 0.8, "Normal", 3.0))
            rows.append((LOW, origin, h, target, 0.6, 9.0, "Warning", 1.0))
    return pd.DataFrame(rows, columns=["adm3_pcode", "origin_week", "horizon", "target_week",
                                       "outbreak_prob", "rr_vs_usual", "alert_level",
                                       "threshold"])


@pytest.fixture
def cases():
    """The latest reported week (2 weeks before ORIGIN), plus an unreported last week."""
    return pd.DataFrame({"adm3_pcode": ["A", "B", LOW, "A"],
                         "week_start": [LATEST] * 3 + [ORIGIN - pd.Timedelta(weeks=1)],
                         "cases": pd.array([4, 0, None, 99], dtype="Int64"),
                         "reporting_flag": [None, None, "non_reporting", None]})


@pytest.fixture
def lines():
    return pd.DataFrame({"adm3_pcode": ["A", "B"], "week_start": [LATEST] * 2,
                         "threshold": [2.6, 1.0]})


@pytest.fixture
def rain():
    rows = []
    for year in (2013, 2014, 2015):
        # MW8 of each year; 2015's MW8 starts 2015-02-22 (the week before ORIGIN)
        start = pd.Timestamp({2013: "2013-02-17", 2014: "2014-02-16", 2015: "2015-02-22"}[year])
        rows += [("A", start, year, 8, {2013: 10, 2014: 30, 2015: 60}[year]),
                 ("B", start, year, 8, 20.0)]
    # One very wet week each, so the cities' wettest-5% lines sit far above MW8.
    rows += [("A", pd.Timestamp("2013-07-21"), 2013, 30, 400.0),
             ("B", pd.Timestamp("2013-07-21"), 2013, 30, 400.0)]
    return pd.DataFrame(rows, columns=["adm3_pcode", "week_start", "mw_year", "mw_week", "rain_mm"])


@pytest.fixture
def hazard():
    return pd.DataFrame({"adm3_pcode": ["A", "B", LOW],
                         "pct_area_flood_hazard_100yr_high": [5.0, 40.0, 1.0]})


# LEVELS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_level_rank_orders_forecast_levels_only():
    levels = pd.Series(["Warning", "Normal", "Watch", "No report", None])
    assert level_rank(levels).tolist() == [2, 0, 1, -1, -1]


def test_display_levels_case_signal_and_no_report():
    levels = pd.Series(["Warning", "No report", "Watch", None, None])
    pcodes = pd.Series([LOW, LOW, "A", "A", LOW])
    assert display_levels(levels, pcodes, {LOW}).tolist() == [
        config.CASE_SIGNAL_LEVEL, config.NO_REPORT_LEVEL, "Watch", config.NO_FORECAST_LEVEL,
        config.NO_FORECAST_LEVEL]
    assert display_levels(levels, pcodes).tolist()[0] == "Warning"   # no case-signal set


# CITY CONFIDENCE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_confidence_groups_from_data():
    groups = confidence_groups(CONF)
    assert groups == {"A": "standard", "B": "lower", LOW: "case_signal"}
    assert case_signal_cities(groups) == {LOW}
    assert city_group(groups, "unknown") == "standard"


def test_confidence_groups_rules_use_config_thresholds():
    edge = pd.DataFrame({"adm3_pcode": ["x", "y", "z"],
                         "outbreak_weeks": [config.CASE_SIGNAL_MAX_OUTBREAK_WEEKS] * 3,
                         "auc": [config.LOWER_CONFIDENCE_AUC, 0.69, 0.2]})
    assert confidence_groups(edge) == {"x": "standard", "y": "lower", "z": "lower"}


def test_confidence_groups_fallback_when_file_missing():
    assert confidence_groups(None) == config.CONFIDENCE_FALLBACK
    assert confidence_groups(CONF.iloc[0:0], {"A": "lower"}) == {"A": "lower"}


def test_final_model_file_gives_the_groups():
    # The final model's per-city test (stage 5 washi_by_city.csv, pooled_ar4_lvl_nw).
    final = pd.DataFrame({
        "adm3_pcode": ["PH112402000", "PH063022000", "PH015518000", "PH097332000",
                       "PH137503000", "PH104305000", "PH137401000", "PH137603000",
                       "PH083747000", "PH050506000", "PH072230000", "PH034919000"],
        "outbreak_weeks": [87, 61, 45, 44, 39, 29, 24, 19, 15, 3, 3, 1],
        "auc": [0.711, 0.850, 0.874, 0.704, 0.792, 0.618, 0.899, 0.832, 0.684, 0.958, 0.682,
                0.610]})
    groups = confidence_groups(final)
    assert {p for p, g in groups.items() if g == "lower"} == {
        "PH104305000", "PH083747000"}                            # CDO, Tacloban
    assert groups["PH097332000"] == "standard"                   # Zamboanga: 0.704 >= 0.70
    assert case_signal_cities(groups) == {
        "PH034919000", "PH050506000", "PH072230000"}            # Palayan, Legazpi, Mandaue
    assert groups == config.CONFIDENCE_FALLBACK | {
        p: "standard" for p in groups if p not in config.CONFIDENCE_FALLBACK}


@pytest.mark.parametrize("province, label", [("NCR, Third District", "Metro Manila"),
                                             ("Pangasinan", "Pangasinan"), (None, "")])
def test_place_label(province, label):
    assert place_label(province) == label


@pytest.mark.parametrize("value, text", [(1.43, "1.4×"), (4.07, "4×"), (None, None),
                                         (np.nan, None)])
def test_fmt_times(value, text):
    assert fmt_times(value) == text


@pytest.mark.parametrize("rr, text", [(2.5, "≈2× usual risk"), (1.4, "≈1.4× usual risk"),
                                      (0.5, "Below usual risk"), (40, "Over 10× usual risk"),
                                      (np.nan, None)])
def test_usual_risk_text(rr, text):
    assert usual_risk_text(rr) == text


@pytest.mark.parametrize("level, prob, text", [
    ("Warning", 0.28, "≈4× usual risk"), ("Watch", 0.14, "≈2× usual risk"),
    ("Normal", 0.09, "At or below usual risk"), (config.CASE_SIGNAL_LEVEL, 0.5, None),
    ("Warning", np.nan, None), ("Warning", 0.9, "Over 10× usual risk"),
])
def test_risk_vs_usual_agrees_with_level(level, prob, text):
    assert risk_vs_usual(level, prob, 0.068) == text


def test_level_descriptions_use_metrics_over_placeholders():
    placeholders = level_descriptions(None, 1)
    assert placeholders["Warning"]["meaning"].startswith("Outbreak week is about 6×")
    assert placeholders["Warning"]["track"] == ("In testing, 44% of Warning weeks became "
                                                "outbreak weeks.")
    assert not placeholders["Warning"]["from_metrics"]
    metrics = pd.DataFrame({"horizon": [1, 1, 1, 2], "alert_level": ["Normal", "Watch",
                                                                     "Warning", "Warning"],
                            "hit_rate": [0.03, 0.1, 0.28, 0.9], "base_rate": [0.07] * 4,
                            "lift": [0.5, 1.4, 4.07, 9.0], "n_weeks": [10, 5, 3, 3],
                            "capture_rate": [1.0, 0.6, 0.47, 0.4]})
    out = level_descriptions(metrics, 1)
    assert out["Warning"]["meaning"] == "Outbreak week is about 4× as likely as usual. Act now."
    assert out["Watch"]["meaning"].startswith("Risk is raised, about 1.4× a usual week")
    assert out["Warning"]["track"] == "In testing, 28% of Warning weeks became outbreak weeks."
    assert out["Normal"]["track"].endswith("(usual: 7%).")
    assert out["Warning"]["base_rate"] == 0.07 and placeholders["Watch"]["base_rate"] == 0.068
    assert out[config.NO_REPORT_LEVEL]["track"] is None
    assert out[config.CASE_SIGNAL_LEVEL]["color"] == config.LEVEL_COLORS["Case signal only"]


# RANKING ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_rank_by_outbreak_prob_missing_last():
    snap = pd.DataFrame({"city_name": list("wxyz"), "outbreak_prob": [0.1, np.nan, 0.5, 0.1]})
    ranked = rank_cities(snap)
    assert ranked.city_name.tolist() == ["y", "w", "z", "x"]
    assert ranked["rank"].tolist() == [1, 2, 3, 4]


# OBSERVED CONTEXT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_rain_context_vs_same_week_other_years(rain):
    out = rain_context(rain, ORIGIN).set_index("adm3_pcode")
    assert out.loc["A", "rain_week_mm"] == 60
    assert out.loc["A", "rain_usual_mm"] == 20         # mean of 10 and 30
    assert out.loc["A", "rain_status"] == RAIN_WETTER
    assert out.loc["B", "rain_status"] == RAIN_ABOUT


def test_rain_context_wettest_and_drier(rain):
    wet = rain.copy()
    wet.loc[(wet.adm3_pcode == "A") & (wet.mw_year == 2015) & (wet.mw_week == 8),
            "rain_mm"] = 500.0                           # above A's wettest-5% line
    wet.loc[(wet.adm3_pcode == "B") & (wet.mw_year == 2015) & (wet.mw_week == 8),
            "rain_mm"] = 5.0                             # a quarter of B's usual 20 mm
    out = rain_context(wet, ORIGIN).set_index("adm3_pcode")
    assert out.loc["A", "rain_status"] == RAIN_WETTEST
    assert out.loc["B", "rain_status"] == RAIN_DRIER


def test_rain_context_missing_week_is_empty(rain):
    assert rain_context(rain, pd.Timestamp("2016-06-05")).empty


def test_cases_week_start_is_two_weeks_back():
    assert cases_week_start(ORIGIN) == pd.Timestamp("2015-02-15")
    assert cases_week_start(ORIGIN, delay=0) == ORIGIN - pd.Timedelta(weeks=1)


def test_latest_cases_uses_the_latest_reported_week(cases, lines):
    out = latest_cases(cases, ORIGIN, lines).set_index("adm3_pcode")
    assert out.loc["A", "latest_cases"] == 4.0                  # not the unreported 99
    assert out.loc[LOW, "latest_flag"] == "non_reporting"
    assert out.loc["A", "unusual_at"] == 3 and out.loc["B", "unusual_at"] == 2
    assert np.isnan(out.loc[LOW, "unusual_at"])                 # no line for that city
    assert latest_cases(cases, ORIGIN).unusual_at.isna().all()  # no thresholds given
    assert latest_cases(cases, ORIGIN + pd.Timedelta(weeks=5)).empty


# SNAPSHOT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_city_snapshot(alerts, cities, cases, rain, hazard, lines):
    snap = city_snapshot(alerts, cities, cases, rain, hazard, ORIGIN, 1, thresholds=lines,
                         confidence=CONF, horizons=(1, 2, 3))
    assert list(snap.columns) == SNAPSHOT_COLUMNS
    snap = snap.set_index("adm3_pcode")
    assert snap.loc["A", "alert_level"] == "Watch" and snap.loc["A", "prev_level"] == "Normal"
    assert snap.loc["A", "peak_level"] == "Warning" and snap.loc["A", "peak_horizon"] == 3
    assert snap.loc[LOW, "alert_level"] == config.CASE_SIGNAL_LEVEL    # too few cases
    assert snap.loc[LOW, "forecast_level"] == "Warning"                # still recorded
    assert snap.loc[LOW, "rank"] == 1                                   # highest chance
    assert snap.loc["B", "hazard_pct"] == 40.0 and snap.loc["A", "latest_cases"] == 4.0
    assert snap.loc["A", "unusual_at"] == 3 and snap.loc["A", "cases_week"] == LATEST
    assert snap.confidence.to_dict() == {"A": "standard", "B": "lower", LOW: "case_signal"}
    assert snap.loc["B", "city_auc"] == 0.6


def test_city_snapshot_peak_only_over_shown_horizons(alerts, cities, cases, rain, hazard):
    snap = city_snapshot(alerts, cities, cases, rain, hazard, ORIGIN, 1, horizons=(1, 2))
    assert snap.set_index("adm3_pcode").loc["A", "peak_level"] == "Watch"   # week 3 hidden


def test_city_snapshot_without_confidence_file(alerts, cities, cases, rain, hazard):
    snap = city_snapshot(alerts, cities, cases, rain, hazard, ORIGIN, 1).set_index("adm3_pcode")
    assert snap.loc[LOW, "alert_level"] == config.CASE_SIGNAL_LEVEL    # config fallback
    assert snap.loc["A", "confidence"] == "standard" and snap.city_auc.isna().all()


def test_city_snapshot_missing_origin_shows_no_forecast(alerts, cities, cases, rain, hazard):
    snap = city_snapshot(alerts, cities, cases, rain, hazard, pd.Timestamp("2016-01-03"), 1)
    assert set(snap.alert_level) == {config.NO_FORECAST_LEVEL}
    assert snap.outbreak_prob.isna().all() and snap.prev_level.isna().all()


# WORDING ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.mark.parametrize("now, before, peak, h, expected", [
    ("Watch", "Normal", "Warning", 3, "Up from Normal last week. Rises to Warning in week 3."),
    ("Normal", "Warning", "Normal", 1,
     "Down from Warning last week. No raised risk expected in the next 3 weeks."),
    ("Warning", "Warning", "Warning", 1, "Same level as last week."),
    ("Case signal only", "Normal", "Warning", 2, ""),
    ("Watch", None, None, None, ""),
])
def test_trend_summary(now, before, peak, h, expected):
    assert trend_summary(now, before, peak, h) == expected


# CITY PANEL +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_level_sentence_uses_city_multiplier():
    info = level_descriptions(None, 1)["Warning"]          # placeholder lift 6×
    assert level_sentence("Warning", info, 0.34) == (
        "Outbreak week is about 5× as likely as usual. Act now.")   # 0.34 / 0.068
    assert level_sentence("Warning", info, np.nan) == info["meaning"]
    normal = level_descriptions(None, 1)["Normal"]
    assert level_sentence("Normal", normal, 0.05) == normal["meaning"]


def test_level_sentence_case_signal_says_how_many_cases():
    info = level_descriptions(None, 1)[config.CASE_SIGNAL_LEVEL]
    assert level_sentence(config.CASE_SIGNAL_LEVEL, info, 0.5, 2.0) == (
        "Too few cases here to forecast a level. Watch the weekly case count instead: 2 or "
        "more reported cases in a week is unusual here.")
    assert level_sentence(config.CASE_SIGNAL_LEVEL, info, 0.5, np.nan) == info["meaning"]


def test_risk_timeline(alerts, rain):
    weekly = pd.DataFrame({"adm3_pcode": "A",
                           "week_start": pd.date_range(ORIGIN - pd.Timedelta(weeks=10),
                                                       periods=10, freq="7D"),
                           "rain_mm": [10.0] * 9 + [200.0]})
    out = risk_timeline(weekly, alerts, "A", ORIGIN, 0.05, heavy_mm=150.0, horizons=(1, 2, 3))
    assert list(out.columns) == TIMELINE_COLUMNS and len(out) == 13
    past, ahead = out[~out.is_future], out[out.is_future]
    assert past.week_start.max() == ORIGIN - pd.Timedelta(weeks=1)
    assert past.heavy.tolist() == [False] * 9 + [True]
    assert ahead.horizon.tolist() == [1, 2, 3]
    assert ahead.multiplier.tolist() == pytest.approx([3.0, 3.0, 6.0])  # 0.15/0.05, 0.3/0.05
    assert ahead.alert_level.tolist() == ["Watch", "Watch", "Warning"]
    assert ahead.rain_mm.isna().all() and past.multiplier.isna().all()
    # Past weeks: the level shown that week (its next-week forecast), else No forecast.
    assert past.alert_level.iloc[-1] == "Normal"
    assert set(past.alert_level.iloc[:-1]) == {config.NO_FORECAST_LEVEL}
    assert risk_timeline(weekly, alerts, "A", ORIGIN, None).multiplier.isna().all()


def test_risk_timeline_drawer_view(alerts, rain):
    weekly = pd.DataFrame({"adm3_pcode": LOW,
                           "week_start": pd.date_range(ORIGIN - pd.Timedelta(weeks=6),
                                                       periods=6, freq="7D"),
                           "rain_mm": 10.0})
    out = risk_timeline(weekly, alerts, LOW, ORIGIN, 0.05, weeks_back=6, case_signal={LOW})
    assert len(out) == 8 and out.is_future.sum() == len(config.HORIZONS)
    assert set(out.alert_level) == {config.CASE_SIGNAL_LEVEL, config.NO_FORECAST_LEVEL}


def test_heavy_rain_mm():
    weekly = pd.DataFrame({"adm3_pcode": ["A"] * 100 + ["B"],
                           "rain_mm": list(range(100)) + [5.0]})
    assert heavy_rain_mm(weekly, "A") == pytest.approx(94.05)
    assert np.isnan(heavy_rain_mm(weekly, "Z"))


def test_lag_caption_from_curve_and_fallback():
    curve = pd.DataFrame({"lag_weeks": range(6), "rr_p95": [0.99, 1.41, 1.77, 1.71, 1.4, 1.2],
                          "rr_p99": 2.0})
    assert lag_caption(curve) == ("Heavy rain raises risk +41% the next week and peaks about "
                                  "2 weeks later.")
    assert lag_caption(pd.DataFrame(columns=["lag_weeks", "rr_p95"])) == \
        config.LAG_CAPTION_FALLBACK


def test_peak_caption_from_curve_and_fallback():
    curve = pd.DataFrame({"lag_weeks": range(4), "rr_p95": [0.99, 1.41, 1.77, 1.5]})
    assert peak_caption(curve) == "Risk usually peaks 2 weeks after heavy rain."
    assert peak_caption(curve.assign(rr_p95=[1, 2, 1, 1])) == (
        "Risk usually peaks 1 week after heavy rain.")
    assert peak_caption(None) == config.PEAK_CAPTION_FALLBACK


def test_top_flood_barangays_skips_zero_share():
    rank = pd.DataFrame({"adm3_pcode": ["A"] * 7, "rank": range(1, 8),
                         "brgy_name": list("abcdefg"),
                         "high_hazard_pct": [50, 40, 30, 20, 10, 5, 0]})
    assert top_flood_barangays(rank, "A").brgy_name.tolist() == list("abcde")
    assert top_flood_barangays(rank.assign(high_hazard_pct=[9, 0, 0, 0, 0, 0, 0]),
                               "A").brgy_name.tolist() == ["a"]
    assert top_flood_barangays(rank, "Z").empty and top_flood_barangays(None, "A").empty


def test_flood_alert_weeks_left():
    start = pd.Timestamp("2018-07-08")
    assert [flood_alert_weeks_left(start, start + pd.Timedelta(weeks=k)) for k in range(-1, 6)]         == [0, 4, 3, 2, 1, 0, 0]
    assert flood_alert_weeks_left(None, start) == 0


def test_watch_weeks_per_year(alerts):
    # A at h1: one Watch week out of two forecast weeks -> half the weeks of a year.
    assert watch_weeks_per_year(alerts, "A", 1) == pytest.approx(365.25 / 7 / 2)
    assert np.isnan(watch_weeks_per_year(alerts, "Z", 1))
