"""Tests for src/risk.py: the app-side DOH thresholds (fallback only)."""

import numpy as np
import pandas as pd
import pytest

from app import config
from src.risk import THRESHOLD_COLUMNS, compute_thresholds


# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def make_cases(values_by_year, week=10, pcode="C1", extra_weeks=(11,)):
    """Cases table with `week` set per year and other weeks set to 0."""
    rows = []
    for year, value in values_by_year.items():
        rows.append((pcode, year, week, value))
        rows += [(pcode, year, w, 0) for w in extra_weeks]
    df = pd.DataFrame(rows, columns=["adm3_pcode", "mw_year", "mw_week", "cases"])
    df["cases"] = df.cases.astype("Int64")
    return df


def row(thr, year, week=10):
    return thr[(thr.mw_year == year) & (thr.mw_week == week)].iloc[0]


# THRESHOLDS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_uses_previous_five_years_only():
    cases = make_cases({2008: 100, 2009: 1, 2010: 2, 2011: 3, 2012: 4, 2013: 5})
    r = row(compute_thresholds(cases, years=[2014]), 2014)
    vals = np.array([1, 2, 3, 4, 5], dtype=float)   # 2008's 100 is outside the window
    assert r.n_years == 5
    assert r.seasonal_mean == pytest.approx(vals.mean())
    assert r.sd == pytest.approx(vals.std(ddof=1))
    assert r.alert_threshold == pytest.approx(vals.mean() + vals.std(ddof=1))
    assert r.epidemic_threshold == pytest.approx(vals.mean() + 2 * vals.std(ddof=1))


def test_falls_back_to_three_years_then_nan():
    cases = make_cases({2008: 1, 2009: 2, 2010: 6})
    thr = compute_thresholds(cases, years=[2010, 2011])
    assert np.isnan(row(thr, 2010).epidemic_threshold)        # only 2 prior years
    r = row(thr, 2011)
    assert r.n_years == 3 and r.seasonal_mean == pytest.approx(3.0)


def test_na_years_are_skipped_not_zero():
    cases = make_cases({2008: 2, 2009: pd.NA, 2010: 4, 2011: 6})
    r = row(compute_thresholds(cases, years=[2012]), 2012)
    assert r.n_years == 3 and r.seasonal_mean == pytest.approx(4.0)


def test_mw53_uses_mw52_history():
    cases = make_cases({2005: 1, 2006: 2, 2007: 3}, week=52, extra_weeks=())
    thr = compute_thresholds(cases, years=[2008])               # 2008 has 53 MWs
    assert row(thr, 2008, 53).seasonal_mean == pytest.approx(2.0)
    assert row(thr, 2008, 53).week_start == pd.Timestamp("2008-12-28")


def test_cutoffs_come_from_arguments():
    cases = make_cases({2008: 0, 2009: 2, 2010: 4})
    r = row(compute_thresholds(cases, years=[2011], alert_sd=0.5, epidemic_sd=3), 2011)
    assert r.alert_threshold == pytest.approx(2 + 0.5 * 2)
    assert r.epidemic_threshold == pytest.approx(2 + 3 * 2)


def test_week_start_is_sunday_and_columns():
    thr = compute_thresholds(make_cases({2008: 1, 2009: 1, 2010: 1}), years=[2011])
    assert list(thr.columns) == THRESHOLD_COLUMNS
    assert (thr.week_start.dt.dayofweek == 6).all()
    assert row(thr, 2011).week_start == pd.Timestamp("2011-03-06")  # MW1 2011 = Jan 2


def test_empty_input():
    empty = pd.DataFrame(columns=["adm3_pcode", "mw_year", "mw_week", "cases"])
    assert compute_thresholds(empty).empty
