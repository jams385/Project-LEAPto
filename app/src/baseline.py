"""Labelled placeholders for contract-v2 parts the modeling team has not delivered.

Each function writes a table in the same schema as the model file it stands
in for (alerts, level_metrics, the "last_week_only" AUC rows, reporting flags).
scripts/make_baseline_forecast.py writes them to data/processed/*_baseline.csv
and the app labels them "Baseline, model pending".

The placeholder alerts are seasonal only: the chance that a week is an
outbreak week is how often the same weeks of earlier years were above the
threshold. They do NOT use rainfall or recent cases, so they cannot
anticipate unusual events (e.g. Typhoon Washi).

Timing convention (docs/DATA_CONTRACT.md): a forecast issued at origin_week
uses data through the week before it, and horizon h targets
origin_week + (h - 1) weeks.
"""

import numpy as np
import pandas as pd

from app import config
from src.weeks import morbidity_week

# SEASONAL CHANCE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def seasonal_exceedance(cases, thresholds, target_weeks, *,
                        min_years=config.BASELINE_MIN_YEARS,
                        window=config.BASELINE_WINDOW_WEEKS,
                        mw53_fallback=config.MW53_FALLBACK_WEEK):
    """Seasonal chance that each target week is above its threshold.

    For target (year Y, week w) in a city, the chance is the share of that
    city's reported weekly counts in weeks w-window..w+window (same year
    numbering, no wrap-around) of all years before Y that are strictly above
    the target week's threshold. MW53 uses MW52. Only years before Y are
    used, so no target-year data leaks in.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, mw_year, mw_week, cases).
    thresholds : pandas.DataFrame
        adm3_pcode, week_start, threshold (cases per 7 days).
    target_weeks : iterable of Timestamp
        Sunday week starts.
    min_years, window, mw53_fallback
        See app/config.py.

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, target_week, outbreak_prob, threshold. Targets with fewer
        than `min_years` earlier values of week w, or with no threshold, are
        omitted. Empty input gives an empty frame with these columns.
    """
    cols = ["adm3_pcode", "target_week", "outbreak_prob", "threshold"]
    targets = pd.DataFrame({"target_week": pd.to_datetime(sorted(set(target_weeks)))})
    if targets.empty or cases.empty:
        return pd.DataFrame(columns=cols)
    mw = [morbidity_week(t) for t in targets.target_week]
    targets["mw_year"] = [y for y, _ in mw]
    targets["mw_week"] = [w if w != 53 else mw53_fallback for _, w in mw]

    thr = thresholds.set_index(["adm3_pcode", "week_start"]).threshold
    rows = []
    for pcode, city in cases.groupby("adm3_pcode"):
        hist = city.dropna(subset=["cases"])
        years = hist.mw_year.to_numpy()
        weeks = hist.mw_week.to_numpy()
        values = hist.cases.to_numpy(dtype=float)
        for t in targets.itertuples(index=False):
            prior = years < t.mw_year
            if (prior & (weeks == t.mw_week)).sum() < min_years:
                continue
            limit = thr.get((pcode, t.target_week), np.nan)
            if pd.isna(limit):
                continue
            pool = values[prior & (np.abs(weeks - t.mw_week) <= window)]
            rows.append((pcode, t.target_week, float((pool > limit).mean()), float(limit)))
    return pd.DataFrame(rows, columns=cols)


# CONTRACT V2 PLACEHOLDERS +++++++++++++++++++++++++++++++++++++++++++++++++++

ALERT_COLUMNS = ["adm3_pcode", "origin_week", "horizon", "target_week", "outbreak_prob",
                 "rr_vs_usual", "alert_level", "observed_cases", "observed_outbreak",
                 "threshold", "reporting_flag", "model_version"]
LEVEL_METRIC_COLUMNS = ["horizon", "alert_level", "n_weeks", "n_outbreaks", "hit_rate",
                        "base_rate", "lift", "capture_rate", "median_lead_weeks", "prob_cutoff"]


def build_baseline_alerts(cases, thresholds, flags=None, *, horizons=config.ALERT_HORIZONS,
                          model_version=config.BASELINE_ALERTS_VERSION):
    """Placeholder alerts.csv: seasonal chance of an outbreak week, no rainfall.

    outbreak_prob comes from seasonal_exceedance. It ignores
    rainfall and recent cases, so it is the same at every horizon and
    rr_vs_usual is left empty. alert_level is left empty for the app to
    assign from the cut-offs.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, week_start, mw_year, mw_week, cases).
    thresholds : pandas.DataFrame
        adm3_pcode, week_start, threshold (src.contract.thresholds_table).
    flags : pandas.DataFrame | None
        reporting_flags rows (adm3_pcode, week_start, flag).
    horizons : tuple[int, ...]
    model_version : str
        Written to every row so the file is clearly a placeholder.

    Returns
    -------
    pandas.DataFrame
        ALERT_COLUMNS, one row per city x target week (with enough history and
        a threshold) x horizon, sorted. Empty input gives an empty frame.
    """
    if cases.empty or thresholds.empty:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    preds = seasonal_exceedance(cases, thresholds, cases.week_start.unique())
    observed = cases[["adm3_pcode", "week_start", "cases"]].rename(
        columns={"week_start": "target_week", "cases": "observed_cases"})
    out = preds.merge(observed, on=["adm3_pcode", "target_week"], how="left")
    flag_map = (flags.set_index(["adm3_pcode", "week_start"]).flag
                if flags is not None and not flags.empty else pd.Series(dtype=object))
    out["reporting_flag"] = [flag_map.get(k) for k in zip(out.adm3_pcode, out.target_week)]
    counted = out.observed_cases.notna() & out.reporting_flag.isna()
    out["observed_outbreak"] = (out.observed_cases.astype("float")
                                > out.threshold).astype("boolean").where(counted)
    out = out.merge(pd.DataFrame({"horizon": list(horizons)}), how="cross")
    out["origin_week"] = out.target_week - pd.to_timedelta((out.horizon - 1) * 7, unit="D")
    out["rr_vs_usual"] = np.nan
    out["alert_level"] = None
    out["model_version"] = model_version
    return (out[ALERT_COLUMNS].sort_values(["adm3_pcode", "origin_week", "horizon"])
            .reset_index(drop=True))


def _lead_weeks(group, level_rank, min_rank, horizon):
    """Lead times (weeks) for the outbreak episodes of one city at one horizon.

    An episode is a run of consecutive outbreak weeks; it is "warned" when
    its first week was at `min_rank` or higher. The lead is the number of
    consecutive weeks before it that were also at that level or higher, plus
    (horizon - 1), because a horizon-h forecast is issued h - 1 weeks before
    its target week.

    Parameters
    ----------
    group : pandas.DataFrame
        One city's rows at one horizon, sorted by target_week, with
        observed_outbreak (bool).
    level_rank : numpy.ndarray of int
        Rank of each row's level (Normal 0, Watch 1, Warning 2).
    min_rank : int
    horizon : int

    Returns
    -------
    list[int]
        One lead per warned episode (empty if none).
    """
    weeks = group.target_week.to_numpy()
    outbreak = group.observed_outbreak.to_numpy(dtype=bool)
    gap = (np.diff(weeks) / np.timedelta64(1, "D")).astype(int)
    leads = []
    for i in np.flatnonzero(outbreak):
        is_start = i == 0 or not outbreak[i - 1] or gap[i - 1] != 7
        if not is_start or level_rank[i] < min_rank:
            continue
        k, j = 0, i - 1
        while j >= 0 and gap[j] == 7 and level_rank[j] >= min_rank:
            k, j = k + 1, j - 1
        leads.append(k + horizon - 1)
    return leads


def compute_level_metrics(alerts, cutoffs=None, *, levels=config.ALERT_LEVELS):
    """Track record per horizon x level (level_metrics.csv schema).

    Uses rows with a forecast level (Normal / Watch / Warning) and a known
    outcome (observed_outbreak not NA).

    Parameters
    ----------
    alerts : pandas.DataFrame
        alerts with alert_level filled (src.contract.assign_levels).
    cutoffs : dict[str, float] | None
        Cut-offs that produced the levels, written as prob_cutoff
        (Normal = 0). None leaves prob_cutoff empty.
    levels : tuple[str, ...]
        Level names, lowest first.

    Returns
    -------
    pandas.DataFrame
        LEVEL_METRIC_COLUMNS, one row per horizon x level:
        hit_rate = outbreak weeks / weeks at that level; base_rate = all
        outbreak weeks / all weeks at that horizon; lift = hit / base;
        capture_rate = share of outbreak weeks at that level or higher;
        median_lead_weeks over warned episodes (see _lead_weeks; NaN if none,
        and always NaN for the lowest level).
        Empty input gives an empty frame.
    """
    rank = {lvl: i for i, lvl in enumerate(levels)}
    data = alerts[alerts.alert_level.isin(levels) & alerts.observed_outbreak.notna()].copy()
    if data.empty:
        return pd.DataFrame(columns=LEVEL_METRIC_COLUMNS)
    data["observed_outbreak"] = data.observed_outbreak.astype(bool)
    data["rank"] = data.alert_level.map(rank)
    rows = []
    for h, hd in data.groupby("horizon"):
        total_out = int(hd.observed_outbreak.sum())
        base = hd.observed_outbreak.mean()
        hd = hd.sort_values(["adm3_pcode", "target_week"])
        for lvl in levels:
            r = rank[lvl]
            at = hd[hd["rank"] == r]
            n_out = int(at.observed_outbreak.sum())
            hit = n_out / len(at) if len(at) else np.nan
            caught = int(hd[hd["rank"] >= r].observed_outbreak.sum())
            # "Normal or higher" is every week, so a lead time means nothing there.
            leads = [] if r == 0 else [
                lead for _, g in hd.groupby("adm3_pcode")
                for lead in _lead_weeks(g, g["rank"].to_numpy(), r, int(h))]
            cut = (0.0 if r == 0 else cutoffs.get(lvl, np.nan)) if cutoffs else np.nan
            rows.append((int(h), lvl, len(at), n_out, hit, base,
                         hit / base if base else np.nan,
                         caught / total_out if total_out else np.nan,
                         float(np.median(leads)) if leads else np.nan, cut))
    return pd.DataFrame(rows, columns=LEVEL_METRIC_COLUMNS)


def _auc(score, label):
    """Mann-Whitney AUC (ties count half).

    Parameters
    ----------
    score : array-like of float
    label : array-like of bool

    Returns
    -------
    float; NaN when either class is empty.
    """
    label = np.asarray(label, dtype=bool)
    n1, n0 = label.sum(), (~label).sum()
    if n1 == 0 or n0 == 0:
        return np.nan
    ranks = pd.Series(score).rank().to_numpy()
    return float((ranks[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def last_week_only_auc(alerts, cases, *, horizons=config.ALERT_HORIZONS):
    """Placeholder AUC for "last week's cases only" (no model is fitted).

    Ranks the same evaluated weeks as `alerts` (known outcome and a
    probability) by the last reported count known at forecast time: the
    target week minus (horizon + 1) weeks, matching the one-week reporting
    delay the modeling team assumes. Weeks without that count are dropped.

    Parameters
    ----------
    alerts : pandas.DataFrame
        alerts.csv rows (adm3_pcode, horizon, target_week, outbreak_prob,
        observed_outbreak).
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, week_start, cases).
    horizons : tuple[int, ...]

    Returns
    -------
    pandas.DataFrame
        horizon, model ("last_week_only"), auc, n_weeks, note. Horizons with
        no evaluable weeks are omitted.
    """
    known = cases[["adm3_pcode", "week_start", "cases"]].rename(
        columns={"week_start": "known_week", "cases": "last_cases"})
    rows = []
    for h in horizons:
        sub = alerts[(alerts.horizon == h) & alerts.observed_outbreak.notna()
                     & alerts.outbreak_prob.notna()].copy()
        sub["known_week"] = sub.target_week - pd.Timedelta(weeks=h + 1)
        sub = sub.merge(known, on=["adm3_pcode", "known_week"], how="inner").dropna(
            subset=["last_cases"])
        if sub.empty:
            continue
        rows.append((int(h), "last_week_only",
                     _auc(sub.last_cases.astype(float), sub.observed_outbreak.astype(bool)),
                     len(sub), "placeholder: ranks weeks by the last reported count, no model"))
    return pd.DataFrame(rows, columns=["horizon", "model", "auc", "n_weeks", "note"])


def baseline_reporting_flags(cases):
    """Placeholder reporting_flags.csv: weeks with no reported count.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, week_start, cases).

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, week_start, flag ("non_reporting") for every week whose
        count is missing; may be empty.
    """
    missing = cases[cases.cases.isna()][["adm3_pcode", "week_start"]]
    return missing.assign(flag="non_reporting").reset_index(drop=True)
