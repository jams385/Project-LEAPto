"""Cached data access for the Streamlit app.

Everything heavy is loaded once per server process with st.cache_data. The
app reads only data/processed/ and data/model_outputs/ (never data/raw/).
"""

import json
import math

import pandas as pd
import streamlit as st

from app import config
from src.contract import (assign_levels, banner_for, level_cutoffs, load_auc, load_observed,
                          load_part)
from app.logic.reasons import city_reasons
from src.views import (case_signal_cities, city_snapshot, confidence_groups,
                       display_levels, level_descriptions)

# DATA LOADING +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _info(source):
    """OutputSource -> plain dict (keeps st.cache_data pickling simple).

    Parameters
    ----------
    source : src.load_outputs.OutputSource

    Returns
    -------
    dict
        kind, reason, warnings (list), path (str or None).
    """
    return {"kind": source.kind, "reason": source.reason,
            "warnings": list(source.warnings),
            "path": str(source.path) if source.path else None}


def missing_runtime_files(root=None):
    """The committed files the app needs that are not on disk.

    Parameters
    ----------
    root : pathlib.Path | None
        Project root to look in; config.ROOT if None.

    Returns
    -------
    list[tuple[str, str]]
        (path from the project root, how to get it back) for every file in
        config.RUNTIME_FILES that does not exist. Empty when all are there.
    """
    base = config.ROOT if root is None else root
    return [(path, fix) for path, fix in config.RUNTIME_FILES.items()
            if not (base / path).is_file()]


@st.cache_data(show_spinner=False)
def load_processed():
    """Load the tables behind the map, list, panel and charts.

    Reads
    -----
    data/processed/{cities,hazard_city}.parquet (static geography and flood
    hazard, from scripts/build_processed.py), and observed data through
    src.contract.load_observed: cases, IMERG rainfall, reporting flags and
    thresholds from data/model_outputs/, falling back to the app's raw-CSV
    pipeline (data/processed/*.parquet) and threshold logic.

    Returns
    -------
    dict
        cities, cases, rain_weekly, hazard, thresholds (DataFrames) and
        status ({part: dict from _info}). cases carries reporting_flag.
        Raises FileNotFoundError with the fix if a required file is missing.
    """
    out = {}
    for key, stem in {"cities": "cities", "hazard": "hazard_city"}.items():
        path = config.PROCESSED_DIR / f"{stem}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run scripts/build_processed.py")
        out[key] = pd.read_parquet(path)
    out["cities"]["island_group"] = out["cities"].region.map(config.REGION_TO_ISLAND_GROUP)
    obs = load_observed(out["cities"])
    out.update(cases=obs["cases"], rain_weekly=obs["rain_weekly"],
               thresholds=obs["thresholds"],
               status={k: _info(v) for k, v in obs["status"].items()})
    return out


@st.cache_data(show_spinner=False)
def load_geojson():
    """Load city polygons and a per-city map zoom that fits each polygon.

    Reads
    -----
    data/processed/cities.geojson.

    Returns
    -------
    tuple[dict, dict[str, float]]
        (GeoJSON FeatureCollection, {adm3_pcode: zoom level}).
    """
    gj = json.loads((config.PROCESSED_DIR / "cities.geojson").read_text(encoding="utf-8"))
    zooms = {}
    for feat in gj["features"]:
        coords = _flatten_coords(feat["geometry"]["coordinates"])
        lons, lats = [c[0] for c in coords], [c[1] for c in coords]
        span = max(max(lons) - min(lons), max(lats) - min(lats), 1e-3)
        zooms[feat["properties"]["adm3_pcode"]] = min(config.MAP_MAX_CITY_ZOOM,
                                                      math.log2(480 / span))
    return gj, zooms


def _flatten_coords(nested):
    """Flatten GeoJSON (Multi)Polygon coordinates into [lon, lat] pairs.

    Parameters
    ----------
    nested : list
        GeoJSON coordinates at any nesting depth.

    Returns
    -------
    list[list[float]]
        All positions; empty list for empty geometry.
    """
    if nested and isinstance(nested[0], (int, float)):
        return [nested]
    return [pos for part in nested for pos in _flatten_coords(part)]


def load_thresholds():
    """Epidemic thresholds for every city x morbidity week.

    Returns
    -------
    pandas.DataFrame
        src.contract.thresholds_table output: the modeling team's thresholds,
        or the app's own DOH computation when theirs are missing.
    """
    return load_processed()["thresholds"]


# CONTRACT V2 PARTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@st.cache_data(show_spinner=False)
def load_level_metrics():
    """Track record per horizon x level (model, else placeholder, else empty).

    Returns
    -------
    tuple[pandas.DataFrame, dict]
        level_metrics.csv rows and _info(source).
    """
    df, src = load_part("level_metrics")
    return df, _info(src)


@st.cache_data(show_spinner=False)
def load_alerts():
    """Alert forecasts with every row's level filled in.

    The modeling team's alerts carry their own levels (their stage 5d
    cut-offs, set again each test year). Levels the file leaves empty (the
    baseline placeholder) are assigned from fixed cut-offs: prob_cutoff in a
    level_metrics.csv when present, else the placeholders in app/config.py.

    Returns
    -------
    tuple[pandas.DataFrame, dict]
        src.contract.assign_levels output and _info(source) plus
        "cutoffs" and "cutoff_source": "delivered" when every level came in
        the file, else "model" / "config" (where the fixed cut-offs came
        from). Empty frame
        with kind="missing" if neither file is usable.
    """
    df, src = load_part("alerts")
    metrics, metrics_info = load_level_metrics()
    cutoffs, cutoff_source = level_cutoffs(metrics, metrics_info["kind"])
    if not df.empty and (df.alert_level.notna() | df.outbreak_prob.isna()).all():
        cutoff_source = "delivered"   # every week with a chance came with its level
    version = df.model_version.dropna().iloc[0] if "model_version" in df and \
        df.model_version.notna().any() else None
    info = _info(src) | {"cutoffs": cutoffs, "cutoff_source": cutoff_source,
                         "model_version": version}
    return assign_levels(df, cutoffs), info


def level_text(horizon):
    """Colour, meaning and track record per level for one horizon.

    Parameters
    ----------
    horizon : int
        1-3.

    Returns
    -------
    dict[str, dict]
        src.views.level_descriptions output, with level_metrics.csv
        (model or placeholder) overriding the config placeholders.
    """
    metrics, _ = load_level_metrics()
    return level_descriptions(metrics, horizon)


@st.cache_data(show_spinner=False)
def load_auc_table():
    """AUC by horizon and model; rows the model lacks come from the placeholder.

    Returns
    -------
    tuple[pandas.DataFrame, dict]
        auc rows with a `source` column ("model" / "baseline") and
        _info(source).
    """
    df, src = load_auc()
    return df, _info(src)


@st.cache_data(show_spinner=False)
def load_lag_curve():
    """Rain lag-response curve (P95 and P99 weeks); empty if not delivered.

    Returns
    -------
    tuple[pandas.DataFrame, dict]
        lag_response.csv rows and _info(source).
    """
    df, src = load_part("lag_response")
    return df, _info(src)


@st.cache_data(show_spinner=False)
def load_city_confidence():
    """Per-city test AUC and outbreak weeks (city_confidence.csv).

    Returns
    -------
    tuple[pandas.DataFrame, dict]
        Rows (adm3_pcode, outbreak_weeks, auc, city) and _info(source).
        Empty with kind="missing" if the file is absent; the app then uses
        config.CONFIDENCE_FALLBACK.
    """
    df, src = load_part("city_confidence")
    return df, _info(src)


def city_groups():
    """Each city's confidence group ("standard" / "lower" / "case_signal").

    Returns
    -------
    dict[str, str]
        src.views.confidence_groups on city_confidence.csv (or the config
        fallback when it is missing).
    """
    return confidence_groups(load_city_confidence()[0])


def case_signal():
    """Cities shown as "Case signal only".

    Returns
    -------
    frozenset[str]
    """
    return case_signal_cities(city_groups())


@st.cache_data(show_spinner=False)
def load_replay():
    """The stage 6 "as of then" forecasts behind the Replay tab.

    Returns
    -------
    tuple[pandas.DataFrame, dict]
        replay_weekly.csv rows and _info(source). Empty with kind="missing"
        when the file is absent (Replay then says what to run).
    """
    df, src = load_part("replay")
    return df, _info(src)


@st.cache_data(show_spinner=False)
def load_rain_late():
    """Weekly IMERG rain including the Late values the model used.

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, week_start, rain_mm_7d, rain_mm_7d_late (empty / without
        the Late column if the modeling team's rain file is missing).
    """
    df, _ = load_part("rain_imerg")
    return df


def city_total_cases(pcode):
    """A city's reported cases over the whole record (2008-2022).

    Parameters
    ----------
    pcode : str

    Returns
    -------
    float
        Sum of weekly cases, gaps ignored.
    """
    cases = load_processed()["cases"]
    return float(cases.loc[cases.adm3_pcode == pcode, "cases"].sum(skipna=True))


@st.cache_data(show_spinner=False)
def load_episodes():
    """How outbreaks started: the level of each outbreak's first week.

    Returns
    -------
    pandas.DataFrame
        episodes.csv rows (horizon, episode, alert_level, n, share); empty
        when the modeling team's file is missing (Data reliability shows
        "pending" for what needs it).
    """
    return load_part("episodes")[0]


@st.cache_data(show_spinner=False)
def load_rain_gain():
    """What rain adds to the forecast, per weeks ahead.

    Returns
    -------
    pandas.DataFrame
        rain_gain.csv rows (horizon, gain_per_week, lo, hi); empty if missing.
    """
    return load_part("rain_gain")[0]


@st.cache_data(show_spinner=False)
def load_reporting_flags():
    """City-weeks flagged as having no usable case report.

    Returns
    -------
    pandas.DataFrame
        reporting_flags.csv rows (adm3_pcode, week_start, flag); empty if none.
    """
    return load_part("reporting_flags")[0]


@st.cache_data(show_spinner=False)
def load_flood_rank():
    """Barangays ranked by Project NOAH 100-yr high flood-hazard share.

    Reads
    -----
    data/processed/brgy_flood_rank.csv (scripts/build_processed.py
    --only-flood-rank, committed).

    Returns
    -------
    pandas.DataFrame
        adm3_pcode, rank, adm4_pcode, brgy_name, high_hazard_pct,
        high_hazard_km2. Empty (same columns) if the file is missing, so the
        panel just hides the list.
    """
    path = config.PROCESSED_DIR / config.FLOOD_RANK_FILE
    cols = ["adm3_pcode", "rank", "adm4_pcode", "brgy_name", "high_hazard_pct",
            "high_hazard_km2"]
    if not path.exists():
        return pd.DataFrame(columns=cols)
    return pd.read_csv(path, dtype={"adm3_pcode": str, "adm4_pcode": str}, encoding="utf-8")


def data_status():
    """Where every contract part currently comes from.

    Returns
    -------
    list[dict]
        One dict per part in config.CONTRACT_FILES order: part, label, kind
        ("model" / "baseline" / "fallback" / "missing"), banner (None for
        model files), reason, warnings.
    """
    observed = load_processed()["status"]
    sources = dict(observed)
    sources["alerts"] = load_alerts()[1]
    sources["level_metrics"] = load_level_metrics()[1]
    sources["auc"] = load_auc_table()[1]
    sources["lag_response"] = load_lag_curve()[1]
    sources["city_confidence"] = load_city_confidence()[1]
    sources["replay"] = load_replay()[1]
    for part, loader in (("episodes", load_part), ("rain_gain", load_part)):
        sources[part] = _info(loader(part)[1])
    return [{"part": part, "label": config.CONTRACT_LABELS[part], **info,
             "banner": banner_for(info)}
            for part in config.CONTRACT_FILES for info in [sources[part]]]


def part_banner(part):
    """Banner text for one part ("Baseline, model pending" etc.), or None.

    Parameters
    ----------
    part : str
        Key of config.CONTRACT_FILES.

    Returns
    -------
    str | None
        None when the modeling team's file is in use.
    """
    return next(row["banner"] for row in data_status() if row["part"] == part)


# VIEWS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def origin_weeks():
    """List the origin weeks that have at least a Week 1 forecast.

    Origins that only carry Week 2/3 rows (the first two weeks of the record)
    are left out, so the picker never lands on an empty "next week".

    Returns
    -------
    list[pandas.Timestamp]
        Sorted Sundays; empty if no alerts are loaded.
    """
    alerts, _ = load_alerts()
    if alerts.empty:
        return []
    return sorted(pd.Timestamp(w) for w in alerts[alerts.horizon == 1].origin_week.unique())


@st.cache_data(show_spinner=False)
def snapshot(origin_week, horizon):
    """Cached src.views.city_snapshot for one origin week and horizon.

    Parameters
    ----------
    origin_week : pandas.Timestamp
        Forecast origin (Sunday).
    horizon : int
        1-3.

    Returns
    -------
    pandas.DataFrame
        src.views.SNAPSHOT_COLUMNS, ranked by chance of an outbreak week.
    """
    data = load_processed()
    alerts, _ = load_alerts()
    return city_snapshot(alerts, data["cities"], data["cases"], data["rain_weekly"],
                         data["hazard"], origin_week, horizon,
                         thresholds=data["thresholds"],
                         confidence=load_city_confidence()[0])


@st.cache_data(show_spinner=False)
def snapshot_reasons(origin_week, horizon):
    """ "What we're seeing" for every city at one origin week and horizon.

    Parameters
    ----------
    origin_week : pandas.Timestamp
    horizon : int
        1-3.

    Returns
    -------
    dict[str, list[app.logic.reasons.Reason]]
        adm3_pcode -> reasons (notes first; may be empty), built from the
        observed cases, IMERG rain, outbreak lines, flood ranking and the
        rain-risk curve. Never guesses missing inputs.
    """
    data = load_processed()
    snap = snapshot(origin_week, horizon)
    flood, lag = load_flood_rank(), load_lag_curve()[0]
    return {r.adm3_pcode: city_reasons(
                r.adm3_pcode, r.alert_level, origin_week, r.target_week,
                rain_weekly=data["rain_weekly"], cases=data["cases"],
                thresholds=data["thresholds"], flood_rank=flood, lag_response=lag,
                group=r.confidence, auc=r.city_auc)
            for r in snap.itertuples()}


def city_names():
    """Map adm3_pcode -> city name, ordered alphabetically by name.

    Returns
    -------
    dict[str, str]
    """
    cities = load_processed()["cities"].sort_values("city_name")
    return dict(zip(cities.adm3_pcode, cities.city_name))
