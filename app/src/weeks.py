"""DOH morbidity-week helpers and the CCHAIN week-label alignment.

DOH morbidity weeks (MW) run Sunday to Saturday. MW1 of a year is the first
Sun-Sat week with at least 4 of its days in that year, so some years have 53 MWs.

CCHAIN's PIDSR file labels each week with a Monday. In most years that Monday
is the day after the MW's Sunday start. In SHIFT_YEARS the label is one week
late (8 days after the true start), as decided by the modeling team and
confirmed against the raw labels during data profiling.
"""

import datetime as dt

import numpy as np
import pandas as pd

# CONSTANTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# Calendar years whose CCHAIN labels are one week late (label = start + 8 days).
SHIFT_YEARS = frozenset({2008, 2013, 2014, 2018, 2019, 2020})

# Days between a CCHAIN label and the true MW Sunday start.
LABEL_OFFSET_DAYS = 1
SHIFTED_LABEL_OFFSET_DAYS = 8


# MORBIDITY WEEK ARITHMETIC ++++++++++++++++++++++++++++++++++++++++++++++++++

def sunday_on_or_before(day):
    """Return the Sunday that starts the Sun-Sat week containing `day`.

    Parameters
    ----------
    day : datetime.date | pandas.Timestamp
        Any calendar day.

    Returns
    -------
    Same type as `day` (date in, date out; Timestamp in, Timestamp out),
    normalised to the Sunday on or before it. A Sunday returns itself.
    """
    return day - dt.timedelta(days=(day.weekday() + 1) % 7)


def mw1_start(year):
    """Return the Sunday on which DOH morbidity week 1 of `year` starts.

    Parameters
    ----------
    year : int
        Calendar year.

    Returns
    -------
    datetime.date
        The Sunday starting the first Sun-Sat week with at least 4 days in
        `year`. It can fall in late December of the previous year.
    """
    jan1 = dt.date(year, 1, 1)
    sunday = sunday_on_or_before(jan1)
    # The week holds >= 4 days of the new year when Jan 1 is Sun..Wed.
    return sunday if (jan1 - sunday).days <= 3 else sunday + dt.timedelta(days=7)


def weeks_in_year(year):
    """Return how many morbidity weeks `year` has (52 or 53).

    Parameters
    ----------
    year : int
        Calendar year.

    Returns
    -------
    int
        Number of Sun-Sat weeks from MW1 of `year` up to MW1 of `year + 1`.
    """
    return (mw1_start(year + 1) - mw1_start(year)).days // 7


def morbidity_week(week_start):
    """Return the (MW year, MW number) for a week starting on `week_start`.

    Parameters
    ----------
    week_start : datetime.date | pandas.Timestamp
        A Sunday. Assumed to already be a week start; it is not snapped.

    Returns
    -------
    tuple[int, int]
        (mw_year, mw_week). Late-December Sundays can belong to MW1 of the
        next year. Raises ValueError if `week_start` is not a Sunday.
    """
    day = pd.Timestamp(week_start).date()
    if day.weekday() != 6:
        raise ValueError(f"{day} is not a Sunday")
    year = day.year + 1 if day >= mw1_start(day.year + 1) else day.year
    if day < mw1_start(year):
        year -= 1
    return year, (day - mw1_start(year)).days // 7 + 1


def week_starts(years, weeks):
    """Return the Sunday start of each (MW year, MW number) pair.

    Used to put the modeling team's (year, mw) weeks on the app's calendar.
    Their MW1 begins on 1 January (so it can be 4-10 days long), but the week
    numbering is the same DOH numbering, so (year, mw) is the join key.

    Parameters
    ----------
    years, weeks : array-like of int
        Same length. Weeks are 1-53.

    Returns
    -------
    pandas.Series of datetime64
        Sundays, positional index 0..n-1. Empty input gives an empty Series.
        Raises ValueError if a week number is outside 1..weeks_in_year(year).
    """
    years = pd.Series(years, dtype="int64").reset_index(drop=True)
    weeks = pd.Series(weeks, dtype="int64").reset_index(drop=True)
    if years.empty:
        return pd.Series([], dtype="datetime64[ns]")
    starts = {y: pd.Timestamp(mw1_start(int(y))) for y in years.unique()}
    limit = years.map({y: weeks_in_year(int(y)) for y in starts})
    if ((weeks < 1) | (weeks > limit)).any():
        bad = years[(weeks < 1) | (weeks > limit)].index[0]
        raise ValueError(f"MW {weeks[bad]} does not exist in {years[bad]}")
    return years.map(starts) + pd.to_timedelta((weeks - 1) * 7, unit="D")


# CCHAIN LABEL ALIGNMENT +++++++++++++++++++++++++++++++++++++++++++++++++++++

def align_cchain_labels(labels):
    """Convert CCHAIN PIDSR week labels (Mondays) to true MW Sunday starts.

    Parameters
    ----------
    labels : pandas.Series of datetime64
        The raw `date` column of disease_pidsr_totals.csv, parsed to datetimes.
        Every value is expected to be a Monday.

    Returns
    -------
    pandas.Series of datetime64
        Sunday week starts, same index as `labels`. Labels in SHIFT_YEARS move
        back 8 days, all others 1 day. Raises ValueError if any label is not a
        Monday, since the offsets would then be wrong.
    """
    labels = pd.to_datetime(labels)
    if (labels.dt.dayofweek != 0).any():
        bad = labels[labels.dt.dayofweek != 0].iloc[0]
        raise ValueError(f"CCHAIN label {bad.date()} is not a Monday")
    offsets = np.where(labels.dt.year.isin(SHIFT_YEARS),
                       SHIFTED_LABEL_OFFSET_DAYS, LABEL_OFFSET_DAYS)
    return labels - pd.to_timedelta(offsets, unit="D")


def week_grid(first_week_start, last_week_start):
    """Build a table of every Sunday week start between two dates.

    Parameters
    ----------
    first_week_start, last_week_start : date-like
        Inclusive bounds. Both must be Sundays.

    Returns
    -------
    pandas.DataFrame
        Columns week_start (datetime64), mw_year (int), mw_week (int), one row
        per week. Empty if last < first.
    """
    starts = pd.date_range(first_week_start, last_week_start, freq="7D")
    mw = [morbidity_week(s) for s in starts]
    return pd.DataFrame({
        "week_start": starts,
        "mw_year": [y for y, _ in mw],
        "mw_week": [w for _, w in mw],
    })
