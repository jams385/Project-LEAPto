"""Pure builders for the Data reliability tab: every number and phrase's basis.

Each function reads the contract tables (data/model_outputs/) and returns plain
numbers, or None when its input is missing or empty: the page then shows
"pending" instead of a number. Nothing here is typed in from the design
canvas. Wording lives in app/content/reliability_text.py.
"""

import numpy as np
import pandas as pd

from app import config

LEVELS_TOP_DOWN = ("Warning", "Watch", "Normal")

# HELPERS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def fraction_phrase(x, tol=0.04):
    """A share as a plain fraction when it is close to one, else None.

    Used so a phrase like "about a third" only appears when the number
    supports it (within `tol` of 1/4, 1/3, 1/2, 2/3 or 3/4).

    Parameters
    ----------
    x : float
        A share between 0 and 1.
    tol : float
        How far from the fraction the share may be.

    Returns
    -------
    str | None
        "a quarter", "a third", "half", "two thirds" or "three quarters";
        None when no fraction fits (or x is missing).
    """
    if x is None or pd.isna(x):
        return None
    names = {0.25: "a quarter", 1 / 3: "a third", 0.5: "half", 2 / 3: "two thirds",
             0.75: "three quarters"}
    best = min(names, key=lambda f: abs(f - x))
    return names[best] if abs(best - x) <= tol else None


def out_of_ten(x):
    """A share as "7 in 10" (rounded to the nearest tenth).

    Parameters
    ----------
    x : float | None

    Returns
    -------
    str | None
        None when x is missing.
    """
    if x is None or pd.isna(x):
        return None
    return f"{round(x * 10):d} in 10"


def _rows(table, **where):
    """Rows of a table matching column == value (empty if the table is empty).

    Parameters
    ----------
    table : pandas.DataFrame | None
    **where
        Column -> required value.

    Returns
    -------
    pandas.DataFrame
    """
    if table is None or table.empty:
        return pd.DataFrame()
    mask = pd.Series(True, index=table.index)
    for col, value in where.items():
        if col not in table:
            return pd.DataFrame()
        mask &= table[col] == value
    return table[mask]


# TEST PERIOD +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def evaluation_period(alerts, metrics, horizon):
    """The years that were tested and how many city-weeks that is.

    Parameters
    ----------
    alerts : pandas.DataFrame | None
        alerts.csv (target_week, observed_outbreak).
    metrics : pandas.DataFrame | None
        level_metrics.csv (horizon, n_weeks).
    horizon : int

    Returns
    -------
    dict
        first_year, last_year (target years with a known outcome) and
        city_weeks (sum of n_weeks at this horizon); each None if unknown.
    """
    out = {"first_year": None, "last_year": None, "city_weeks": None}
    if alerts is not None and not alerts.empty:
        known = alerts[alerts.observed_outbreak.notna()]
        if not known.empty:
            # A DOH week belongs to the year holding most of it (MW1 can start in
            # late December): the year of its fourth day.
            years = (pd.to_datetime(known.target_week) + pd.Timedelta(days=3)).dt.year
            out.update(first_year=int(years.min()), last_year=int(years.max()))
    m = _rows(metrics, horizon=horizon)
    if not m.empty:
        out["city_weeks"] = int(m.n_weeks.sum())
    return out


# LEVEL ROWS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def level_rows(metrics, horizon):
    """One dict per level (Warning, Watch, Normal) from the track record.

    Parameters
    ----------
    metrics : pandas.DataFrame | None
        level_metrics.csv: horizon, alert_level, n_weeks, n_outbreaks,
        hit_rate, base_rate, lift, capture_rate (share of all outbreak weeks
        at this level OR higher).
    horizon : int

    Returns
    -------
    list[dict]
        level, rate (share of its weeks that became outbreak weeks), lift
        (rate / base rate), base_rate, weeks, share_of_weeks, weeks_per_city_year
        (weeks / (tested weeks / 52.18): a city's year), own_capture (share of
        ALL outbreak weeks that fell at exactly this level) and cum_capture
        (this level or higher). Empty list when the track record is missing.
    """
    m = _rows(metrics, horizon=horizon)
    if m.empty or not set(LEVELS_TOP_DOWN) <= set(m.alert_level):
        return []
    by = m.set_index("alert_level")
    total_weeks = float(by.n_weeks.sum())
    total_out = float(by.n_outbreaks.sum())
    city_years = total_weeks / (365.25 / 7)
    out = []
    for level in LEVELS_TOP_DOWN:
        r = by.loc[level]
        cum = float(r.capture_rate)
        own = {"Warning": cum,
               "Watch": cum - float(by.loc["Warning"].capture_rate),
               "Normal": float(r.n_outbreaks) / total_out if total_out else np.nan}[level]
        out.append({"level": level, "rate": float(r.hit_rate), "lift": float(r.lift),
                    "base_rate": float(r.base_rate), "weeks": int(r.n_weeks),
                    "share_of_weeks": float(r.n_weeks) / total_weeks,
                    "weeks_per_city_year": float(r.n_weeks) / city_years,
                    "own_capture": own, "cum_capture": cum})
    return out


def episode_share(episodes, horizon, level, kind="2+ weeks"):
    """Share of outbreak episodes whose first week was forecast at `level`.

    Parameters
    ----------
    episodes : pandas.DataFrame | None
        episodes.csv (horizon, episode, alert_level, n, share).
    horizon : int
    level : str
    kind : str
        "2+ weeks" (multi-week outbreaks) or "single week".

    Returns
    -------
    float | None
        None when the row is missing.
    """
    r = _rows(episodes, horizon=horizon, episode=kind, alert_level=level)
    return None if r.empty else float(r.share.iloc[0])


def first_week_flagged(episodes, horizon):
    """Share of multi-week outbreaks whose first week was Watch or Warning.

    Parameters
    ----------
    episodes : pandas.DataFrame | None
    horizon : int

    Returns
    -------
    float | None
        1 - the Normal share; None when it is missing.
    """
    normal = episode_share(episodes, horizon, "Normal")
    return None if normal is None else 1.0 - normal


def normal_blip_share(episodes, horizon):
    """Of the outbreaks that began in a Normal week, how many lasted one week.

    Parameters
    ----------
    episodes : pandas.DataFrame | None
    horizon : int

    Returns
    -------
    float | None
        single-week Normal / (single-week + multi-week Normal), by count.
    """
    one = _rows(episodes, horizon=horizon, episode="single week", alert_level="Normal")
    many = _rows(episodes, horizon=horizon, episode="2+ weeks", alert_level="Normal")
    if one.empty or many.empty:
        return None
    n1, n2 = float(one.n.iloc[0]), float(many.n.iloc[0])
    return n1 / (n1 + n2) if n1 + n2 else None


# TILES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def lead_weeks_range(horizon=None, delay=config.CASES_REPORT_DELAY_WEEKS):
    """The lead over case reports when an outbreak is flagged ahead of time.

    A forecast made h weeks ahead is issued at the end of week t - h, and the
    health office learns of an outbreak in week t at the end of week t + delay
    (reports arrive late): so a flag h weeks ahead leads by h + delay weeks.
    This is the definition of the modeling team's stage 6 lead time, not a
    measured average.

    Parameters
    ----------
    horizon : int | None
        One horizon, or None for the whole range of config.HORIZONS.
    delay : int
        Reporting delay in weeks.

    Returns
    -------
    tuple[int, int]
        (shortest, longest) lead in weeks.
    """
    hs = [horizon] if horizon else list(config.HORIZONS)
    return min(hs) + delay, max(hs) + delay


def auc_pair(auc, horizon):
    """The final model's AUC against the seasonal calendar's.

    Parameters
    ----------
    auc : pandas.DataFrame | None
        auc.csv (horizon, model, scope, auc).
    horizon : int

    Returns
    -------
    dict
        final_within, seasonal_within, final_all, seasonal_all, rain_all;
        each None when missing.
    """
    def get(model, scope):
        r = _rows(auc, horizon=horizon, model=model, scope=scope)
        return None if r.empty else float(r.auc.iloc[0])
    return {"final_within": get("final_model", "within city"),
            "seasonal_within": get("seasonal_only", "within city"),
            "final_all": get("final_model", "all weeks"),
            "seasonal_all": get("seasonal_only", "all weeks"),
            "rain_all": get("rain_only", "all weeks")}


def rain_gain_split(rain_gain):
    """The weeks ahead where rain clearly helps, and where it does not.

    "Clearly" means the 95% interval of the gain in log score is above zero.

    Parameters
    ----------
    rain_gain : pandas.DataFrame | None
        rain_gain.csv (horizon, gain_per_week, lo, hi).

    Returns
    -------
    dict | None
        clear (horizons with lo > 0), unclear (the rest), gains
        ({horizon: gain}); None when the file is missing.
    """
    if rain_gain is None or rain_gain.empty:
        return None
    clear = sorted(int(h) for h in rain_gain[rain_gain.lo > 0].horizon)
    unclear = sorted(int(h) for h in rain_gain[~(rain_gain.lo > 0)].horizon)
    return {"clear": clear, "unclear": unclear,
            "gains": {int(r.horizon): float(r.gain_per_week) for r in rain_gain.itertuples()}}


# WHAT IT CANNOT DO +++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def case_counts(cases, first_year):
    """How few cases a typical city-week has, in the tested years.

    Parameters
    ----------
    cases : pandas.DataFrame | None
        Observed weekly cases (week_start, cases).
    first_year : int | None
        First tested year.

    Returns
    -------
    dict | None
        median (cases per city-week) and share_le2 (weeks with 2 or fewer);
        None when unknown.
    """
    if cases is None or cases.empty or first_year is None:
        return None
    year = cases.mw_year if "mw_year" in cases else (
        pd.to_datetime(cases.week_start) + pd.Timedelta(days=3)).dt.year
    t = cases[(year >= first_year) & cases.cases.notna()]
    if t.empty:
        return None
    return {"median": float(t.cases.median()), "share_le2": float((t.cases <= 2).mean())}


def calibration_top(alerts, horizon, from_p=config.RELIABILITY_CALIBRATION_FROM):
    """How often the highest forecast chances came true.

    Parameters
    ----------
    alerts : pandas.DataFrame | None
        alerts.csv (horizon, outbreak_prob, observed_outbreak).
    horizon : int
    from_p : float
        Weeks forecast at this chance or higher.

    Returns
    -------
    dict | None
        weeks, forecast (mean chance), observed (share that became outbreak
        weeks); None when no such week has a known outcome.
    """
    if alerts is None or alerts.empty:
        return None
    x = alerts[(alerts.horizon == horizon) & alerts.observed_outbreak.notna()
               & (alerts.outbreak_prob >= from_p)]
    if x.empty:
        return None
    return {"weeks": int(len(x)), "forecast": float(x.outbreak_prob.mean()),
            "observed": float(x.observed_outbreak.astype(bool).mean())}


def city_groups_named(city_conf, names):
    """Lower-confidence and case-signal cities, with their numbers.

    Parameters
    ----------
    city_conf : pandas.DataFrame | None
        city_confidence.csv (adm3_pcode, outbreak_weeks, auc).
    names : dict[str, str]
        adm3_pcode -> city name.

    Returns
    -------
    dict | None
        lower: [(name, auc)], case_signal: [(name, outbreak_weeks)], each
        sorted by name, using the app's rules (src.views.confidence_groups);
        None when the file is missing.
    """
    if city_conf is None or city_conf.empty:
        return None
    lower, signal = [], []
    for r in city_conf.itertuples():
        name = names.get(r.adm3_pcode, r.adm3_pcode)
        if r.outbreak_weeks < config.CASE_SIGNAL_MAX_OUTBREAK_WEEKS:
            signal.append((name, int(r.outbreak_weeks)))
        elif r.auc < config.LOWER_CONFIDENCE_AUC:
            lower.append((name, float(r.auc)))
    return {"lower": sorted(lower), "case_signal": sorted(signal)}


def no_report_weeks(flags, cases):
    """How many city-weeks have no usable case report.

    Parameters
    ----------
    flags : pandas.DataFrame | None
        reporting_flags.csv (one row per flagged city-week).
    cases : pandas.DataFrame | None
        cases_weekly.csv rows (one per city-week).

    Returns
    -------
    dict | None
        flagged and total city-weeks; None when either is missing.
    """
    if flags is None or cases is None or cases.empty:
        return None
    return {"flagged": int(len(flags)), "total": int(len(cases))}


def event_peak(replay, event, horizon=config.REPLAY_HORIZON):
    """The week with the most cases in a replay event, and the level shown for it.

    Parameters
    ----------
    replay : pandas.DataFrame | None
        replay_weekly.csv.
    event : str
        e.g. config.REPLAY_EVENT_WASHI.
    horizon : int

    Returns
    -------
    dict | None
        cases, times (cases / that week's outbreak line), level, week; None
        when the event is missing.
    """
    r = _rows(replay, event=event, horizon=horizon)
    if r.empty or r.observed_cases.isna().all():
        return None
    top = r.loc[r.observed_cases.astype(float).idxmax()]
    times = (float(top.observed_cases) / float(top.threshold)
             if pd.notna(top.threshold) and top.threshold else None)
    return {"cases": float(top.observed_cases), "times": times, "level": top.alert_level,
            "week": top.target_week}
