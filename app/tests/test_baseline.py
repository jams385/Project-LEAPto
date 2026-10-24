"""Tests for src/baseline.py: labelled placeholders in the contract-v2 schemas."""

import numpy as np
import pandas as pd
import pytest

from app import config
from src.baseline import (ALERT_COLUMNS, baseline_reporting_flags, build_baseline_alerts,
                          compute_level_metrics, last_week_only_auc, seasonal_exceedance)
from src.contract import PARTS, assign_levels
from src.weeks import week_grid


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.fixture
def cases():
    """One city, 2008-2013, cases = MW number in every year except 2013 = 100."""
    grid = week_grid("2007-12-30", "2013-12-22")
    df = grid.assign(adm3_pcode="C1", city_name="City 1")
    df["cases"] = df.mw_week.where(df.mw_year < 2013, 100).astype("Int64")
    return df


# SEASONAL CHANCE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def flat_thresholds(cases, value):
    return cases[["adm3_pcode", "week_start"]].assign(threshold=value)


def test_chance_pools_neighbouring_weeks_of_prior_years(cases):
    # 2013 MW10: pool = MW 9, 10, 11 of 2008-2012 (values 9-11); 2013's 100s never leak in.
    target = [pd.Timestamp("2013-03-03")]
    assert seasonal_exceedance(cases, flat_thresholds(cases, 10.0), target) \
        .outbreak_prob.iloc[0] == pytest.approx(1 / 3)          # only the 11s are > 10
    assert seasonal_exceedance(cases, flat_thresholds(cases, 50.0), target) \
        .outbreak_prob.iloc[0] == 0.0


def test_targets_without_history_or_threshold_are_dropped(cases):
    thr = flat_thresholds(cases, 5.0)
    out = seasonal_exceedance(cases, thr, [pd.Timestamp("2010-03-07"),
                                           pd.Timestamp("2011-03-06")])
    assert out.target_week.tolist() == [pd.Timestamp("2011-03-06")]  # 2010 has 2 prior yrs
    no_thr = thr[thr.week_start != pd.Timestamp("2011-03-06")]
    assert seasonal_exceedance(cases, no_thr, [pd.Timestamp("2011-03-06")]).empty
    assert seasonal_exceedance(cases.iloc[0:0], thr, [pd.Timestamp("2011-03-06")]).empty


# CONTRACT V2 PLACEHOLDERS +++++++++++++++++++++++++++++++++++++++++++++++++++

def model_thresholds(cases, value=20.0):
    return cases[["adm3_pcode", "week_start"]].assign(threshold=value)


def test_baseline_alerts_schema_and_validator(cases):
    flags = pd.DataFrame({"adm3_pcode": ["C1"], "week_start": [pd.Timestamp("2013-03-03")],
                          "flag": ["non_reporting"]})
    out = build_baseline_alerts(cases, model_thresholds(cases), flags)
    assert list(out.columns) == ALERT_COLUMNS
    assert set(out.horizon) == set(config.ALERT_HORIZONS) and out.alert_level.isna().all()
    assert out.model_version.str.startswith("PLACEHOLDER").all()
    assert PARTS["alerts"].validator(out.copy()) is not None
    flagged = out[out.target_week == pd.Timestamp("2013-03-03")]
    assert set(flagged.reporting_flag) == {"non_reporting"}
    assert flagged.observed_outbreak.isna().all()
    # MW11 history is 10-12 cases (below 20) but 2013 has 100: an unforeseen outbreak
    later = out[(out.target_week == pd.Timestamp("2013-03-10")) & (out.horizon == 1)].iloc[0]
    assert bool(later.observed_outbreak) and later.outbreak_prob == 0.0


def test_baseline_alerts_empty_input(cases):
    assert build_baseline_alerts(cases.iloc[0:0], model_thresholds(cases)).empty


def toy_alerts(levels, outbreaks, horizon=1):
    weeks = pd.date_range("2015-01-04", periods=len(levels), freq="7D")
    return pd.DataFrame({"adm3_pcode": "C1", "horizon": horizon, "target_week": weeks,
                         "alert_level": levels,
                         "observed_outbreak": pd.array(outbreaks, dtype="boolean")})


def test_level_metrics_rates_and_lead():
    lv = ["Normal", "Watch", "Warning", "Warning", "Normal", "Normal", "Watch", "Normal"]
    ob = [False, False, False, True, False, False, True, False]
    m = compute_level_metrics(toy_alerts(lv, ob, horizon=2),
                              {"Watch": 0.1, "Warning": 0.2}).set_index("alert_level")
    assert m.loc["Warning", "n_weeks"] == 2 and m.loc["Warning", "hit_rate"] == 0.5
    assert m.loc["Warning", "base_rate"] == pytest.approx(2 / 8)
    assert m.loc["Warning", "lift"] == pytest.approx(2.0)
    assert m.loc["Watch", "capture_rate"] == 1.0 and m.loc["Warning", "capture_rate"] == 0.5
    # Warning episode at week 4: 1 earlier Warning week + (horizon 2 - 1) = 2
    assert m.loc["Warning", "median_lead_weeks"] == 2.0
    # >= Watch: week 4 (2 earlier weeks + 1 = 3) and week 7 (0 + 1 = 1) -> median 2
    assert m.loc["Watch", "median_lead_weeks"] == 2.0
    assert np.isnan(m.loc["Normal", "median_lead_weeks"])
    assert m.prob_cutoff.to_dict() == {"Normal": 0.0, "Watch": 0.1, "Warning": 0.2}


def test_level_metrics_skip_unknown_outcomes_and_display_states():
    m = compute_level_metrics(toy_alerts(["Warning", "No report", "Watch"],
                                         [True, None, None]))
    assert m.n_weeks.sum() == 1 and m.prob_cutoff.isna().all()
    assert compute_level_metrics(toy_alerts(["No report"], [None])).empty


def test_level_metrics_pass_the_validator(cases):
    alerts = assign_levels(build_baseline_alerts(cases, model_thresholds(cases, 5.0)))
    m = compute_level_metrics(alerts, {"Watch": 0.1, "Warning": 0.2})
    assert PARTS["level_metrics"].validator(m.copy()) == []


def test_last_week_only_auc_uses_delayed_count():
    weeks = pd.date_range("2015-01-04", periods=12, freq="7D")
    cases = pd.DataFrame({"adm3_pcode": "C1", "week_start": weeks,
                          "cases": [0, 0, 9, 0, 0, 9, 0, 0, 9, 0, 0, 9]})
    # outbreak exactly 2 weeks after each 9 -> perfectly ranked at horizon 1
    outbreak = cases.cases.shift(2).fillna(0).eq(9)
    alerts = pd.DataFrame({"adm3_pcode": "C1", "horizon": 1, "target_week": weeks,
                           "outbreak_prob": 0.1,
                           "observed_outbreak": pd.array(outbreak, dtype="boolean")})
    out = last_week_only_auc(alerts, cases, horizons=(1,))
    assert out.auc.iloc[0] == 1.0 and out.n_weeks.iloc[0] == 10
    assert PARTS["auc"].validator(out.copy()) == ["auc.csv has no rows for "
                                                  "['final_model']"]


def test_baseline_reporting_flags(cases):
    out = baseline_reporting_flags(cases.assign(cases=cases.cases.mask(cases.mw_week == 5)))
    assert set(out.flag) == {"non_reporting"} and len(out) == 6
