"""Data contract v2: the modeling team's files the app reads.

Schemas and rules are documented in docs/DATA_CONTRACT.md. Each part is one
CSV, looked up in this order:
    1. data/model_outputs/<file>            modeling team (delivered, or
                                            converted by scripts/import_analysis_outputs.py)
    2. data/processed/<stem>_baseline.csv   labelled placeholder written by
                                            scripts/make_baseline_forecast.py
    3. nothing                              empty table, kind="missing"
Observed cases, IMERG rainfall and thresholds have a different last resort:
the app's own raw-CSV pipeline and threshold logic, reported as
kind="fallback" so the UI can show a visible warning.

Pure functions only (no Streamlit); app/data.py adds caching.
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app import config
from src.load_outputs import ContractError, OutputSource, load_with_fallback, read_contract_csv
from src.risk import compute_thresholds
from src.weeks import morbidity_week, week_starts, weeks_in_year

log = logging.getLogger(__name__)

# VALIDATION HELPERS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++

KNOWN_PCODES = frozenset(config.ANALYSIS_CITY_PCODES.values())


def _require_sundays(df, *cols):
    """Raise ContractError unless every non-null date in `cols` is a Sunday.

    Parameters
    ----------
    df : pandas.DataFrame
        Table with parsed datetime columns.
    *cols : str
        Date columns to check.

    Returns
    -------
    None
    """
    for col in cols:
        if (df[col].dropna().dt.dayofweek != 6).any():
            raise ContractError(f"{col} must be a Sunday (start of a DOH morbidity week)")


def _require_unique(df, keys):
    """Raise ContractError if `keys` do not identify rows uniquely.

    Parameters
    ----------
    df : pandas.DataFrame
    keys : list[str]

    Returns
    -------
    None
    """
    if df.duplicated(keys).any():
        raise ContractError(f"duplicate {' x '.join(keys)} rows")


def _require_between(series, lo, hi, name):
    """Raise ContractError if a non-null value of `series` is outside [lo, hi].

    Parameters
    ----------
    series : pandas.Series of numbers
    lo, hi : float | None
        Bounds; None means unbounded on that side.
    name : str
        Column name for the message.

    Returns
    -------
    None. A non-numeric column also raises ContractError.
    """
    values = pd.to_numeric(series, errors="coerce")
    if values.isna().sum() > series.isna().sum():
        raise ContractError(f"{name} must be numeric")
    values = values.dropna()
    if (lo is not None and (values < lo).any()) or (hi is not None and (values > hi).any()):
        raise ContractError(f"{name} must be between {lo} and {hi}")


def _as_bool(series, name):
    """Coerce True/False/1/0/TRUE/FALSE/empty to a nullable boolean Series.

    Parameters
    ----------
    series : pandas.Series
        As read from CSV (bool, number or text).
    name : str
        Column name for the error message.

    Returns
    -------
    pandas.Series of dtype "boolean" (NA for empty cells). Raises
    ContractError on any other value.
    """
    text = series.astype("string").str.strip().str.lower()
    mapping = {"true": True, "false": False, "1": True, "0": False,
               "1.0": True, "0.0": False}
    out = text.map(mapping)
    if (out.isna() & text.notna() & (text != "")).any():
        raise ContractError(f"{name} must be true/false")
    return out.astype("boolean")


def _warn_unknown_pcodes(df):
    """Warnings for adm3_pcodes outside the 12 monitored cities.

    Parameters
    ----------
    df : pandas.DataFrame with adm3_pcode.

    Returns
    -------
    list[str]
        Empty when every code is known.
    """
    unknown = sorted(set(df.adm3_pcode.dropna()) - KNOWN_PCODES)
    return [f"unknown adm3_pcode values ignored by the map: {unknown}"] if unknown else []


# VALIDATORS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def validate_alerts(df):
    """Check alerts.csv (normalises observed_outbreak / text columns in place).

    Parameters
    ----------
    df : pandas.DataFrame
        ALERTS columns with parsed origin_week / target_week.

    Returns
    -------
    list[str]
        Warnings: unknown pcodes, and an empty alert_level column (the app
        then assigns levels from cut-offs, see assign_levels).

    Raises
    ------
    ContractError
        Non-Sunday weeks, horizon outside config.ALERT_HORIZONS, wrong
        target_week, outbreak_prob outside 0-1, negative rr/threshold/cases,
        unknown alert_level or reporting_flag, or duplicate
        city x origin x horizon rows.
    """
    _require_sundays(df, "origin_week", "target_week")
    if not df.horizon.isin(config.ALERT_HORIZONS).all():
        raise ContractError(f"horizon must be one of {config.ALERT_HORIZONS}")
    expected = df.origin_week + pd.to_timedelta((df.horizon - 1) * 7, unit="D")
    if (expected != df.target_week).any():
        raise ContractError("target_week must equal origin_week + (horizon - 1) weeks")
    _require_between(df.outbreak_prob, 0, 1, "outbreak_prob")
    for col in ("rr_vs_usual", "threshold", "observed_cases"):
        _require_between(df[col], 0, None, col)
    df["observed_outbreak"] = _as_bool(df.observed_outbreak, "observed_outbreak")
    for col in ("alert_level", "reporting_flag"):
        df[col] = df[col].astype(object).where(df[col].notna() & (df[col] != ""), None)
    bad = set(df.alert_level.dropna()) - set(config.ALL_LEVELS)
    if bad:
        raise ContractError(f"alert_level must be one of {config.ALL_LEVELS}, got {sorted(bad)}")
    bad = set(df.reporting_flag.dropna()) - set(config.REPORTING_FLAGS)
    if bad:
        raise ContractError(f"reporting_flag must be empty or one of {config.REPORTING_FLAGS}")
    _require_unique(df, ["adm3_pcode", "origin_week", "horizon"])
    warnings = _warn_unknown_pcodes(df)
    if df.alert_level.isna().all():
        warnings.append("alert_level is empty: levels are assigned from the cut-offs in "
                        "app/config.py (placeholder until the modeling team sets them)")
    return warnings


def validate_level_metrics(df):
    """Check level_metrics.csv.

    Parameters
    ----------
    df : pandas.DataFrame with LEVEL_METRICS columns.

    Returns
    -------
    list[str] (always empty today).

    Raises
    ------
    ContractError
        Unknown horizon or level, counts below 0, rates outside 0-1,
        negative lift/lead, or duplicate horizon x level rows.
    """
    if not df.horizon.isin(config.ALERT_HORIZONS).all():
        raise ContractError(f"horizon must be one of {config.ALERT_HORIZONS}")
    if not df.alert_level.isin(config.ALERT_LEVELS).all():
        raise ContractError(f"alert_level must be one of {config.ALERT_LEVELS}")
    for col in ("n_weeks", "n_outbreaks", "lift", "median_lead_weeks"):
        _require_between(df[col], 0, None, col)
    for col in ("hit_rate", "base_rate", "capture_rate") + (
            ("prob_cutoff",) if "prob_cutoff" in df else ()):
        _require_between(df[col], 0, 1, col)
    _require_unique(df, ["horizon", "alert_level"])
    return []


def validate_auc(df):
    """Check auc.csv.

    Parameters
    ----------
    df : pandas.DataFrame with AUC columns.

    Returns
    -------
    list[str]
        A warning naming any of config.AUC_REQUIRED_MODELS that is absent.

    Raises
    ------
    ContractError
        Unknown horizon or scope, AUC outside 0-1, empty model name,
        duplicates (per horizon x model x scope when `scope` is present).
    """
    if not df.horizon.isin(config.ALERT_HORIZONS).all():
        raise ContractError(f"horizon must be one of {config.ALERT_HORIZONS}")
    _require_between(df.auc, 0, 1, "auc")
    if df.model.isna().any() or (df.model.astype(str).str.strip() == "").any():
        raise ContractError("model must not be empty")
    if "scope" in df and not df.scope.fillna(config.AUC_SCOPES[0]).isin(config.AUC_SCOPES).all():
        raise ContractError(f"scope must be one of {config.AUC_SCOPES}")
    _require_unique(df, ["horizon", "model"] + (["scope"] if "scope" in df else []))
    absent = [m for m in config.AUC_REQUIRED_MODELS if m not in set(df.model)]
    return [f"auc.csv has no rows for {absent}"] if absent else []


def validate_rain(df):
    """Check rain_weekly_imerg.csv.

    Parameters
    ----------
    df : pandas.DataFrame with RAIN columns (week_start parsed).

    Returns
    -------
    list[str]
        Unknown-pcode warnings.

    Raises
    ------
    ContractError
        Non-Sunday weeks, negative rain, duplicate city x week rows.
    """
    _require_sundays(df, "week_start")
    for col in ("rain_mm_7d", "rain_mm_7d_late"):
        if col in df:
            _require_between(df[col], 0, None, col)
    _require_unique(df, ["adm3_pcode", "week_start"])
    return _warn_unknown_pcodes(df)


def validate_lag_response(df):
    """Check lag_response.csv (v2: one row per lag, P95 and P99 columns).

    Parameters
    ----------
    df : pandas.DataFrame with LAG columns.

    Returns
    -------
    list[str] (always empty today).

    Raises
    ------
    ContractError
        Lags not whole numbers in 0-10, non-positive RR, lower > upper,
        duplicate lags.
    """
    _require_between(df.lag_weeks, 0, 10, "lag_weeks")
    if (pd.to_numeric(df.lag_weeks) % 1 != 0).any():
        raise ContractError("lag_weeks must be whole weeks")
    for level in ("p95", "p99"):
        rr = pd.to_numeric(df[f"rr_{level}"], errors="coerce")
        if rr.isna().any() or (rr <= 0).any():
            raise ContractError(f"rr_{level} must be positive")
        lo, hi = f"rr_{level}_lower", f"rr_{level}_upper"
        if lo in df and hi in df and (df[lo] > df[hi]).any():
            raise ContractError(f"{lo} is greater than {hi} in some rows")
    _require_unique(df, ["lag_weeks"])
    return []


def validate_reporting_flags(df):
    """Check reporting_flags.csv (an empty list of flagged weeks is valid).

    Parameters
    ----------
    df : pandas.DataFrame with FLAG columns (week_start parsed).

    Returns
    -------
    list[str]
        Unknown-pcode warnings.

    Raises
    ------
    ContractError
        Non-Sunday weeks, unknown flags, duplicate city x week rows.
    """
    _require_sundays(df, "week_start")
    if not df.flag.isin(config.REPORTING_FLAGS).all():
        raise ContractError(f"flag must be one of {config.REPORTING_FLAGS}")
    _require_unique(df, ["adm3_pcode", "week_start"])
    return _warn_unknown_pcodes(df)


def validate_thresholds_app(df):
    """Check thresholds_2023_for_app.csv (as delivered by the modeling team).

    Parameters
    ----------
    df : pandas.DataFrame with city, year, mw, thr_app (+ optional columns).

    Returns
    -------
    list[str] (always empty today).

    Raises
    ------
    ContractError
        City names not in config.ANALYSIS_CITY_PCODES, MW outside 1-53,
        missing or negative thr_app, duplicate city x year x mw rows.
    """
    unknown = sorted(set(df.city) - set(config.ANALYSIS_CITY_PCODES))
    if unknown:
        raise ContractError(f"unknown city names {unknown}; add them to "
                            "config.ANALYSIS_CITY_PCODES")
    _require_between(df.mw, 1, 53, "mw")
    if df.thr_app.isna().any():
        raise ContractError("thr_app must not be empty")
    _require_between(df.thr_app, 0, None, "thr_app")
    _require_unique(df, ["city", "year", "mw"])
    return []


def validate_cases(df):
    """Check cases_weekly.csv.

    Parameters
    ----------
    df : pandas.DataFrame with CASES columns (week_start parsed).

    Returns
    -------
    list[str]
        Unknown-pcode warnings.

    Raises
    ------
    ContractError
        Non-Sunday weeks, MW outside 1-53, negative cases, duplicates.
    """
    _require_sundays(df, "week_start")
    _require_between(df.mw_week, 1, 53, "mw_week")
    _require_between(df.cases, 0, None, "cases")
    _require_unique(df, ["adm3_pcode", "week_start"])
    return _warn_unknown_pcodes(df)


def validate_thresholds_history(df):
    """Check thresholds_weekly.csv (historical epidemic thresholds).

    Parameters
    ----------
    df : pandas.DataFrame with THRESHOLD_HISTORY columns (week_start parsed).

    Returns
    -------
    list[str]
        Unknown-pcode warnings.

    Raises
    ------
    ContractError
        Non-Sunday weeks, negative thresholds, duplicates.
    """
    _require_sundays(df, "week_start")
    _require_between(df.threshold, 0, None, "threshold")
    _require_unique(df, ["adm3_pcode", "week_start"])
    return _warn_unknown_pcodes(df)


def validate_city_confidence(df):
    """Check city_confidence.csv (per-city test AUC and outbreak weeks).

    Parameters
    ----------
    df : pandas.DataFrame with adm3_pcode, outbreak_weeks, auc.

    Returns
    -------
    list[str]
        Unknown-pcode warnings.

    Raises
    ------
    ContractError
        AUC outside 0-1, negative outbreak weeks, duplicate cities.
    """
    _require_between(df.auc, 0, 1, "auc")
    _require_between(df.outbreak_weeks, 0, None, "outbreak_weeks")
    _require_unique(df, ["adm3_pcode"])
    return _warn_unknown_pcodes(df)


def validate_replay(df):
    """Check replay_weekly.csv (stage 6 "as of then" forecasts for the case studies).

    Parameters
    ----------
    df : pandas.DataFrame with event, adm3_pcode, origin_week, horizon,
        target_week, outbreak_prob, alert_level, observed_cases (+ optional).

    Returns
    -------
    list[str]
        Unknown-pcode warnings.

    Raises
    ------
    ContractError
        Non-Sunday weeks, horizon outside config.ALERT_HORIZONS, target_week
        not origin_week + 7 x (horizon - 1), chance outside 0-1, a level that
        is not Normal / Watch / Warning, duplicates.
    """
    _require_sundays(df, "origin_week", "target_week")
    if not df.horizon.isin(config.ALERT_HORIZONS).all():
        raise ContractError(f"horizon must be one of {config.ALERT_HORIZONS}")
    expected = df.origin_week + pd.to_timedelta((df.horizon - 1) * 7, unit="D")
    if not (df.target_week == expected).all():
        raise ContractError("target_week must equal origin_week + 7 x (horizon - 1)")
    _require_between(df.outbreak_prob.dropna(), 0, 1, "outbreak_prob")
    bad = set(df.alert_level.dropna()) - set(config.ALERT_LEVELS)
    if bad:
        raise ContractError(f"alert_level must be one of {config.ALERT_LEVELS}, got {sorted(bad)}")
    _require_unique(df, ["event", "adm3_pcode", "target_week", "horizon"])
    return _warn_unknown_pcodes(df)


EPISODE_KINDS = ("2+ weeks", "single week")


def validate_episodes(df):
    """Check episodes.csv (the level of each outbreak's first week).

    Parameters
    ----------
    df : pandas.DataFrame with horizon, episode, alert_level, n, share.

    Returns
    -------
    list[str]
        Empty.

    Raises
    ------
    ContractError
        Horizon outside config.ALERT_HORIZONS, unknown episode kind or level,
        share outside 0-1, negative n, duplicates.
    """
    if not df.horizon.isin(config.ALERT_HORIZONS).all():
        raise ContractError(f"horizon must be one of {config.ALERT_HORIZONS}")
    if not df.episode.isin(EPISODE_KINDS).all():
        raise ContractError(f"episode must be one of {EPISODE_KINDS}")
    if not df.alert_level.isin(config.ALERT_LEVELS).all():
        raise ContractError(f"alert_level must be one of {config.ALERT_LEVELS}")
    _require_between(df.share, 0, 1, "share")
    _require_between(df.n, 0, None, "n")
    _require_unique(df, ["horizon", "episode", "alert_level"])
    return []


def validate_rain_gain(df):
    """Check rain_gain.csv (what rain adds to the forecast, per weeks ahead).

    Parameters
    ----------
    df : pandas.DataFrame with horizon, gain_per_week, lo, hi.

    Returns
    -------
    list[str]
        Empty.

    Raises
    ------
    ContractError
        Horizon outside 1-4, lo above hi, duplicates.
    """
    _require_between(df.horizon, 1, 4, "horizon")
    if (df.lo > df.hi).any():
        raise ContractError("lo must not be above hi")
    _require_unique(df, ["horizon"])
    return []


# PARTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@dataclass(frozen=True)
class Part:
    """One contract file: its columns, date columns and validator.

    Attributes
    ----------
    name : str
        Key in config.CONTRACT_FILES.
    columns : tuple[str, ...]
        Required columns.
    validator : callable
        DataFrame -> list of warnings; raises ContractError.
    optional : tuple[str, ...]
        Columns kept when present.
    dates : tuple[str, ...]
        Columns parsed as YYYY-MM-DD.
    allow_empty : bool
        Whether a header with no rows is valid.
    """

    name: str
    columns: tuple
    validator: object
    optional: tuple = field(default_factory=tuple)
    dates: tuple = field(default_factory=tuple)
    allow_empty: bool = False

    @property
    def filename(self):
        """The contract file name, from config.CONTRACT_FILES."""
        return config.CONTRACT_FILES[self.name]


PARTS = {p.name: p for p in (
    Part("alerts",
         ("adm3_pcode", "origin_week", "horizon", "target_week", "outbreak_prob",
          "rr_vs_usual", "alert_level", "observed_cases", "observed_outbreak", "threshold",
          "reporting_flag"),
         validate_alerts, optional=("days", "model_version"),
         dates=("origin_week", "target_week")),
    Part("level_metrics",
         ("horizon", "alert_level", "n_weeks", "n_outbreaks", "hit_rate", "base_rate", "lift",
          "capture_rate", "median_lead_weeks"),
         validate_level_metrics, optional=("prob_cutoff",)),
    Part("auc", ("horizon", "model", "auc"), validate_auc,
         optional=("scope", "n_weeks", "note")),
    Part("rain_imerg", ("adm3_pcode", "week_start", "rain_mm_7d"), validate_rain,
         optional=("mw_year", "mw_week", "rain_mm_7d_late"), dates=("week_start",)),
    Part("lag_response", ("lag_weeks", "rr_p95", "rr_p99"), validate_lag_response,
         optional=("rr_p95_lower", "rr_p95_upper", "rr_p99_lower", "rr_p99_upper")),
    Part("reporting_flags", ("adm3_pcode", "week_start", "flag"), validate_reporting_flags,
         dates=("week_start",), allow_empty=True),
    Part("thresholds_app", ("city", "year", "mw", "thr_app"), validate_thresholds_app,
         optional=("thr_app_source", "city_type", "cases_needed_app", "signal_text")),
    Part("cases", ("adm3_pcode", "week_start", "mw_year", "mw_week", "cases"), validate_cases,
         optional=("days",), dates=("week_start",)),
    Part("thresholds_history", ("adm3_pcode", "week_start", "mw_year", "mw_week", "threshold"),
         validate_thresholds_history, optional=("source",), dates=("week_start",)),
    Part("city_confidence", ("adm3_pcode", "outbreak_weeks", "auc"), validate_city_confidence,
         optional=("city",)),
    Part("episodes", ("horizon", "episode", "alert_level", "n", "share"), validate_episodes),
    Part("rain_gain", ("horizon", "gain_per_week", "lo", "hi"), validate_rain_gain),
    Part("replay", ("event", "adm3_pcode", "origin_week", "horizon", "target_week",
                    "outbreak_prob", "alert_level", "observed_cases"),
         validate_replay, optional=("threshold", "observed_outbreak", "model_version"),
         dates=("origin_week", "target_week")),
)}


def load_part(name, *, model_dir=None, processed_dir=None):
    """Load one contract part: model file, else baseline placeholder, else empty.

    Parameters
    ----------
    name : str
        A key of PARTS.
    model_dir, processed_dir : pathlib.Path | None
        Overrides for config.MODEL_OUTPUTS_DIR / config.PROCESSED_DIR.

    Returns
    -------
    tuple[pandas.DataFrame, OutputSource]
        Validated table and where it came from. Never raises for contract
        problems (the reasons are in OutputSource.reason and the log).
    """
    part = PARTS[name]
    return load_with_fallback(part.filename, list(part.columns), part.validator,
                              date_columns=part.dates, optional_columns=part.optional,
                              allow_empty=part.allow_empty,
                              model_dir=model_dir, processed_dir=processed_dir)


def load_model_file(name, *, model_dir=None):
    """Load only the modeling team's copy of a part (no baseline fallback).

    Parameters
    ----------
    name : str
        A key of PARTS.
    model_dir : pathlib.Path | None
        Override for config.MODEL_OUTPUTS_DIR.

    Returns
    -------
    tuple[pandas.DataFrame | None, str]
        (validated table, "ok") or (None, why it is unusable). Never raises
        for contract problems.
    """
    part = PARTS[name]
    path = (config.MODEL_OUTPUTS_DIR if model_dir is None else model_dir) / part.filename
    try:
        df = read_contract_csv(path, list(part.columns), part.dates,
                               optional_columns=part.optional, allow_empty=part.allow_empty)
        part.validator(df)
    except ContractError as err:
        return None, str(err)
    return df, "ok"


def load_auc(**dirs):
    """Load auc.csv, filling required models it lacks from the baseline file.

    The modeling team may deliver only some comparisons (e.g. no
    "last_week_only" model). Rows for missing required models are taken from
    the baseline placeholder and marked source="baseline", so the UI can put
    the "Baseline, model pending" label on those rows only.

    Parameters
    ----------
    **dirs
        model_dir / processed_dir overrides.

    Returns
    -------
    tuple[pandas.DataFrame, OutputSource]
        AUC columns + `source` ("model" / "baseline") + `scope` ("all weeks"
        when the file has none). The OutputSource is the
        model file's, with a warning listing borrowed models; kind="baseline"
        if only the placeholder exists; "missing" if neither.
    """
    df, src = load_part("auc", **dirs)
    df = df.assign(source=src.kind if src.kind != "missing" else None,
                   scope=df.scope.fillna(config.AUC_SCOPES[0]) if "scope" in df
                   else config.AUC_SCOPES[0])
    if src.kind != "model":
        return df, src
    absent = [m for m in config.AUC_REQUIRED_MODELS if m not in set(df.model)]
    if not absent:
        return df, src
    processed = dirs.get("processed_dir")
    base, base_src = load_part("auc", model_dir=processed or config.PROCESSED_DIR,
                               processed_dir=processed or config.PROCESSED_DIR)
    borrowed = base[base.model.isin(absent)].assign(source="baseline",
                                                    scope=config.AUC_SCOPES[0])
    if borrowed.empty:
        return df, src
    note = (f"{', '.join(sorted(borrowed.model.unique()))} rows are baseline placeholders "
            "(model pending)")
    return (pd.concat([df, borrowed], ignore_index=True),
            OutputSource(src.kind, src.path, src.reason, src.warnings + (note,)))


# ALERT LEVELS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def level_cutoffs(level_metrics=None, source_kind=None, *, default=None):
    """Probability cut-offs for Watch / Warning.

    Parameters
    ----------
    level_metrics : pandas.DataFrame | None
        Loaded level_metrics.csv. Its prob_cutoff column overrides the
        defaults, but only when it is the modeling team's file.
    source_kind : str | None
        OutputSource.kind of `level_metrics`.
    default : dict[str, float] | None
        Defaults; config.LEVEL_CUTOFFS if None.

    Returns
    -------
    tuple[dict[str, float], str]
        ({"Watch": p, "Warning": p}, "model" or "config").
    """
    cutoffs = dict(config.LEVEL_CUTOFFS if default is None else default)
    if (source_kind != "model" or level_metrics is None
            or "prob_cutoff" not in level_metrics or level_metrics.empty):
        return cutoffs, "config"
    found = (level_metrics.dropna(subset=["prob_cutoff"])
             .groupby("alert_level").prob_cutoff.min())
    found = {k: float(v) for k, v in found.items() if k in cutoffs}
    if not found:
        return cutoffs, "config"
    cutoffs.update(found)
    return cutoffs, "model"


def assign_levels(alerts, cutoffs=None):
    """Fill alert_level where the file leaves it empty.

    Rules, in order: a reporting_flag -> "No report"; no outbreak_prob (e.g.
    no outbreak line that week) -> "No forecast"; outbreak_prob >= Warning cut-off -> "Warning"; >= Watch
    cut-off -> "Watch"; otherwise "Normal". Levels already in the file are
    kept as delivered.

    Parameters
    ----------
    alerts : pandas.DataFrame
        alerts.csv rows (outbreak_prob, alert_level, reporting_flag).
    cutoffs : dict[str, float] | None
        {"Watch": p, "Warning": p}; config.LEVEL_CUTOFFS if None.

    Returns
    -------
    pandas.DataFrame
        Copy with alert_level filled and `level_source` ("model" for
        delivered levels, "cut-offs" for app-assigned). Empty in, empty out.
    """
    cutoffs = config.LEVEL_CUTOFFS if cutoffs is None else cutoffs
    out = alerts.copy()
    prob = pd.to_numeric(out.outbreak_prob, errors="coerce")
    flagged = out.reporting_flag.notna() & (out.reporting_flag.astype(str) != "")
    assigned = np.select(
        [flagged.to_numpy(), prob.isna().to_numpy(),
         (prob >= cutoffs["Warning"]).to_numpy(), (prob >= cutoffs["Watch"]).to_numpy()],
        [config.NO_REPORT_LEVEL, config.NO_FORECAST_LEVEL, "Warning", "Watch"],
        default="Normal").astype(object)
    delivered = out.alert_level.notna()
    out["level_source"] = np.where(delivered, "model", "cut-offs")
    out["alert_level"] = out.alert_level.where(delivered, pd.Series(assigned, index=out.index))
    return out


# OBSERVED DATA (cases, rain, flags, thresholds) +++++++++++++++++++++++++++++

THRESHOLD_TABLE_COLUMNS = ["adm3_pcode", "mw_year", "mw_week", "week_start", "threshold",
                           "source"]


def thresholds_from_contract(history, app_table):
    """Combine historical and 2023 model thresholds into one weekly table.

    Parameters
    ----------
    history : pandas.DataFrame
        thresholds_weekly.csv (adm3_pcode, week_start, mw_year, mw_week,
        threshold, optional source). May be empty.
    app_table : pandas.DataFrame
        thresholds_2023_for_app.csv (city, year, mw, thr_app, optional
        thr_app_source). May be empty.

    Returns
    -------
    pandas.DataFrame
        THRESHOLD_TABLE_COLUMNS sorted by city and week; thresholds are
        cases per 7 days. In a 53-week year without an MW53 row, MW53 copies
        MW52 (the app's rule). History wins where both cover a week. Empty
        inputs give an empty frame with these columns.
    """
    frames = []
    if not history.empty:
        frames.append(history.assign(source=history.get("source", "modeling team"))
                      [THRESHOLD_TABLE_COLUMNS])
    if not app_table.empty:
        app = pd.DataFrame({
            "adm3_pcode": app_table.city.map(config.ANALYSIS_CITY_PCODES).to_numpy(),
            "mw_year": app_table.year.astype(int).to_numpy(),
            "mw_week": app_table.mw.astype(int).to_numpy(),
            "threshold": app_table.thr_app.to_numpy(dtype=float),
            "source": (app_table.thr_app_source if "thr_app_source" in app_table
                       else pd.Series("modeling team", index=app_table.index)).to_numpy(),
        })
        wk53 = []
        for (pcode, year), grp in app.groupby(["adm3_pcode", "mw_year"]):
            if weeks_in_year(int(year)) == 53 and 53 not in set(grp.mw_week):
                wk53.append(grp[grp.mw_week == 52].assign(mw_week=53))
        app = pd.concat([app, *wk53], ignore_index=True)
        app["week_start"] = week_starts(app.mw_year, app.mw_week).to_numpy()
        frames.append(app[THRESHOLD_TABLE_COLUMNS])
    if not frames:
        return pd.DataFrame(columns=THRESHOLD_TABLE_COLUMNS)
    out = pd.concat(frames, ignore_index=True).drop_duplicates(["adm3_pcode", "week_start"])
    out["week_start"] = pd.to_datetime(out.week_start)
    return out.sort_values(["adm3_pcode", "week_start"]).reset_index(drop=True)


def thresholds_table(model_thresholds, cases):
    """The weekly epidemic thresholds the app uses.

    The modeling team's thresholds when they exist; otherwise the app's own
    DOH computation (mean + 2 SD of the same week in earlier years), which
    load_observed reports as a fallback.

    Parameters
    ----------
    model_thresholds : pandas.DataFrame
        thresholds_from_contract output (may be empty).
    cases : pandas.DataFrame
        Observed weekly cases (adm3_pcode, mw_year, mw_week, cases), used
        only for the fallback.

    Returns
    -------
    pandas.DataFrame
        THRESHOLD_TABLE_COLUMNS (threshold in cases per 7 days; NaN where the
        fallback has too little history). Empty if there is nothing to use.
    """
    if not model_thresholds.empty:
        return model_thresholds[THRESHOLD_TABLE_COLUMNS]
    app = compute_thresholds(cases)
    return (app.rename(columns={"epidemic_threshold": "threshold"})
            .assign(source="app: DOH mean + 2 SD (fallback)")[THRESHOLD_TABLE_COLUMNS])


def _fallback_source(reason, model_src):
    """OutputSource for the app's own pipeline, keeping why the model was skipped.

    Parameters
    ----------
    reason : str
        What the fallback is.
    model_src : OutputSource
        The failed contract load.

    Returns
    -------
    OutputSource with kind="fallback".
    """
    detail = f"{reason} ({model_src.reason})" if model_src.reason else reason
    return OutputSource("fallback", None, detail)


def load_observed(cities=None, *, model_dir=None, processed_dir=None):
    """Observed cases, rain, reporting flags and thresholds, with fallbacks.

    Sources, best first:
    * cases  : cases_weekly.csv -> data/processed/cases_weekly.parquet (raw pipeline)
    * rain   : rain_weekly_imerg.csv -> data/processed/rain_weekly.parquet (CHIRPS)
    * flags  : reporting_flags.csv -> its baseline placeholder -> none
    * thresholds : thresholds_weekly.csv + thresholds_2023_for_app.csv
                   -> the app's own DOH computation
    Fallbacks to the app's pipeline are reported as kind="fallback".

    Parameters
    ----------
    cities : pandas.DataFrame | None
        adm3_pcode -> city_name lookup (cities.parquet). When None, names
        come from the parquet cases file, or stay as the pcode.
    model_dir, processed_dir : pathlib.Path | None
        Overrides for config.MODEL_OUTPUTS_DIR / config.PROCESSED_DIR.

    Returns
    -------
    dict
        cases       : adm3_pcode, city_name, week_start, mw_year, mw_week,
                      cases (Int64), reporting_flag (None when not flagged)
        rain_weekly : adm3_pcode, week_start, mw_year, mw_week, rain_mm
        flags       : reporting_flags rows
        thresholds  : thresholds_table output
        model_thresholds : thresholds_from_contract output (may be empty)
        status      : {part name: OutputSource} for cases, rain_imerg,
                      reporting_flags, thresholds_history, thresholds_app

    Raises
    ------
    FileNotFoundError
        If neither the contract cases file nor the parquet fallback exists
        (same for rain), with the command that fixes it.
    """
    processed = config.PROCESSED_DIR if processed_dir is None else processed_dir
    dirs = {"model_dir": model_dir, "processed_dir": processed}
    status = {}

    cases, src = load_part("cases", **dirs)
    if src.kind == "missing":
        path = processed / "cases_weekly.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run scripts/import_analysis_outputs.py "
                                    "or scripts/build_processed.py")
        cases = pd.read_parquet(path)
        src = _fallback_source("Reported cases from the app's raw-CSV pipeline", src)
    status["cases"] = src
    names = (dict(zip(cities.adm3_pcode, cities.city_name)) if cities is not None
             else dict(zip(cases.adm3_pcode, cases.get("city_name", cases.adm3_pcode))))
    cases = cases.assign(city_name=cases.adm3_pcode.map(names).fillna(cases.adm3_pcode),
                         cases=pd.to_numeric(cases.cases).astype("Int64"))

    rain, src = load_part("rain_imerg", **dirs)
    if src.kind == "missing":
        path = processed / "rain_weekly.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run scripts/import_analysis_outputs.py "
                                    "or scripts/build_processed.py")
        rain = pd.read_parquet(path)
        src = _fallback_source("Rainfall from CHIRPS via the app's raw-CSV pipeline, "
                               "not the model's IMERG", src)
    else:
        rain = rain.rename(columns={"rain_mm_7d": "rain_mm"})
        if "mw_year" not in rain or "mw_week" not in rain:
            mw = {w: morbidity_week(w) for w in rain.week_start.unique()}
            rain["mw_year"] = rain.week_start.map(lambda w: mw[w][0])
            rain["mw_week"] = rain.week_start.map(lambda w: mw[w][1])
    status["rain_imerg"] = src
    rain = rain[["adm3_pcode", "week_start", "mw_year", "mw_week", "rain_mm"]]

    flags, status["reporting_flags"] = load_part("reporting_flags", **dirs)
    flag_map = flags.set_index(["adm3_pcode", "week_start"]).flag if not flags.empty else None
    cases["reporting_flag"] = (
        [flag_map.get(k) for k in zip(cases.adm3_pcode, cases.week_start)]
        if flag_map is not None else None)

    history, status["thresholds_history"] = load_part("thresholds_history", **dirs)
    app_table, status["thresholds_app"] = load_part("thresholds_app", **dirs)
    model_thr = thresholds_from_contract(history, app_table)
    if model_thr.empty:
        reason = "Epidemic thresholds computed by the app (DOH mean + 2 SD)"
        status["thresholds_history"] = _fallback_source(reason, status["thresholds_history"])
        status["thresholds_app"] = _fallback_source(reason, status["thresholds_app"])
    thresholds = thresholds_table(model_thr, cases)

    return {"cases": cases, "rain_weekly": rain, "flags": flags, "thresholds": thresholds,
            "model_thresholds": model_thr, "status": status}


def banner_for(source):
    """Banner text for one part, or None when it is the modeling team's file.

    Parameters
    ----------
    source : OutputSource | dict
        A part's source (dicts as cached by app/data.py are accepted).

    Returns
    -------
    str | None
        config.BASELINE_BANNER for placeholders, a fallback / missing notice
        otherwise, None for kind="model".
    """
    kind = source["kind"] if isinstance(source, dict) else source.kind
    return {"model": None, "baseline": config.BASELINE_BANNER,
            "fallback": "App fallback, model file missing",
            "missing": "Not available yet"}.get(kind)
