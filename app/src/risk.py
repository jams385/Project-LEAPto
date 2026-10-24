"""App-side DOH epidemic thresholds (FALLBACK only).

The modeling team's thresholds are used whenever they exist (src/contract.py).
This computation runs only when they are missing, and the app then shows a
warning. All settings come from app/config.py; functions accept them as
keyword arguments (defaulting to config) so tests can pin exact values.
"""

import numpy as np
import pandas as pd

from app import config
from src.weeks import mw1_start, weeks_in_year

# THRESHOLDS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

THRESHOLD_COLUMNS = ["adm3_pcode", "mw_year", "mw_week", "week_start", "n_years",
                     "seasonal_mean", "sd", "alert_threshold", "epidemic_threshold"]


def compute_thresholds(cases, years=None, *,
                       lookback=config.THRESHOLD_LOOKBACK_YEARS,
                       min_years=config.THRESHOLD_MIN_YEARS,
                       alert_sd=config.ALERT_SD,
                       epidemic_sd=config.EPIDEMIC_SD,
                       ddof=config.SD_DDOF,
                       mw53_fallback=config.MW53_FALLBACK_WEEK):
    """Compute seasonal mean, alert and epidemic thresholds per city x MW.

    For target year Y and morbidity week w, the history is the cases in week w
    of years Y-lookback .. Y-1 (NA years skipped). With fewer than `min_years`
    non-NA values the row's statistics are NaN. MW53 targets use the history
    of `mw53_fallback` (MW52), since MW53 rarely exists.

    Parameters
    ----------
    cases : pandas.DataFrame
        cases_weekly.parquet: adm3_pcode, mw_year, mw_week, cases (Int64/float).
    years : iterable[int] | None
        Target years to compute. Default: first data year + 1 through last
        data year + 1 (so forecasts past the record still get thresholds).
    lookback, min_years, alert_sd, epidemic_sd, ddof, mw53_fallback
        See app/config.py.

    Returns
    -------
    pandas.DataFrame
        THRESHOLD_COLUMNS, one row per city x target-year MW (including MW53 in
        53-week years). week_start is the MW's Sunday. Empty `cases` gives an
        empty frame with these columns.
    """
    if cases.empty:
        return pd.DataFrame(columns=THRESHOLD_COLUMNS)
    hist = cases.assign(cases=cases.cases.astype("float"))
    pivot = hist.pivot_table(index=["adm3_pcode", "mw_week"], columns="mw_year",
                             values="cases", aggfunc="first", dropna=False)
    if years is None:
        years = range(int(hist.mw_year.min()) + 1, int(hist.mw_year.max()) + 2)

    frames = []
    for year in years:
        cols = [y for y in range(year - lookback, year) if y in pivot.columns]
        window = pivot[cols] if cols else pd.DataFrame(index=pivot.index)
        stats = pd.DataFrame({
            "n_years": window.notna().sum(axis=1),
            "seasonal_mean": window.mean(axis=1),
            "sd": window.std(axis=1, ddof=ddof),
        })
        stats.loc[stats.n_years < min_years, ["seasonal_mean", "sd"]] = np.nan
        stats = stats.reset_index()
        stats = stats[stats.mw_week <= 52]
        if weeks_in_year(year) == 53:
            wk53 = stats[stats.mw_week == mw53_fallback].assign(mw_week=53)
            stats = pd.concat([stats, wk53], ignore_index=True)
        stats["mw_year"] = year
        frames.append(stats)

    out = pd.concat(frames, ignore_index=True)
    out["alert_threshold"] = out.seasonal_mean + alert_sd * out.sd
    out["epidemic_threshold"] = out.seasonal_mean + epidemic_sd * out.sd
    out["week_start"] = [pd.Timestamp(mw1_start(y)) + pd.Timedelta(weeks=w - 1)
                         for y, w in zip(out.mw_year, out.mw_week)]
    return (out[THRESHOLD_COLUMNS]
            .sort_values(["adm3_pcode", "week_start"]).reset_index(drop=True))
