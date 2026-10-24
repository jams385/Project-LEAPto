"""Pure builders for what the dashboard shows for one origin week + horizon.

The Streamlit layer (app/) only caches and renders these tables; the
ranking, level and wording rules live here so they can be tested. Inputs
are the contract-v2 tables (alerts with levels filled by
src.contract.assign_levels, observed cases, IMERG rainfall, thresholds).
"""

import numpy as np
import pandas as pd

from app import config

# CONSTANTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# Rainfall is "wetter/drier than usual" outside this ratio band of the
# same-week mean; at or above the city's wettest 5% it is "Wettest 5% of weeks".
RAIN_ABOVE_USUAL_RATIO = 1.25
RAIN_BELOW_USUAL_RATIO = 0.75
RAIN_WETTEST, RAIN_WETTER, RAIN_ABOUT, RAIN_DRIER = (
    "Wettest 5% of weeks", "Wetter than usual", "About usual", "Drier than usual")

SNAPSHOT_COLUMNS = [
    "adm3_pcode", "city_name", "province", "region", "island_group", "lat", "lon",
    "target_week", "alert_level", "forecast_level", "outbreak_prob", "rr_vs_usual",
    "threshold", "prev_level", "peak_level", "peak_horizon", "rank",
    "cases_week", "latest_cases", "latest_flag", "unusual_at",
    "rain_week_mm", "rain_usual_mm", "rain_status", "hazard_pct", "confidence", "city_auc",
]


# CITY CONFIDENCE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def confidence_groups(confidence=None, fallback=None):
    """Each city's confidence group, decided from the per-city test results.

    Rules (thresholds in app/config.py): fewer than
    CASE_SIGNAL_MAX_OUTBREAK_WEEKS outbreak weeks -> "case_signal"; else an
    AUC below LOWER_CONFIDENCE_AUC -> "lower"; else "standard".

    Parameters
    ----------
    confidence : pandas.DataFrame | None
        city_confidence.csv (adm3_pcode, outbreak_weeks, auc).
    fallback : dict[str, str] | None
        Groups to use when the table is missing or empty;
        config.CONFIDENCE_FALLBACK if None.

    Returns
    -------
    dict[str, str]
        adm3_pcode -> group. Cities not listed count as "standard" (see
        city_group).
    """
    if confidence is None or confidence.empty:
        return dict(config.CONFIDENCE_FALLBACK if fallback is None else fallback)
    groups = {}
    for r in confidence.itertuples():
        if r.outbreak_weeks < config.CASE_SIGNAL_MAX_OUTBREAK_WEEKS:
            groups[r.adm3_pcode] = "case_signal"
        elif r.auc < config.LOWER_CONFIDENCE_AUC:
            groups[r.adm3_pcode] = "lower"
        else:
            groups[r.adm3_pcode] = "standard"
    return groups


def city_group(groups, pcode):
    """One city's group ("standard" when unknown).

    Parameters
    ----------
    groups : dict[str, str]
        confidence_groups output.
    pcode : str

    Returns
    -------
    str
    """
    return groups.get(pcode, "standard")


def place_label(province):
    """Where a city is, in the list and drawer: its province, or "Metro Manila".

    Parameters
    ----------
    province : str | None
        cities.parquet province (NCR cities have "NCR, Third District" etc.).

    Returns
    -------
    str
        "" when missing.
    """
    if province is None or pd.isna(province):
        return ""
    return "Metro Manila" if str(province).startswith("NCR") else str(province)


def case_signal_cities(groups):
    """Cities that show "Case signal only" instead of a level.

    Parameters
    ----------
    groups : dict[str, str]
        confidence_groups output.

    Returns
    -------
    frozenset[str]
    """
    return frozenset(p for p, g in groups.items() if g == "case_signal")


# LEVELS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def level_rank(levels):
    """Order of forecast levels: Normal 0, Watch 1, Warning 2.

    Parameters
    ----------
    levels : pandas.Series of str | None

    Returns
    -------
    pandas.Series of float
        -1 for Case signal only, No report, None or unknown labels.
    """
    order = {lvl: i for i, lvl in enumerate(config.ALERT_LEVELS)}
    return levels.map(order).fillna(-1)


def display_levels(levels, pcodes, case_signal=frozenset()):
    """The level to show: case-signal cities show "Case signal only".

    "No report" always wins (the week was flagged as non-reporting); then a
    case-signal city shows "Case signal only" instead of a forecast level.

    Parameters
    ----------
    levels : pandas.Series of str | None
        Forecast levels (alerts.alert_level).
    pcodes : pandas.Series of str
        Same index, adm3_pcode of each row.
    case_signal : set[str]
        Cities with too few cases to forecast (case_signal_cities).

    Returns
    -------
    pandas.Series of object, same index. Missing levels (no forecast row)
    become "No forecast", never "Case signal only".
    """
    missing = levels.isna()
    shown = levels.astype(object).where(~missing, config.NO_FORECAST_LEVEL)
    signal = pcodes.isin(case_signal) & ~missing & (shown != config.NO_REPORT_LEVEL)
    return shown.where(~signal, config.CASE_SIGNAL_LEVEL)


def fmt_times(value):
    """Format a multiplier: "1.4×" below 2, whole numbers from 2 ("4×").

    Parameters
    ----------
    value : float | None

    Returns
    -------
    str | None
        None for missing values.
    """
    if value is None or pd.isna(value):
        return None
    return f"{value:.1f}×" if value < 1.95 else f"{value:.0f}×"


def usual_risk_text(rr, cap=config.MAX_RR_SHOWN):
    """Plain-words version of rr_vs_usual for one city-week.

    Parameters
    ----------
    rr : float | None
        Risk relative to a usual week for this city and time of year.
    cap : float
        Above this, say "over N× usual risk".

    Returns
    -------
    str | None
        "≈4× usual risk", "Below usual risk", "Over 10× usual risk", or None
        when rr is missing.
    """
    if rr is None or pd.isna(rr):
        return None
    if rr < 0.95:
        return "Below usual risk"
    if rr > cap:
        return f"Over {cap:.0f}× usual risk"
    return f"≈{fmt_times(rr)} usual risk"


def risk_vs_usual(level, outbreak_prob, base_rate):
    """How the week compares with a usual week, consistent with the level.

    The multiplier is outbreak_prob / base_rate (the share of all city-weeks
    that are outbreak weeks), the same comparison the level meanings use
    ("about 4× as likely as usual"). rr_vs_usual from alerts.csv is not used
    here until the modeling team defines it.

    Parameters
    ----------
    level : str | None
        Shown alert level.
    outbreak_prob : float | None
    base_rate : float | None

    Returns
    -------
    str | None
        "≈3× usual risk" for Watch / Warning, "At or below usual risk" for
        Normal, None for Limited data / No report or missing inputs.
    """
    if level == "Normal":
        return "At or below usual risk"
    if level not in ("Watch", "Warning") or outbreak_prob is None or pd.isna(outbreak_prob) \
            or not base_rate:
        return None
    return usual_risk_text(outbreak_prob / base_rate)


def usual_week_text(level, outbreak_prob, base_rate):
    """The comparison shown next to the badge: "≈4× a usual week".

    Parameters
    ----------
    level : str
        Shown alert level.
    outbreak_prob : float | None
    base_rate : float | None

    Returns
    -------
    str | None
        "≈4× a usual week" / "over 10× a usual week" for Watch and Warning,
        "At or below usual risk" for Normal, None otherwise.
    """
    text = risk_vs_usual(level, outbreak_prob, base_rate)
    if text and text.startswith(("≈", "Over")):
        return text.replace(" usual risk", " a usual week").replace("Over", "over")
    return text


def level_sentence(level, info, outbreak_prob, unusual_at=None):
    """The meaning sentence for one city-week, with its own multiplier.

    Watch / Warning say "about N×" with N = outbreak_prob / base rate, so the
    sentence always matches the "≈N× usual risk" figure next to it. "Case
    signal only" adds how many weekly cases are unusual; other levels use the
    configured sentence unchanged.

    Parameters
    ----------
    level : str
        Shown alert level.
    info : dict
        level_descriptions(...)[level] (meaning, base_rate).
    outbreak_prob : float | None
    unusual_at : float | None
        Weekly cases that would be above the outbreak line (case signal).

    Returns
    -------
    str
    """
    if level == config.CASE_SIGNAL_LEVEL and unusual_at is not None \
            and not pd.isna(unusual_at):
        return (f"{info['meaning'].rstrip('.')}: {int(unusual_at)} or more reported cases "
                "in a week is unusual here.")
    if level not in ("Watch", "Warning") or outbreak_prob is None or pd.isna(outbreak_prob) \
            or not info.get("base_rate"):
        return info["meaning"]
    times = min(outbreak_prob / info["base_rate"], config.MAX_RR_SHOWN)
    return config.LEVEL_MEANINGS[level].format(lift=fmt_times(times))


def level_descriptions(level_metrics=None, horizon=1):
    """Colour, meaning and track record for every display level.

    Wording and placeholder numbers come from app/config.py; a
    level_metrics.csv (model or placeholder) overrides hit rate, lift and
    base rate for the chosen horizon.

    Parameters
    ----------
    level_metrics : pandas.DataFrame | None
        level_metrics.csv rows (horizon, alert_level, hit_rate, base_rate,
        lift, n_weeks, capture_rate).
    horizon : int
        Horizon whose track record is shown.

    Returns
    -------
    dict[str, dict]
        For each of config.DISPLAY_LEVELS: color, meaning (str), track
        (str | None), hit_rate, lift, capture_rate, n_weeks (None when
        unknown), base_rate and from_metrics (bool).
    """
    rows = {}
    if level_metrics is not None and not level_metrics.empty:
        sub = level_metrics[level_metrics.horizon == horizon]
        rows = {r.alert_level: r for r in sub.itertuples()}
    base = next((r.base_rate for r in rows.values()), config.BASE_RATE)
    out = {}
    for level in config.DISPLAY_LEVELS:
        record = dict(config.LEVEL_TRACK_RECORD.get(level, {"hit_rate": None, "lift": None}))
        record.update(capture_rate=None, n_weeks=None)
        metric = rows.get(level)
        if metric is not None:
            record.update(hit_rate=metric.hit_rate, lift=metric.lift,
                          capture_rate=metric.capture_rate, n_weeks=metric.n_weeks)
        lift = fmt_times(record["lift"])
        meaning = config.LEVEL_MEANINGS[level].format(lift=lift or "several times")
        track = None
        if record["hit_rate"] is not None and not pd.isna(record["hit_rate"]):
            track = config.LEVEL_TRACK_TEXT.format(hit=f"{record['hit_rate']:.0%}", level=level)
            if level == "Normal":
                track = track[:-1] + f" (usual: {base:.0%})."
        out[level] = {"color": config.LEVEL_COLORS[level], "meaning": meaning, "track": track,
                      "base_rate": base, "from_metrics": metric is not None, **record}
    return out


# RANKING ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def rank_cities(snapshot):
    """Rank cities by the chance of an outbreak week, highest first.

    Parameters
    ----------
    snapshot : pandas.DataFrame
        Needs outbreak_prob and city_name.

    Returns
    -------
    pandas.DataFrame
        Sorted copy with an integer `rank` column (1 = highest chance).
        Cities without a chance go last, alphabetically.
    """
    out = snapshot.assign(_p=snapshot.outbreak_prob.fillna(-1))
    out = out.sort_values(["_p", "city_name"], ascending=[False, True], kind="mergesort")
    out["rank"] = np.arange(1, len(out) + 1)
    return out.drop(columns="_p").reset_index(drop=True)


# OBSERVED CONTEXT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def rain_context(rain_weekly, origin_week, quantile=config.HEAVY_RAIN_QUANTILE):
    """IMERG rainfall in the completed week before `origin_week` vs its usual.

    "Usual" is the city's mean rainfall for the same morbidity week number in
    every other year of the record (2003-2022); "wettest 5%" is the city's
    own heavy-rain line (heavy_rain_mm).

    Parameters
    ----------
    rain_weekly : pandas.DataFrame
        adm3_pcode, week_start, mw_year, mw_week, rain_mm.
    origin_week : Timestamp
        Forecast origin (Sunday).
    quantile : float
        The city's heavy-rain quantile (0.95 = wettest 5% of weeks).

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, rain_week_mm, rain_usual_mm, rain_status: RAIN_WETTEST at
        or above the city's heavy-rain line, else RAIN_WETTER / RAIN_ABOUT /
        RAIN_DRIER against the usual, or None with no comparison. Empty (same
        columns) when that week has no rainfall data.
    """
    last_week = pd.Timestamp(origin_week) - pd.Timedelta(days=7)
    week = rain_weekly[rain_weekly.week_start == last_week]
    cols = ["adm3_pcode", "rain_week_mm", "rain_usual_mm", "rain_status"]
    if week.empty:
        return pd.DataFrame(columns=cols)
    mw_week, mw_year = int(week.mw_week.iloc[0]), int(week.mw_year.iloc[0])
    others = rain_weekly[(rain_weekly.mw_week == mw_week) & (rain_weekly.mw_year != mw_year)]
    usual = others.groupby("adm3_pcode").rain_mm.mean().rename("rain_usual_mm")
    heavy = rain_weekly.groupby("adm3_pcode").rain_mm.quantile(quantile).rename("_heavy")
    out = week.set_index("adm3_pcode")[["rain_mm"]].rename(columns={"rain_mm": "rain_week_mm"})
    out = out.join(usual).join(heavy)
    ratio = out.rain_week_mm / out.rain_usual_mm.replace(0, np.nan)
    status = np.select(
        [out.rain_week_mm >= out._heavy, ratio > RAIN_ABOVE_USUAL_RATIO,
         ratio < RAIN_BELOW_USUAL_RATIO, ratio.notna()],
        [RAIN_WETTEST, RAIN_WETTER, RAIN_DRIER, RAIN_ABOUT], default="")
    out["rain_status"] = [s or None for s in status]
    return out.reset_index()[cols]


def cases_week_start(origin_week, delay=config.CASES_REPORT_DELAY_WEEKS):
    """Start of the latest week with reported cases at a forecast origin.

    Rain is known to the end of last week, but case reports arrive about a
    week late, so the latest reported week is `delay` weeks before that.

    Parameters
    ----------
    origin_week : Timestamp
        Forecast origin (Sunday).
    delay : int
        Reporting delay in weeks.

    Returns
    -------
    pandas.Timestamp
        A Sunday, (1 + delay) weeks before the origin.
    """
    return pd.Timestamp(origin_week) - pd.Timedelta(weeks=1 + delay)


def latest_cases(cases, origin_week, thresholds=None, delay=config.CASES_REPORT_DELAY_WEEKS):
    """Cases in the latest reported week at a forecast origin, vs that week's line.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, week_start, cases, optional
        reporting_flag).
    origin_week : Timestamp
    thresholds : pandas.DataFrame | None
        adm3_pcode, week_start, threshold. None leaves unusual_at empty.
    delay : int
        Reporting delay in weeks (cases_week_start).

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, latest_cases (float, NaN if not reported), latest_flag
        (reporting flag or None) and unusual_at = floor(threshold) + 1, the
        weekly count that would be above that week's outbreak line (NaN
        without a threshold). Empty when that week is outside the data.
    """
    start = cases_week_start(origin_week, delay)
    week = cases[cases.week_start == start]
    flag = week.reporting_flag if "reporting_flag" in week else pd.Series(None, index=week.index)
    out = pd.DataFrame({"adm3_pcode": week.adm3_pcode,
                        "latest_cases": week.cases.astype("float"),
                        "latest_flag": flag.astype(object).where(flag.notna(), None)})
    if thresholds is None or thresholds.empty:
        return out.assign(unusual_at=np.nan)
    line = thresholds[thresholds.week_start == start][["adm3_pcode", "threshold"]]
    out = out.merge(line, on="adm3_pcode", how="left")
    return out.assign(unusual_at=np.floor(out.threshold) + 1).drop(columns="threshold")


# SNAPSHOT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def city_snapshot(alerts, cities, cases, rain_weekly, hazard, origin_week, horizon, *,
                  thresholds=None, confidence=None, horizons=config.HORIZONS):
    """One row per city behind the map, the city list and the drawer.

    Parameters
    ----------
    alerts : pandas.DataFrame
        Alerts with alert_level filled (src.contract.assign_levels).
    cities : pandas.DataFrame
        cities.parquet (adm3_pcode, city_name, province, region, lat, lon).
    cases : pandas.DataFrame
        Observed weekly cases (with reporting_flag).
    rain_weekly : pandas.DataFrame
        IMERG weekly rainfall (adm3_pcode, week_start, mw_year, mw_week, rain_mm).
    hazard : pandas.DataFrame
        hazard_city.parquet (adm3_pcode + config.FLOOD_HAZARD_COLUMN).
    origin_week : Timestamp
        Forecast origin (Sunday).
    horizon : int
        1-3.
    thresholds : pandas.DataFrame | None
        Outbreak lines (adm3_pcode, week_start, threshold) for unusual_at.
    confidence : pandas.DataFrame | None
        city_confidence.csv; None/empty uses config.CONFIDENCE_FALLBACK.
    horizons : tuple[int, ...]
        Horizons shown in the app (for peak_level).

    Returns
    -------
    pandas.DataFrame
        SNAPSHOT_COLUMNS, ranked (rank 1 first). alert_level is the level to
        show (display_levels); forecast_level is the forecast's own level.
        prev_level is the shown level for the same horizon one origin
        earlier. peak_level / peak_horizon are the highest forecast level
        over `horizons` at this origin (earliest horizon on ties).
        cases_week / latest_cases are the latest reported week
        (cases_week_start); confidence is the city's group and city_auc its
        test AUC (NaN when unknown). Cities without a forecast row show
        "No forecast" and NaN numbers.
    """
    origin_week = pd.Timestamp(origin_week)
    groups = confidence_groups(confidence)
    signal = case_signal_cities(groups)
    keep = ["adm3_pcode", "target_week", "alert_level", "outbreak_prob", "rr_vs_usual",
            "threshold"]
    now = alerts[(alerts.origin_week == origin_week) & (alerts.horizon == horizon)][keep]
    prev = alerts[(alerts.origin_week == origin_week - pd.Timedelta(days=7))
                  & (alerts.horizon == horizon)][["adm3_pcode", "alert_level"]]
    prev = prev.assign(prev_level=display_levels(prev.alert_level, prev.adm3_pcode, signal))
    ahead = alerts[(alerts.origin_week == origin_week) & alerts.horizon.isin(horizons)].assign(
        _rank=lambda d: level_rank(d.alert_level))
    peak = (ahead.sort_values(["adm3_pcode", "_rank", "horizon"], ascending=[True, False, True])
            .drop_duplicates("adm3_pcode")[["adm3_pcode", "alert_level", "horizon"]]
            .rename(columns={"alert_level": "peak_level", "horizon": "peak_horizon"}))
    aucs = (confidence[["adm3_pcode", "auc"]].rename(columns={"auc": "city_auc"})
            if confidence is not None and not confidence.empty
            else pd.DataFrame({"adm3_pcode": pd.Series(dtype=object),
                               "city_auc": pd.Series(dtype=float)}))

    out = (cities[["adm3_pcode", "city_name", "province", "region", "lat", "lon"]]
           .merge(now, on="adm3_pcode", how="left")
           .merge(prev[["adm3_pcode", "prev_level"]], on="adm3_pcode", how="left")
           .merge(peak, on="adm3_pcode", how="left")
           .merge(latest_cases(cases, origin_week, thresholds), on="adm3_pcode", how="left")
           .merge(rain_context(rain_weekly, origin_week), on="adm3_pcode", how="left")
           .merge(hazard[["adm3_pcode", config.FLOOD_HAZARD_COLUMN]]
                  .rename(columns={config.FLOOD_HAZARD_COLUMN: "hazard_pct"}),
                  on="adm3_pcode", how="left")
           .merge(aucs, on="adm3_pcode", how="left"))
    out["island_group"] = out.region.map(config.REGION_TO_ISLAND_GROUP)
    out["confidence"] = [city_group(groups, p) for p in out.adm3_pcode]
    out["cases_week"] = cases_week_start(origin_week)
    out["forecast_level"] = out.alert_level.astype(object).where(out.alert_level.notna(), None)
    out["alert_level"] = display_levels(out.alert_level, out.adm3_pcode, signal)
    for col in ("prev_level", "peak_level", "latest_flag", "rain_status"):  # NaN -> None
        out[col] = out[col].astype(object).where(out[col].notna(), None)
    return rank_cities(out)[SNAPSHOT_COLUMNS]


# WORDING ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def trend_summary(level, prev_level, peak_level=None, peak_horizon=None):
    """The "time to act" line on the city card.

    Parameters
    ----------
    level, prev_level : str | None
        Shown level now and one origin week earlier (same horizon).
    peak_level : str | None
        Highest forecast level over weeks 1-3 at this origin.
    peak_horizon : int | float | None
        The week (1-3) of that peak.

    Returns
    -------
    str
        e.g. "Up from Normal last week. Rises to Warning in week 3." Only
        forecast levels (Normal / Watch / Warning) are compared; parts whose
        inputs are missing are left out; "" if nothing is known.
    """
    parts = []
    known = config.ALERT_LEVELS
    if level in known and prev_level in known:
        now, before = known.index(level), known.index(prev_level)
        if now > before:
            parts.append(f"Up from {prev_level} last week.")
        elif now < before:
            parts.append(f"Down from {prev_level} last week.")
        else:
            parts.append("Same level as last week.")
    if level in known and peak_level in known and peak_horizon is not None \
            and not pd.isna(peak_horizon):
        if known.index(peak_level) > known.index(level):
            parts.append(f"Rises to {peak_level} in week {int(peak_horizon)}.")
        elif level == "Normal" and peak_level == "Normal":
            parts.append("No raised risk expected in the next 3 weeks.")
    return " ".join(parts)


# CITY PANEL SERIES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

HORIZON_COLUMNS = ["horizon", "target_week", "alert_level", "outbreak_prob"]


def city_horizons(alerts, pcode, origin_week, case_signal=frozenset(), horizons=None):
    """The level for each forecast week of one city and origin.

    Parameters
    ----------
    alerts : pandas.DataFrame
        Alerts with alert_level filled.
    pcode : str
        City adm3_pcode.
    origin_week : Timestamp
    case_signal : set[str]
        Cities shown as "Case signal only" (display_levels).
    horizons : tuple[int, ...] | None
        Horizons to keep; None keeps every horizon in the file.

    Returns
    -------
    pandas.DataFrame
        HORIZON_COLUMNS sorted by horizon, alert_level as shown
        (display_levels); empty (same columns) without a forecast.
    """
    rows = alerts[(alerts.adm3_pcode == pcode)
                  & (alerts.origin_week == pd.Timestamp(origin_week))]
    if horizons is not None:
        rows = rows[rows.horizon.isin(horizons)]
    rows = rows.assign(alert_level=display_levels(rows.alert_level, rows.adm3_pcode,
                                                  case_signal))
    return rows.sort_values("horizon")[HORIZON_COLUMNS].reset_index(drop=True)


def city_timeseries(cases, rain_weekly, thresholds, pcode, origin_week, weeks_back=26,
                    weeks_ahead=3):
    """Weekly series for the "Rainfall vs reported cases" chart.

    Covers `weeks_back` weeks before the origin plus the forecast weeks.
    Reported cases are included for every week; weeks from the origin on are
    flagged is_future so the chart can show them as "reported later" (useful
    when looking back at past events). No predicted counts are shown.

    Parameters
    ----------
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, week_start, cases, reporting_flag).
    rain_weekly : pandas.DataFrame
        IMERG weekly rainfall (adm3_pcode, week_start, rain_mm).
    thresholds : pandas.DataFrame
        adm3_pcode, week_start, threshold.
    pcode : str
    origin_week : Timestamp
    weeks_back, weeks_ahead : int

    Returns
    -------
    pandas.DataFrame
        week_start, rain_mm, cases (float, NaN where missing), threshold,
        reporting_flag, is_future. One row per week, sorted; weeks outside
        the data keep NaN values.
    """
    origin = pd.Timestamp(origin_week)
    weeks = pd.date_range(origin - pd.Timedelta(weeks=weeks_back),
                          origin + pd.Timedelta(weeks=weeks_ahead - 1), freq="7D")
    out = pd.DataFrame({"week_start": weeks})
    c = cases[cases.adm3_pcode == pcode]
    c = c[["week_start", "cases"] + (["reporting_flag"] if "reporting_flag" in c else [])]
    r = rain_weekly[rain_weekly.adm3_pcode == pcode][["week_start", "rain_mm"]]
    t = thresholds[thresholds.adm3_pcode == pcode][["week_start", "threshold"]]
    for part in (r, c, t):
        out = out.merge(part, on="week_start", how="left")
    if "reporting_flag" not in out:
        out["reporting_flag"] = None
    out["cases"] = out.cases.astype("float")
    out["is_future"] = out.week_start >= origin
    return out[["week_start", "rain_mm", "cases", "threshold", "reporting_flag", "is_future"]]


# RAIN -> RISK TIMELINE ++++++++++++++++++++++++++++++++++++++++++++++++++++++

TIMELINE_COLUMNS = ["week_start", "rain_mm", "heavy", "is_future", "horizon",
                    "alert_level", "multiplier"]


def heavy_rain_mm(rain_weekly, pcode, quantile=config.HEAVY_RAIN_QUANTILE):
    """A city's heavy-rain week: its wettest 5% of weeks (2003-2022).

    Parameters
    ----------
    rain_weekly : pandas.DataFrame
        adm3_pcode, rain_mm.
    pcode : str
    quantile : float

    Returns
    -------
    float
        Weekly rainfall (mm) at that quantile; NaN without rainfall data.
    """
    values = rain_weekly.loc[rain_weekly.adm3_pcode == pcode, "rain_mm"].dropna()
    return float(values.quantile(quantile)) if not values.empty else np.nan


def risk_timeline(rain_weekly, alerts, pcode, origin_week, base_rate,
                  weeks_back=config.TIMELINE_WEEKS_BACK, heavy_mm=np.nan, *,
                  case_signal=frozenset(), horizons=config.HORIZONS):
    """Rows for the drawer's rain -> risk charts.

    The last `weeks_back` completed weeks carry IMERG rainfall and the level
    the app showed for that week (its next-week forecast, made the week it
    started); the forecast weeks (`horizons` at this origin) carry the
    expected risk multiplier outbreak_prob / base_rate and the shown level.
    No case counts.

    Parameters
    ----------
    rain_weekly : pandas.DataFrame
        adm3_pcode, week_start, rain_mm.
    alerts : pandas.DataFrame
        Alerts with alert_level filled.
    pcode : str
    origin_week : Timestamp
        Forecast origin; rain weeks end the week before it.
    base_rate : float | None
        Share of all city-weeks that are outbreak weeks.
    weeks_back : int
    heavy_mm : float
        Rain at or above this is flagged `heavy` (NaN: nothing flagged).
    case_signal : set[str]
        Cities shown as "Case signal only".
    horizons : tuple[int, ...]
        Forecast weeks to include.

    Returns
    -------
    pandas.DataFrame
        TIMELINE_COLUMNS sorted by week; past rows have NaN multiplier, future
        rows NaN rain. A past week with no forecast shows "No forecast".
        Missing weeks keep NaN values; without base_rate the multiplier is NaN.
    """
    origin = pd.Timestamp(origin_week)
    past = pd.DataFrame({"week_start": pd.date_range(
        origin - pd.Timedelta(weeks=weeks_back), origin - pd.Timedelta(weeks=1), freq="7D")})
    rain = rain_weekly[rain_weekly.adm3_pcode == pcode][["week_start", "rain_mm"]]
    shown = alerts[(alerts.adm3_pcode == pcode) & (alerts.horizon == 1)
                   & alerts.origin_week.isin(past.week_start)]
    shown = shown[["origin_week", "adm3_pcode", "alert_level"]].rename(
        columns={"origin_week": "week_start"})
    past = (past.merge(rain, on="week_start", how="left")
            .merge(shown, on="week_start", how="left").assign(is_future=False))
    past["alert_level"] = display_levels(past.alert_level, past.adm3_pcode.fillna(pcode),
                                         case_signal)
    past = past.drop(columns="adm3_pcode")
    ahead = city_horizons(alerts, pcode, origin, case_signal, horizons).rename(
        columns={"target_week": "week_start"})
    ahead = ahead.assign(
        is_future=True,
        multiplier=(ahead.outbreak_prob / base_rate) if base_rate else np.nan)
    out = pd.concat([past, ahead], ignore_index=True)
    out["heavy"] = out.rain_mm >= heavy_mm
    for col in ("horizon", "alert_level", "multiplier"):
        if col not in out:
            out[col] = np.nan
    return out[TIMELINE_COLUMNS].sort_values("week_start").reset_index(drop=True)


def lag_caption(lag_response):
    """One-line caption for the rain -> risk chart from the lag-response curve.

    Parameters
    ----------
    lag_response : pandas.DataFrame
        lag_response.csv (lag_weeks, rr_p95, ...): risk after a heavy-rain
        (P95) week vs a typical week, per lag.

    Returns
    -------
    str
        e.g. "Heavy rain raises risk +41% the next week and peaks about 2
        weeks later." config.LAG_CAPTION_FALLBACK when the curve is missing
        or has no lag-1 value.
    """
    if lag_response is None or lag_response.empty or 1 not in set(lag_response.lag_weeks):
        return config.LAG_CAPTION_FALLBACK
    curve = lag_response.set_index("lag_weeks").rr_p95
    peak = int(curve.idxmax())
    week = "week" if peak == 1 else "weeks"
    return (f"Heavy rain raises risk {curve[1] - 1:+.0%} the next week and peaks about "
            f"{peak} {week} later.")


def peak_caption(lag_response):
    """Short caption for the drawer's mini chart: when risk peaks after heavy rain.

    Parameters
    ----------
    lag_response : pandas.DataFrame | None
        lag_response.csv (lag_weeks, rr_p95).

    Returns
    -------
    str
        "Risk usually peaks N weeks after heavy rain." with N = the lag of
        the highest rr_p95; config.PEAK_CAPTION_FALLBACK without the curve.
    """
    if lag_response is None or lag_response.empty:
        return config.PEAK_CAPTION_FALLBACK
    peak = int(lag_response.set_index("lag_weeks").rr_p95.idxmax())
    return f"Risk usually peaks {peak} week{'' if peak == 1 else 's'} after heavy rain."


# FLOOD-PRONE BARANGAYS ++++++++++++++++++++++++++++++++++++++++++++++++++++++

def top_flood_barangays(flood_rank, pcode, n=config.TOP_FLOOD_BARANGAYS):
    """The city's most flood-prone barangays (Project NOAH, 100-yr high hazard).

    Parameters
    ----------
    flood_rank : pandas.DataFrame
        brgy_flood_rank.csv (adm3_pcode, rank, brgy_name, high_hazard_pct).
    pcode : str
    n : int

    Returns
    -------
    pandas.DataFrame
        Up to `n` rows sorted by rank; barangays with no high-hazard area are
        left out. Empty when the city or the file is missing.
    """
    if flood_rank is None or flood_rank.empty:
        return pd.DataFrame(columns=["rank", "brgy_name", "high_hazard_pct"])
    rows = flood_rank[(flood_rank.adm3_pcode == pcode) & (flood_rank.high_hazard_pct > 0)]
    return rows.sort_values("rank").head(n).reset_index(drop=True)


# FLOOD ALERT AND BACKGROUND WATCH ++++++++++++++++++++++++++++++++++++++++++

def flood_alert_weeks_left(start, week, weeks=config.FLOOD_ALERT_WEEKS):
    """Weeks a Flood alert still covers, counting the week shown.

    Parameters
    ----------
    start : Timestamp | None
        The forecast week the alert was switched on for (None = off).
    week : Timestamp
        The forecast week shown.
    weeks : int
        How long an alert lasts.

    Returns
    -------
    int
        weeks .. 1 while `week` is within `weeks` weeks from `start`; 0 when
        off, before `start` or after it has run out.
    """
    if start is None:
        return 0
    passed = (pd.Timestamp(week) - pd.Timestamp(start)).days // 7
    return weeks - passed if 0 <= passed < weeks else 0


def watch_weeks_per_year(alerts, pcode, horizon):
    """How many weeks a year a city is at Watch, over the test years.

    Parameters
    ----------
    alerts : pandas.DataFrame
        Alerts with alert_level filled (adm3_pcode, horizon, target_week).
    pcode : str
    horizon : int

    Returns
    -------
    float
        Watch weeks / years covered, where years = weeks with a forecast
        level / 52.18 (week-based, since test years start on a Sunday that
        can fall in late December); NaN without any.
    """
    rows = alerts[(alerts.adm3_pcode == pcode) & (alerts.horizon == horizon)
                  & alerts.alert_level.isin(config.ALERT_LEVELS)]
    if rows.empty:
        return np.nan
    return float((rows.alert_level == "Watch").sum() / (len(rows) / (365.25 / 7)))
