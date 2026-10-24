"""Tests for src/weeks.py: DOH morbidity weeks and CCHAIN label alignment."""

import datetime as dt

import pandas as pd
import pytest

from src.weeks import (SHIFT_YEARS, align_cchain_labels, morbidity_week, mw1_start,
                       sunday_on_or_before, week_grid, week_starts, weeks_in_year)


# MORBIDITY WEEK ARITHMETIC ++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.mark.parametrize("year, expected", [
    (2008, dt.date(2007, 12, 30)),  # Jan 1 Tue -> week holds 5 days of 2008
    (2009, dt.date(2009, 1, 4)),    # Jan 1 Thu -> only 3 days, so next Sunday
    (2012, dt.date(2012, 1, 1)),    # Jan 1 is a Sunday
    (2013, dt.date(2012, 12, 30)),
    (2020, dt.date(2019, 12, 29)),
])
def test_mw1_start(year, expected):
    assert mw1_start(year) == expected
    assert mw1_start(year).weekday() == 6


def test_53_week_years_match_modeling_decisions():
    long_years = {y for y in range(2008, 2023) if weeks_in_year(y) == 53}
    assert long_years == {2008, 2014, 2020}


def test_sunday_on_or_before():
    assert sunday_on_or_before(dt.date(2024, 5, 15)) == dt.date(2024, 5, 12)
    assert sunday_on_or_before(dt.date(2024, 5, 12)) == dt.date(2024, 5, 12)


def test_morbidity_week_year_boundaries():
    assert morbidity_week(dt.date(2012, 12, 30)) == (2013, 1)
    assert morbidity_week(dt.date(2008, 12, 28)) == (2008, 53)
    assert morbidity_week(dt.date(2009, 1, 4)) == (2009, 1)
    assert morbidity_week(pd.Timestamp("2011-12-25")) == (2011, 52)


def test_morbidity_week_rejects_non_sunday():
    with pytest.raises(ValueError):
        morbidity_week(dt.date(2012, 1, 2))


# CCHAIN LABEL ALIGNMENT +++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_align_normal_and_shift_years():
    labels = pd.Series(pd.to_datetime(["2009-01-05", "2008-01-07", "2013-01-07"]))
    out = align_cchain_labels(labels)
    assert list(out.dt.date) == [dt.date(2009, 1, 4), dt.date(2007, 12, 30),
                                 dt.date(2012, 12, 30)]
    assert (out.dt.dayofweek == 6).all()


def test_first_label_each_year_maps_to_mw1():
    """The real first CCHAIN label of every year lands exactly on MW1."""
    first = pd.date_range("2008-01-07", "2022-12-26", freq="7D")
    first = first[~first.isin(pd.to_datetime(["2012-12-31", "2018-01-01"]))]
    aligned = align_cchain_labels(pd.Series(first))
    by_year = pd.Series(aligned.values, index=first.year).groupby(level=0).min()
    for year, start in by_year.items():
        assert start.date() == mw1_start(year), year


def test_aligned_raw_grid_has_no_duplicates_and_only_wk53_gaps():
    """Aligning the full raw label grid leaves gaps only at week 53."""
    raw = pd.date_range("2008-01-07", "2022-12-26", freq="7D")
    raw = raw[~raw.isin(pd.to_datetime(["2012-12-31", "2018-01-01"]))]
    aligned = align_cchain_labels(pd.Series(raw))
    assert aligned.is_unique
    grid = week_grid(aligned.min(), aligned.max())
    gaps = grid[~grid.week_start.isin(aligned)]
    assert set(zip(gaps.mw_year, gaps.mw_week)) == {(2008, 53), (2014, 53), (2020, 53)}


def test_align_rejects_non_monday():
    with pytest.raises(ValueError):
        align_cchain_labels(pd.Series(pd.to_datetime(["2009-01-04"])))


def test_shift_years_constant():
    assert SHIFT_YEARS == {2008, 2013, 2014, 2018, 2019, 2020}


def test_week_grid_columns_and_empty():
    g = week_grid("2012-12-23", "2013-01-06")
    assert list(g.columns) == ["week_start", "mw_year", "mw_week"]
    assert list(zip(g.mw_year, g.mw_week)) == [(2012, 52), (2013, 1), (2013, 2)]
    assert week_grid("2013-01-06", "2012-12-23").empty


# MODELING-TEAM WEEK KEYS ++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_week_starts_maps_year_and_mw_to_sundays():
    out = week_starts([2014, 2014, 2020], [1, 2, 53])
    assert out.tolist() == [pd.Timestamp("2013-12-29"), pd.Timestamp("2014-01-05"),
                            pd.Timestamp("2020-12-27")]
    assert week_starts([], []).empty


def test_week_starts_rejects_impossible_weeks():
    with pytest.raises(ValueError, match="MW 53 does not exist in 2019"):
        week_starts([2019], [53])
