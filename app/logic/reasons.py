"""Plain-language reasons behind a city's alert level ("What we're seeing").

The model does not output per-week drivers, so these are SIGNALS IN THE DATA
that are consistent with the level, not the model's internal explanation.
Each reason is built from real columns only, states its numbers and source,
and is dropped when its input is missing or the week is flagged as
non-reporting. Cut-offs live in app/config.py.

Reasons, in display order:
    case_signal / lower_confidence / no_report / no_forecast
                 notes about confidence
    heavy_rain   IMERG rain 1-2 weeks ago vs this city's usual for the week
    cases        the latest reported week's cases vs that week's outbreak line
    seasonal     outbreak weeks around this time in earlier years (fallback,
                 only when neither heavy rain nor cases applies)
    flood        the city's most flood-prone barangay (Project NOAH)
Wording rules: "may", "raised risk", "chance of an outbreak week"; never a
forecast number of people.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app import config
from src.views import cases_week_start
from src.weeks import morbidity_week

# REASON +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

NOTE_KINDS = ("case_signal", "lower_confidence", "no_report", "no_forecast")
SIGNAL_KINDS = ("heavy_rain", "cases", "seasonal", "flood")


@dataclass(frozen=True)
class Reason:
    """One line of "What we're seeing".

    Attributes
    ----------
    kind : str
        One of NOTE_KINDS or SIGNAL_KINDS.
    text : str
        Plain-language sentence with its numbers.
    source : str
        Where the numbers come from (shown in small print).
    """

    kind: str
    text: str
    source: str


# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def lag_window(lag_response=None):
    """Weeks after heavy rain during which risk stays raised.

    Parameters
    ----------
    lag_response : pandas.DataFrame | None
        lag_response.csv (lag_weeks, rr_p95, optional rr_p95_lower).

    Returns
    -------
    tuple[int, int]
        (first, last) lag whose 95% interval lies above 1 (rr_p95_lower > 1),
        or whose RR is above 1 when there is no interval.
        config.LAG_WINDOW_FALLBACK when the curve is missing or never raised.
    """
    if lag_response is None or lag_response.empty:
        return config.LAG_WINDOW_FALLBACK
    col = "rr_p95_lower" if "rr_p95_lower" in lag_response else "rr_p95"
    raised = lag_response.loc[lag_response[col] > 1, "lag_weeks"].astype(int)
    if raised.empty:
        return config.LAG_WINDOW_FALLBACK
    return int(raised.min()), int(raised.max())


def _usual_rain(rain, week_row):
    """Mean rain for the same morbidity week number in every other year.

    Parameters
    ----------
    rain : pandas.DataFrame
        One city's rain_weekly rows (mw_year, mw_week, rain_mm).
    week_row : pandas.Series
        The week being compared.

    Returns
    -------
    float
        NaN when there is no other year.
    """
    other = rain[(rain.mw_week == week_row.mw_week) & (rain.mw_year != week_row.mw_year)]
    return float(other.rain_mm.mean()) if not other.empty else np.nan


def _ago(weeks):
    """Wording for a week in the past.

    Parameters
    ----------
    weeks : int
        1 or more.

    Returns
    -------
    str
        "last week" for 1, else "N weeks ago".
    """
    return "last week" if weeks == 1 else f"{weeks} weeks ago"


# SIGNALS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def heavy_rain_reason(rain_weekly, pcode, origin_week, window=None):
    """Heavy rain 1 or 2 weeks before the forecast week.

    Parameters
    ----------
    rain_weekly : pandas.DataFrame
        IMERG weekly rain (adm3_pcode, week_start, mw_year, mw_week, rain_mm).
    pcode : str
    origin_week : Timestamp
        Forecast origin; "last week" is the week before it.
    window : tuple[int, int] | None
        lag_window() output for the wording.

    Returns
    -------
    Reason | None
        The week with the largest rain-to-usual ratio among those at or above
        config.REASON_HEAVY_RAIN_RATIO x usual and config.REASON_HEAVY_RAIN_MIN_MM;
        None if neither week qualifies or the data are missing.
    """
    first, last = window or config.LAG_WINDOW_FALLBACK
    rain = rain_weekly[rain_weekly.adm3_pcode == pcode]
    best = None
    for ago in (1, 2):
        week = rain[rain.week_start == pd.Timestamp(origin_week) - pd.Timedelta(weeks=ago)]
        if week.empty or pd.isna(week.rain_mm.iloc[0]):
            continue
        row = week.iloc[0]
        usual = _usual_rain(rain, row)
        if np.isnan(usual) or usual <= 0:
            continue
        ratio = row.rain_mm / usual
        if (ratio >= config.REASON_HEAVY_RAIN_RATIO
                and row.rain_mm >= config.REASON_HEAVY_RAIN_MIN_MM
                and (best is None or ratio > best[0])):
            best = (ratio, ago, row.rain_mm, usual)
    if best is None:
        return None
    _, ago, mm, usual = best
    return Reason("heavy_rain",
                  f"Heavy rain {_ago(ago)}: {mm:.0f} mm vs a usual {usual:.0f} mm for this "
                  f"time of year. Heavy rain may raise the chance of an outbreak week for "
                  f"the next {first}–{last} weeks.",
                  "NASA IMERG rainfall; lag from the modeling team's rain–risk curve")


def cases_reason(cases, thresholds, pcode, origin_week):
    """The latest reported week's cases close to or above its outbreak line.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, week_start, cases, reporting_flag).
    thresholds : pandas.DataFrame
        adm3_pcode, week_start, threshold (cases per 7 days).
    pcode : str
    origin_week : Timestamp
        Forecast origin; the latest reported week is src.views.cases_week_start.

    Returns
    -------
    Reason | None
        None when that week is missing, flagged as non-reporting, has no
        threshold, or is below config.REASON_CASES_NEAR_SHARE of the line.
    """
    last = cases_week_start(origin_week)
    week = cases[(cases.adm3_pcode == pcode) & (cases.week_start == last)]
    line = thresholds[(thresholds.adm3_pcode == pcode) & (thresholds.week_start == last)]
    if week.empty or line.empty:
        return None
    flag = week.reporting_flag.iloc[0] if "reporting_flag" in week else None
    n, thr = week.cases.iloc[0], line.threshold.iloc[0]
    if (flag is not None and not pd.isna(flag)) or pd.isna(n) or pd.isna(thr):
        return None
    n, limit = int(n), int(thr)
    if n < 1 or n < config.REASON_CASES_NEAR_SHARE * thr:
        return None
    where = "above" if n > thr else "close to"
    unit = "case" if n == 1 else "cases"
    return Reason("cases",
                  f"{n} {unit} reported in the latest reported week (from {last:%b} "
                  f"{last.day}), {where} that week's outbreak line (more than {limit}).",
                  "Reported cases, DOH PIDSR via Project CCHAIN; DOH epidemic threshold")


def seasonal_reason(cases, thresholds, pcode, target_week,
                    window=config.REASON_SEASON_WINDOW_WEEKS):
    """How often weeks around this time were outbreak weeks in earlier years.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (with reporting_flag).
    thresholds : pandas.DataFrame
        adm3_pcode, week_start, threshold.
    pcode : str
    target_week : Timestamp
        The forecast week (Sunday).
    window : int
        Morbidity weeks either side.

    Returns
    -------
    Reason | None
        None when no earlier week has both a report and a threshold.
    """
    year, mw = morbidity_week(pd.Timestamp(target_week))
    hist = cases[(cases.adm3_pcode == pcode) & (cases.mw_year < year)
                 & ((cases.mw_week - mw).abs() <= window)]
    if "reporting_flag" in hist:
        hist = hist[hist.reporting_flag.isna()]
    hist = hist.merge(thresholds[thresholds.adm3_pcode == pcode][["week_start", "threshold"]],
                      on="week_start").dropna(subset=["cases", "threshold"])
    if hist.empty:
        return None
    above = int((hist.cases.astype(float) > hist.threshold).sum())
    first = int(hist.mw_year.min())
    return Reason("seasonal",
                  f"Seasonal pattern: in {first}–{year - 1}, {above} of {len(hist)} weeks "
                  f"around this time of year were outbreak weeks here.",
                  "Reported cases vs DOH epidemic thresholds, same weeks in earlier years")


def flood_reason(flood_rank, pcode):
    """The city's most flood-prone barangay, when it is largely high-hazard.

    Parameters
    ----------
    flood_rank : pandas.DataFrame
        brgy_flood_rank.csv (adm3_pcode, rank, brgy_name, high_hazard_pct).
    pcode : str

    Returns
    -------
    Reason | None
        None when the file is missing or the top share is below
        config.REASON_FLOOD_BRGY_PCT.
    """
    if flood_rank is None or flood_rank.empty:
        return None
    rows = flood_rank[flood_rank.adm3_pcode == pcode].sort_values("rank")
    if rows.empty or rows.high_hazard_pct.iloc[0] < config.REASON_FLOOD_BRGY_PCT:
        return None
    top = rows.iloc[0]
    return Reason("flood",
                  f"Flood-prone area: {top.brgy_name} has {top.high_hazard_pct:.0f}% of its "
                  f"area at high flood hazard. Flooding may add to the risk from heavy rain.",
                  "Project NOAH flood hazard maps (100-year flood)")


# ALL REASONS FOR ONE CITY +++++++++++++++++++++++++++++++++++++++++++++++++++

def confidence_reason(cases, pcode, group, auc=None):
    """A note when the city's forecasts are less certain.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (for the case-signal total).
    pcode : str
    group : str
        The city's confidence group (src.views.confidence_groups).
    auc : float | None
        The city's test AUC (city_confidence.csv).

    Returns
    -------
    Reason | None
        A "case_signal" note (with the city's case total) or a
        "lower_confidence" note (with its AUC when known); None for
        "standard" cities.
    """
    if group == "case_signal":
        total = int(cases.loc[cases.adm3_pcode == pcode, "cases"].sum(skipna=True))
        return Reason("case_signal",
                      f"Few reported cases in this city ({total} in 2008–2022), too few to "
                      "forecast a level. The weekly case count is the signal to watch.",
                      "Reported cases, DOH PIDSR via Project CCHAIN; modeling team's "
                      "per-city test")
    if group == "lower":
        score = (f" (score {auc:.2f}, where 0.5 is guessing and 1 is perfect)"
                 if auc is not None and not pd.isna(auc) else "")
        return Reason("lower_confidence",
                      "Lower confidence: in testing on 2014–2022, forecasts for this city "
                      f"picked out outbreak weeks less well than in most cities{score}.",
                      "Modeling team's per-city test (AUC)")
    return None


def city_reasons(pcode, level, origin_week, target_week, *, rain_weekly, cases, thresholds,
                 flood_rank=None, lag_response=None, group="standard", auc=None):
    """Every reason for one city and forecast week, notes first.

    Parameters
    ----------
    pcode : str
    level : str
        The level shown for this city (src.views.display_levels).
    origin_week, target_week : Timestamp
        Forecast origin and the forecast week (target may be NaT when there
        is no forecast row).
    rain_weekly, cases, thresholds : pandas.DataFrame
        IMERG rain, observed cases (with reporting_flag), outbreak lines.
    flood_rank : pandas.DataFrame | None
        brgy_flood_rank.csv.
    lag_response : pandas.DataFrame | None
        lag_response.csv (for the "next 1-5 weeks" wording).
    group : str
        The city's confidence group ("standard" / "lower" / "case_signal").
    auc : float | None
        The city's test AUC, quoted in the lower-confidence note.

    Returns
    -------
    list[Reason]
        Notes (case signal, lower confidence, no report, no forecast) first,
        then heavy rain, cases, the seasonal fallback (only if neither of
        those applies) and flood. Inputs that are missing are skipped, never
        guessed; the list can be empty.
    """
    out = []
    if level == config.NO_FORECAST_LEVEL:
        return [Reason("no_forecast", "No forecast for this week, so there is no level to "
                       "explain.", "alerts.csv: 2014–2022, weeks with an outbreak line")]
    note = confidence_reason(cases, pcode, group, auc)
    if note is not None:
        out.append(note)
    last = cases_week_start(origin_week)
    flags = cases[(cases.adm3_pcode == pcode) & (cases.week_start.isin(
        [last, pd.Timestamp(target_week) if not pd.isna(target_week) else last]))]
    flagged = flags.reporting_flag.notna() if "reporting_flag" in flags else pd.Series(False)
    if level == config.NO_REPORT_LEVEL or bool(flagged.any()):
        note = Reason("no_report",
                      "Case reports for this period are missing (flagged as non-reporting), "
                      "so recent cases can't be checked.",
                      "Reporting flags from the modeling team")
        # When the level itself is "No report", that note leads.
        out.insert(0 if level == config.NO_REPORT_LEVEL else len(out), note)
    rain = heavy_rain_reason(rain_weekly, pcode, origin_week, lag_window(lag_response))
    seen = cases_reason(cases, thresholds, pcode, origin_week)
    out += [r for r in (rain, seen) if r is not None]
    if rain is None and seen is None and not pd.isna(target_week):
        season = seasonal_reason(cases, thresholds, pcode, target_week)
        if season is not None:
            out.append(season)
    flood = flood_reason(flood_rank, pcode)
    if flood is not None:
        out.append(flood)
    return out


def headline_reason(reasons):
    """The one reason shown on the Overview.

    Parameters
    ----------
    reasons : list[Reason]
        city_reasons output.

    Returns
    -------
    Reason | None
        A blocking note if there is one (case signal, no report, no
        forecast), else the first signal, else the lower-confidence note
        (the drawer header already says "lower confidence"); None for an
        empty list.
    """
    for kinds in (("case_signal", "no_report", "no_forecast"), SIGNAL_KINDS,
                  ("lower_confidence",)):
        for r in reasons:
            if r.kind in kinds:
                return r
    return None
