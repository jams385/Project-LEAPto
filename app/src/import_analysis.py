"""Convert the modeling team's R outputs into contract-v2 tables.

Pure functions used by scripts/import_analysis_outputs.py. Inputs are
DataFrames read from the analysis folder (which is never written to);
outputs follow docs/DATA_CONTRACT.md.

Their files key weeks by (city name or adm3_pcode, year, mw). Their MW1
starts on 1 January, so it can be 4-10 days long, but the numbering is the
DOH numbering the app uses, so every week is placed on the app's Sunday
calendar with src.weeks.week_starts(year, mw).
"""

import numpy as np
import pandas as pd

from app import config
from src.weeks import week_starts

# FILES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# Paths inside the analysis project (relative to its `analysis/` folder).
SOURCES = {
    "city_week": "data/processed/city_week.csv",
    "thresholds_app": "output/stage4/thresholds_2023_for_app.csv",
    "thresholds_weekly": "output/stage4/thresholds_weekly.csv",
    # Final model (stage 5e); the seasonal-only model is in the stage 5 file.
    "forecasts": "output/stage5/forecasts_washi.csv.gz",
    "forecasts_seasonal": "output/stage5/forecasts.csv.gz",
    # Risk levels (stage 5d): cut-offs per test year, and their weekly levels
    # (used only to check that the app reproduces them).
    "risk_cutoffs": "output/stage5/risk_levels_cutoffs.csv",
    "risk_weekly": "output/stage5/risk_levels_weekly.csv.gz",
    # AUC: final model (stage 5e), seasonal model (stage 5c), rain-only (stage 5).
    "auc_final": "output/stage5/washi_summary.csv",
    "auc_settings": "output/stage5/settings_summary.csv",
    "probability_scores": "output/stage5/probability_scores.csv",
    "lag_response": "output/stage3/lag_response.csv",
    "city_auc": "output/stage5/washi_by_city.csv",
    # Stage 6: "as of then" forecasts for the three case studies.
    "case_studies": "output/stage6/case_study_weekly.csv",
    # Data reliability: level of each outbreak's first week; what rain adds.
    "risk_episodes": "output/stage5/risk_levels_episodes.csv",
    "paired": "output/stage5/paired_comparisons.csv",
}
# Columns each converter needs; checked before converting.
SOURCE_COLUMNS = {
    "city_week": ["city", "adm3_pcode", "year", "mw", "days", "cases", "include",
                  "in_pidsr_period", "flag_zero_run", "flag_low_year",
                  config.ANALYSIS_RAIN_COLUMN, config.ANALYSIS_RAIN_LATE_COLUMN],
    "thresholds_app": ["city", "year", "mw", "thr_app"],
    "thresholds_weekly": ["city", "year", "mw", "thr_exc5", "thr_exc3"],
    "forecasts": ["origin", "h", "variant", "set", "city", "year", "mw", "days", "include",
                  "cases", "mu", "theta", "thr_exc5", "above_exc5"],
    "forecasts_seasonal": ["h", "variant", "set", "city", "year", "mw", "days", "mu", "theta",
                           "thr_exc5"],
    "risk_cutoffs": ["origin", "h", "city", "watch", "warn", "version"],
    "risk_weekly": ["origin", "h", "city", "year", "mw", "version", "level"],
    "auc_final": ["variant", "h", "auc_within_city", "auc_all", "cities"],
    "auc_settings": ["variant", "h", "auc_within_city", "auc_all"],
    "probability_scores": ["h", "grp", "threshold", "variant", "auc"],
    "lag_response": ["lag", "rr", "lo", "hi", "level"],
    "city_auc": ["variant", "city", "outbreak_weeks", "auc"],
    "case_studies": ["event", "view", "model", "h", "city", "year", "mw", "cases", "threshold",
                     "above", "p", "level"],
    "risk_episodes": ["version", "h", "episode", "level", "N", "share"],
    "paired": ["comparison", "better", "than", "h", "gain_per_week", "lo", "hi"],
}
# Low-reporting years from 2020 on are kept by the modeling team (COVID
# indicator), so only earlier ones count as excluded "low_reporting_year".
LOW_YEAR_EXCLUDED_UNTIL = 2019


class AnalysisFormatError(ValueError):
    """An analysis file lacks the columns or values the converter expects."""


def check_columns(df, source):
    """Raise AnalysisFormatError if `df` lacks SOURCE_COLUMNS[source].

    Parameters
    ----------
    df : pandas.DataFrame
        As read from the analysis file.
    source : str
        Key of SOURCES.

    Returns
    -------
    None
    """
    missing = [c for c in SOURCE_COLUMNS[source] if c not in df.columns]
    if missing:
        raise AnalysisFormatError(f"{SOURCES[source]} is missing columns {missing}")


# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def as_bool(series):
    """Read R/CSV logicals (TRUE/FALSE, True/False, 1/0) as plain bools.

    Parameters
    ----------
    series : pandas.Series

    Returns
    -------
    pandas.Series of bool; anything not true-like (including NA) is False.
    """
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "1.0"})


def city_pcodes(names):
    """Map the modeling team's city names to adm3_pcode.

    Parameters
    ----------
    names : pandas.Series of str
        e.g. "Cagayan de Oro".

    Returns
    -------
    pandas.Series of str, same index. Raises AnalysisFormatError naming any
    city missing from config.ANALYSIS_CITY_PCODES.
    """
    codes = names.map(config.ANALYSIS_CITY_PCODES)
    if codes.isna().any():
        raise AnalysisFormatError(f"unknown city names {sorted(set(names[codes.isna()]))}; "
                                  "add them to config.ANALYSIS_CITY_PCODES")
    return codes


def nb_exceed_prob(k, mu, theta):
    """P(Y > k) for a negative binomial with mean mu and size theta (NB2).

    Same as R's 1 - pnbinom(k, size = theta, mu = mu); computed by summing
    the probability mass for 0..k with the recurrence
    p(j) = p(j-1) * (j - 1 + theta) / j * mu / (mu + theta), so no SciPy.

    Parameters
    ----------
    k : array-like of float
        Integer cut (floor already applied); NaN gives NaN.
    mu, theta : array-like of float
        Mean (> 0) and size (> 0), same length as k.

    Returns
    -------
    numpy.ndarray of float in [0, 1]; NaN where any input is NaN. k < 0
    gives 1.
    """
    k = np.asarray(k, dtype=float)
    mu = np.asarray(mu, dtype=float)
    theta = np.asarray(theta, dtype=float)
    bad = np.isnan(k) | np.isnan(mu) | np.isnan(theta)
    kk = np.where(bad, -1, k)
    q = mu / (mu + theta)
    pmf = (theta / (mu + theta)) ** theta
    cdf = np.where(kk >= 0, pmf, 0.0)
    for j in range(1, int(max(kk.max(initial=0), 0)) + 1):
        pmf = pmf * (j - 1 + theta) / j * q
        cdf = cdf + np.where(kk >= j, pmf, 0.0)
    out = np.clip(1.0 - cdf, 0.0, 1.0)
    out[bad] = np.nan
    return out


# CITY-WEEK TABLE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def convert_city_week(city_week):
    """Cases, IMERG rainfall and reporting flags from their city_week.csv.

    Parameters
    ----------
    city_week : pandas.DataFrame
        data/processed/city_week.csv: one row per city x (year, mw), 2003-2022.

    Returns
    -------
    dict[str, pandas.DataFrame]
        cases : adm3_pcode, week_start, mw_year, mw_week, cases, days (PIDSR
                period rows only, 2008-2022)
        rain_imerg : adm3_pcode, week_start, mw_year, mw_week, rain_mm_7d
                (config.ANALYSIS_RAIN_COLUMN, IMERG Final, mm per 7 days),
                rain_mm_7d_late (IMERG Late); rows with no rain dropped
        reporting_flags : adm3_pcode, week_start, flag for every excluded
                week (include == FALSE): "low_reporting_year" if the city-year
                is a flagged low-reporting year up to 2019, else "non_reporting"
    Raises AnalysisFormatError on missing columns or unknown cities.
    """
    check_columns(city_week, "city_week")
    cw = city_week.copy()
    cw["adm3_pcode"] = cw.adm3_pcode.astype(str)
    if (city_pcodes(cw.city) != cw.adm3_pcode).any():
        raise AnalysisFormatError("city_week.csv adm3_pcode disagrees with "
                                  "config.ANALYSIS_CITY_PCODES for some cities")
    cw["week_start"] = week_starts(cw.year, cw.mw).to_numpy()
    cw = cw.rename(columns={"year": "mw_year", "mw": "mw_week"})
    keys = ["adm3_pcode", "week_start", "mw_year", "mw_week"]

    pidsr = cw[as_bool(cw.in_pidsr_period)]
    cases = pidsr[keys + ["cases", "days"]].copy()
    cases["cases"] = pd.to_numeric(cases.cases).astype("Int64")

    rain = cw[keys].assign(rain_mm_7d=cw[config.ANALYSIS_RAIN_COLUMN],
                           rain_mm_7d_late=cw[config.ANALYSIS_RAIN_LATE_COLUMN])
    rain = rain.dropna(subset=["rain_mm_7d"])

    excluded = pidsr[~as_bool(pidsr.include)]
    low_year = as_bool(excluded.flag_low_year) & (excluded.mw_year <= LOW_YEAR_EXCLUDED_UNTIL)
    flags = excluded[["adm3_pcode", "week_start"]].assign(
        flag=np.where(low_year, "low_reporting_year", "non_reporting"))

    tidy = lambda df: df.sort_values(["adm3_pcode", "week_start"]).reset_index(drop=True)
    return {"cases": tidy(cases), "rain_imerg": tidy(rain), "reporting_flags": tidy(flags)}


# THRESHOLDS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def convert_thresholds_weekly(thresholds_weekly):
    """Historical epidemic thresholds from stage4/thresholds_weekly.csv.

    The threshold is the outbreak-excluded 5-year one (the version the
    modeling team recommends and validated), falling back to the
    outbreak-excluded 3-year one where no 5-year history exists (2011-2013).

    Parameters
    ----------
    thresholds_weekly : pandas.DataFrame
        city, year, mw, thr_exc5, thr_exc3, ...

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, week_start, mw_year, mw_week, threshold (cases per 7
        days), source. Weeks with neither threshold (2008-2010) are dropped.
    """
    check_columns(thresholds_weekly, "thresholds_weekly")
    tw = thresholds_weekly
    threshold = tw.thr_exc5.fillna(tw.thr_exc3)
    out = pd.DataFrame({
        "adm3_pcode": city_pcodes(tw.city).to_numpy(),
        "week_start": week_starts(tw.year, tw.mw).to_numpy(),
        "mw_year": tw.year.to_numpy(),
        "mw_week": tw.mw.to_numpy(),
        "threshold": threshold.to_numpy(),
        "source": np.where(tw.thr_exc5.notna(), "outbreak-excluded 5-year",
                           "outbreak-excluded 3-year (fallback)"),
    })
    out = out[out.threshold.notna()]
    return out.sort_values(["adm3_pcode", "week_start"]).reset_index(drop=True)


# ALERTS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def assign_their_levels(prob, origin, h, city, cutoffs, *,
                        version=config.ANALYSIS_LEVEL_VERSION):
    """Normal / Watch / Warning from the modeling team's cut-offs (stage 5d).

    Parameters
    ----------
    prob : array-like of float
        outbreak_prob.
    origin, h, city : array-like
        Their origin year (last training year), horizon and city name.
    cutoffs : pandas.DataFrame
        stage5/risk_levels_cutoffs.csv (origin, h, city, watch, warn, version).
    version : str
        Which of their versions to use (config.ANALYSIS_LEVEL_VERSION).

    Returns
    -------
    numpy.ndarray of object
        "Warning" when prob >= warn, "Watch" when >= watch, else "Normal";
        None where prob is missing or no cut-off exists (e.g. horizon 3+).
    """
    check_columns(cutoffs, "risk_cutoffs")
    cut = cutoffs[cutoffs.version == version]
    keys = pd.DataFrame({"origin": np.asarray(origin), "h": np.asarray(h),
                         "city": np.asarray(city)})
    m = keys.merge(cut[["origin", "h", "city", "watch", "warn"]], on=["origin", "h", "city"],
                   how="left")
    prob = np.asarray(prob, dtype=float)
    level = np.where(prob >= m.warn, "Warning", np.where(prob >= m.watch, "Watch", "Normal"))
    return np.where(np.isnan(prob) | m.watch.isna().to_numpy(), None, level).astype(object)


def convert_forecasts(forecasts, flags, *, seasonal=None, cutoffs=None,
                      variant=config.ANALYSIS_ALERT_VARIANT,
                      usual_variant=config.ANALYSIS_USUAL_VARIANT,
                      horizons=config.ALERT_HORIZONS):
    """alerts.csv rows from the modeling team's rolling-origin forecasts.

    Uses the out-of-sample rows (set == "test", forecast years 2014-2022) of
    `variant`. For each row:
    * outbreak_prob = P(cases > threshold scaled to the week's length)
      = 1 - pnbinom(floor(thr_exc5 * days / 7), theta, mu), exactly as in
      their R/05_validation.R and R/05d_risk_levels.R;
    * origin_week = target_week - (h - 1) weeks: forecast h uses rain up to
      the week before the origin and cases with a one-week reporting delay;
    * rr_vs_usual = outbreak_prob / the same week's outbreak_prob from
      `usual_variant` (seasonal only). PLACEHOLDER definition until the
      modeling team defines it; NaN where the seasonal chance is 0;
    * alert_level = "No report" for weeks flagged in reporting_flags.csv,
      else their stage 5d level (assign_their_levels) when `cutoffs` is
      given, else empty (the app then assigns it from config.LEVEL_CUTOFFS).

    Parameters
    ----------
    forecasts : pandas.DataFrame
        stage5/forecasts_washi.csv.gz (the final model).
    flags : pandas.DataFrame
        convert_city_week(...)["reporting_flags"].
    seasonal : pandas.DataFrame | None
        A file holding `usual_variant` test rows (stage5/forecasts.csv.gz);
        None looks for them in `forecasts`.
    cutoffs : pandas.DataFrame | None
        stage5/risk_levels_cutoffs.csv.
    variant, usual_variant : str
        Their model variant names.
    horizons : tuple[int, ...]
        Horizons to keep.

    Returns
    -------
    pandas.DataFrame
        contract alerts columns + days, model_version. Raises
        AnalysisFormatError if a variant has no test rows.
    """
    check_columns(forecasts, "forecasts")
    fc = forecasts[(forecasts.set == "test") & forecasts.h.isin(horizons)
                   & (forecasts.variant == variant)].copy()
    if fc.empty:
        raise AnalysisFormatError(f"no test rows for variant {variant!r} in {SOURCES['forecasts']}")
    src = forecasts if seasonal is None else seasonal
    check_columns(src, "forecasts_seasonal")
    us = src[(src.set == "test") & src.h.isin(horizons) & (src.variant == usual_variant)].copy()
    if us.empty:
        raise AnalysisFormatError(f"no test rows for variant {usual_variant!r} in "
                                  f"{SOURCES['forecasts_seasonal']}")
    for part in (fc, us):
        part["adm3_pcode"] = city_pcodes(part.city).to_numpy()
        part["target_week"] = week_starts(part.year, part.mw).to_numpy()
        part["outbreak_prob"] = nb_exceed_prob(np.floor(part.thr_exc5 * part.days / 7), part.mu,
                                               part.theta)

    keys = ["adm3_pcode", "target_week", "h"]
    usual = us[keys + ["outbreak_prob"]].rename(columns={"outbreak_prob": "usual_prob"})
    main = fc.merge(usual, on=keys, how="left")

    included = as_bool(main.include) & main.thr_exc5.notna()
    flag_map = flags.set_index(["adm3_pcode", "week_start"]).flag
    reporting = [flag_map.get(k) for k in zip(main.adm3_pcode, main.target_week)]
    levels = (assign_their_levels(main.outbreak_prob, main.origin, main.h, main.city, cutoffs)
              if cutoffs is not None else np.full(len(main), None, dtype=object))
    levels = np.where([f is not None for f in reporting], config.NO_REPORT_LEVEL, levels)
    out = pd.DataFrame({
        "adm3_pcode": main.adm3_pcode,
        "origin_week": main.target_week - pd.to_timedelta((main.h - 1) * 7, unit="D"),
        "horizon": main.h.astype(int),
        "target_week": main.target_week,
        "outbreak_prob": main.outbreak_prob,
        "rr_vs_usual": main.outbreak_prob / main.usual_prob.where(main.usual_prob > 0),
        "alert_level": levels,
        "observed_cases": pd.to_numeric(main.cases).astype("Int64"),
        "observed_outbreak": as_bool(main.above_exc5).astype("boolean").where(included),
        "threshold": main.thr_exc5,
        "reporting_flag": reporting,
        "days": main.days.astype(int),
        "model_version": f"dlnm-nb-{variant} (final model, levels {config.ANALYSIS_LEVEL_VERSION}, "
                         "imported)",
    })
    return out.sort_values(["adm3_pcode", "origin_week", "horizon"]).reset_index(drop=True)


def check_levels(alerts, risk_weekly, *, version=config.ANALYSIS_LEVEL_VERSION):
    """How many of the modeling team's weekly levels the alerts reproduce.

    Parameters
    ----------
    alerts : pandas.DataFrame
        convert_forecasts output (adm3_pcode, target_week, horizon, alert_level).
    risk_weekly : pandas.DataFrame
        stage5/risk_levels_weekly.csv.gz (city, year, mw, h, version, level).
    version : str

    Returns
    -------
    tuple[int, int]
        (weeks with the same level, weeks compared). Their file holds only
        weeks that count in the test (reported, with a threshold).
    """
    check_columns(risk_weekly, "risk_weekly")
    theirs = risk_weekly[risk_weekly.version == version]
    theirs = pd.DataFrame({"adm3_pcode": city_pcodes(theirs.city).to_numpy(),
                           "target_week": week_starts(theirs.year, theirs.mw).to_numpy(),
                           "horizon": theirs.h.astype(int).to_numpy(),
                           "their_level": theirs.level.to_numpy()})
    both = theirs.merge(alerts[["adm3_pcode", "target_week", "horizon", "alert_level"]],
                        on=["adm3_pcode", "target_week", "horizon"], how="left")
    return int((both.their_level == both.alert_level).sum()), len(both)


# VALIDATION SUMMARIES +++++++++++++++++++++++++++++++++++++++++++++++++++++++

def convert_auc(final_summary, settings_summary, probability_scores, *, models=None,
                horizons=config.ALERT_HORIZONS):
    """auc.csv rows: the final model, the seasonal-only model and rain only.

    * final model: stage5/washi_summary.csv ("All cities" rows of the final
      variant), both scopes;
    * seasonal only: stage5/settings_summary.csv, both scopes (same test);
    * rain only: stage5/probability_scores.csv ("All cities", outbreak-
      excluded threshold), all weeks only.
    "last week's cases only" was never fitted by the modeling team, so it is
    not produced here (the baseline script adds a placeholder for it).

    Parameters
    ----------
    final_summary, settings_summary, probability_scores : pandas.DataFrame
    models : dict[str, str] | None
        Their variant -> contract model name; config.ANALYSIS_AUC_MODELS if None.
    horizons : tuple[int, ...]

    Returns
    -------
    pandas.DataFrame
        horizon, model, scope ("all weeks" / "within city"), auc. Empty if
        nothing matches.
    """
    check_columns(final_summary, "auc_final")
    check_columns(settings_summary, "auc_settings")
    check_columns(probability_scores, "probability_scores")
    models = config.ANALYSIS_AUC_MODELS if models is None else models
    parts = []
    fin = final_summary[(final_summary.cities == "All cities")
                        & (final_summary.variant == config.ANALYSIS_ALERT_VARIANT)]
    sea = settings_summary[settings_summary.variant == config.ANALYSIS_USUAL_VARIANT]
    sea = sea.drop_duplicates(["variant", "h"])          # repeated once per comparison
    for table in (fin, sea):
        table = table[table.h.isin(horizons) & table.variant.isin(models)]
        for column, scope in (("auc_all", "all weeks"), ("auc_within_city", "within city")):
            parts.append(pd.DataFrame({"horizon": table.h.astype(int).to_numpy(),
                                       "model": table.variant.map(models).to_numpy(),
                                       "scope": scope, "auc": table[column].to_numpy()}))
    ps = probability_scores
    rain = ps[(ps.grp == "All cities") & (ps.threshold == "Outbreak-excluded")
              & (ps.variant == "pooled") & ps.h.isin(horizons) & ps.variant.isin(models)]
    parts.append(pd.DataFrame({"horizon": rain.h.astype(int).to_numpy(),
                               "model": rain.variant.map(models).to_numpy(),
                               "scope": "all weeks", "auc": rain.auc.to_numpy()}))
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["model", "scope", "horizon"]).reset_index(drop=True)


def convert_lag_response(lag_response):
    """lag_response.csv (wide) from stage3/lag_response.csv (long).

    Parameters
    ----------
    lag_response : pandas.DataFrame
        lag, rr, lo, hi, level ("P95" = 164 mm/week, "P99" = 265 mm/week,
        each relative to a typical week).

    Returns
    -------
    pandas.DataFrame
        lag_weeks, rr_p95, rr_p95_lower, rr_p95_upper, rr_p99,
        rr_p99_lower, rr_p99_upper. Raises AnalysisFormatError if either level
        is absent.
    """
    check_columns(lag_response, "lag_response")
    lr = lag_response
    parts = []
    for level in ("P95", "P99"):
        sub = lr[lr.level == level]
        if sub.empty:
            raise AnalysisFormatError(f"{SOURCES['lag_response']} has no {level} rows")
        tag = level.lower()
        parts.append(sub.set_index("lag")[["rr", "lo", "hi"]].rename(columns={
            "rr": f"rr_{tag}", "lo": f"rr_{tag}_lower", "hi": f"rr_{tag}_upper"}))
    out = pd.concat(parts, axis=1).reset_index().rename(columns={"lag": "lag_weeks"})
    out["lag_weeks"] = out.lag_weeks.astype(int)
    return out.sort_values("lag_weeks").reset_index(drop=True)


# CITY CONFIDENCE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def convert_city_confidence(city_auc, *, variant=config.ANALYSIS_ALERT_VARIANT):
    """city_confidence.csv rows from stage5/washi_by_city.csv (the final model).

    Parameters
    ----------
    city_auc : pandas.DataFrame
        variant, city, outbreak_weeks (outbreak weeks in the 2014-2022 test),
        auc (that city's test AUC), plus other columns.
    variant : str
        The variant exported as alerts.csv, whose rows are kept.

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, city, outbreak_weeks, auc, sorted by city. Raises
        AnalysisFormatError if a column is missing, the variant is absent or
        a city name is unknown.
    """
    check_columns(city_auc, "city_auc")
    rows = city_auc[city_auc.variant == variant]
    if rows.empty:
        raise AnalysisFormatError(f"no rows for variant {variant!r} in {SOURCES['city_auc']}")
    out = pd.DataFrame({"adm3_pcode": city_pcodes(rows.city).to_numpy(),
                        "city": rows.city.to_numpy(),
                        "outbreak_weeks": rows.outbreak_weeks.astype(int).to_numpy(),
                        "auc": rows.auc.astype(float).to_numpy()})
    return out.sort_values("city").reset_index(drop=True)


# REPLAY ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def convert_replay(case_weekly, *, variant=config.ANALYSIS_ALERT_VARIANT):
    """replay_weekly.csv rows from stage6/case_study_weekly.csv.

    Keeps only the "strict" view (trained on earlier years only, retrained
    each January, exactly as in the rolling test) of the final model. The
    "today's model" view is dropped on purpose: it never saw the outbreak but
    was trained on later years, so it is not a replay.

    Parameters
    ----------
    case_weekly : pandas.DataFrame
        event, view, model, h, city, year, mw, cases, threshold, above, p, level.
    variant : str
        Their model variant (config.ANALYSIS_ALERT_VARIANT).

    Returns
    -------
    pandas.DataFrame
        event, adm3_pcode, origin_week, horizon, target_week, outbreak_prob,
        alert_level, observed_cases, threshold, observed_outbreak,
        model_version. Weeks without a chance or outbreak line keep empty
        values. Raises AnalysisFormatError if no strict rows exist or a city
        is unknown.
    """
    check_columns(case_weekly, "case_studies")
    rows = case_weekly[(case_weekly.view == "strict") & (case_weekly.model == variant)].copy()
    if rows.empty:
        raise AnalysisFormatError(f"no strict rows for {variant!r} in {SOURCES['case_studies']}")
    target = week_starts(rows.year, rows.mw).to_numpy()
    out = pd.DataFrame({
        "event": rows.event.to_numpy(),
        "adm3_pcode": city_pcodes(rows.city).to_numpy(),
        "origin_week": target - pd.to_timedelta((rows.h.to_numpy() - 1) * 7, unit="D"),
        "horizon": rows.h.astype(int).to_numpy(),
        "target_week": target,
        "outbreak_prob": rows.p.to_numpy(),
        "alert_level": rows.level.where(rows.p.notna(), None).to_numpy(),
        "observed_cases": pd.to_numeric(rows.cases).astype("Int64").to_numpy(),
        "threshold": rows.threshold.to_numpy(),
        "observed_outbreak": as_bool(rows.above).astype("boolean").where(rows.threshold.notna())
                             .to_numpy(),
        "model_version": f"dlnm-nb-{variant} (stage 6, as of then, imported)",
    })
    return out.sort_values(["event", "target_week", "horizon"]).reset_index(drop=True)


# RELIABILITY ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def convert_episodes(risk_episodes, *, version=config.ANALYSIS_LEVEL_VERSION,
                     horizons=config.ALERT_HORIZONS):
    """episodes.csv rows from stage5/risk_levels_episodes.csv.

    Parameters
    ----------
    risk_episodes : pandas.DataFrame
        version, h, episode ("2+ weeks" / "single week"), level, N, share:
        for each outbreak episode, the level its first week was forecast at.
    version : str
        Their risk-level version (config.ANALYSIS_LEVEL_VERSION).
    horizons : tuple[int, ...]

    Returns
    -------
    pandas.DataFrame
        horizon, episode, alert_level, n, share. Raises AnalysisFormatError
        when their file has nothing for `version`.
    """
    check_columns(risk_episodes, "risk_episodes")
    rows = risk_episodes[(risk_episodes.version == version) & risk_episodes.h.isin(horizons)]
    if rows.empty:
        raise AnalysisFormatError(f"no rows for version {version!r} in "
                                  f"{SOURCES['risk_episodes']}")
    out = pd.DataFrame({"horizon": rows.h.astype(int).to_numpy(),
                        "episode": rows.episode.to_numpy(),
                        "alert_level": rows.level.to_numpy(),
                        "n": rows.N.astype(int).to_numpy(),
                        "share": rows.share.astype(float).to_numpy()})
    return out.sort_values(["horizon", "episode", "alert_level"]).reset_index(drop=True)


def convert_rain_gain(paired):
    """rain_gain.csv rows from stage5/paired_comparisons.csv.

    Keeps their "Rain vs no rain" comparison (the pooled rain model against the
    seasonal-only model): the gain in log score per week, with its 95% interval,
    at 1-4 weeks ahead.

    Parameters
    ----------
    paired : pandas.DataFrame
        comparison, better, than, h, gain_per_week, lo, hi.

    Returns
    -------
    pandas.DataFrame
        horizon, gain_per_week, lo, hi. Raises AnalysisFormatError if the
        comparison is absent.
    """
    check_columns(paired, "paired")
    rows = paired[(paired.comparison == "Rain vs no rain") & (paired.better == "pooled")
                  & (paired.than == "seasonal")]
    if rows.empty:
        raise AnalysisFormatError(f"no 'Rain vs no rain' rows in {SOURCES['paired']}")
    out = pd.DataFrame({"horizon": rows.h.astype(int).to_numpy(),
                        "gain_per_week": rows.gain_per_week.astype(float).to_numpy(),
                        "lo": rows.lo.astype(float).to_numpy(),
                        "hi": rows.hi.astype(float).to_numpy()})
    return out.sort_values("horizon").reset_index(drop=True)
