"""Tests for src/contract.py: v2 validators, loaders, fallbacks and levels."""

import numpy as np
import pandas as pd
import pytest

from app import config
from src.contract import (PARTS, THRESHOLD_TABLE_COLUMNS, assign_levels, banner_for,
                          level_cutoffs, load_auc, load_model_file, load_observed, load_part,
                          thresholds_from_contract, thresholds_table)
from src.load_outputs import ContractError, OutputSource, baseline_filename

P1, P2 = "PH015518000", "PH137503000"


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.fixture
def dirs(tmp_path):
    model, processed = tmp_path / "model_outputs", tmp_path / "processed"
    model.mkdir()
    processed.mkdir()
    return {"model_dir": model, "processed_dir": processed}


def write(df, folder, part, baseline=False):
    name = PARTS[part].filename
    df.to_csv(folder / (baseline_filename(name) if baseline else name), index=False)


def alerts_rows(**overrides):
    df = pd.DataFrame({
        "adm3_pcode": [P1, P1, P1], "origin_week": ["2015-03-01", "2015-03-01", "2015-03-08"],
        "horizon": [1, 2, 1], "target_week": ["2015-03-01", "2015-03-08", "2015-03-08"],
        "outbreak_prob": [0.05, 0.15, 0.4], "rr_vs_usual": [1.0, 2.0, np.nan],
        "alert_level": [None, None, None], "observed_cases": [0, 3, None],
        "observed_outbreak": ["FALSE", "TRUE", None], "threshold": [2.0, 2.0, 2.0],
        "reporting_flag": [None, None, None],
    })
    for col, value in overrides.items():
        df[col] = value
    return df


def cases_rows():
    weeks = pd.date_range("2013-12-29", periods=60, freq="7D")
    rows = [{"adm3_pcode": p, "week_start": w, "cases": i % 3}
            for p in (P1, P2) for i, w in enumerate(weeks)]
    df = pd.DataFrame(rows)
    df["mw_year"] = np.where(df.week_start < "2014-12-28", 2014, 2015)
    df["mw_week"] = df.groupby(["adm3_pcode", "mw_year"]).cumcount() + 1
    return df


# VALIDATORS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_valid_alerts_load_with_empty_level_warning(dirs):
    write(alerts_rows(), dirs["model_dir"], "alerts")
    df, src = load_part("alerts", **dirs)
    assert src.kind == "model" and len(df) == 3
    assert str(df.observed_outbreak.dtype) == "boolean"
    assert df.observed_outbreak.tolist()[:2] == [False, True]
    assert any("alert_level is empty" in w for w in src.warnings)


@pytest.mark.parametrize("override, message", [
    ({"target_week": ["2015-03-01"] * 3}, "target_week must equal"),
    ({"outbreak_prob": [0.1, 1.2, 0.3]}, "outbreak_prob"),
    ({"alert_level": ["Very High", None, None]}, "alert_level must be one of"),
    ({"reporting_flag": ["missing", None, None]}, "reporting_flag"),
    ({"horizon": [1, 2, 3], "target_week": ["2015-03-01", "2015-03-08", "2015-03-22"]},
     "horizon must be one of"),
    ({"origin_week": ["2015-03-02"] * 3}, "Sunday"),
    ({"observed_outbreak": ["yes", None, None]}, "true/false"),
])
def test_bad_alerts_fall_back_with_reason(dirs, override, message):
    write(alerts_rows(**override), dirs["model_dir"], "alerts")
    df, src = load_part("alerts", **dirs)
    assert src.kind == "missing" and df.empty and message in src.reason


def test_duplicate_alert_rows_rejected(dirs):
    write(pd.concat([alerts_rows(), alerts_rows()]), dirs["model_dir"], "alerts")
    assert "duplicate" in load_part("alerts", **dirs)[1].reason


def test_lag_response_rules(dirs):
    good = pd.DataFrame({"lag_weeks": range(11), "rr_p95": 1.2, "rr_p99": 2.0,
                         "rr_p95_lower": 1.0, "rr_p95_upper": 1.5})
    write(good, dirs["model_dir"], "lag_response")
    df, src = load_part("lag_response", **dirs)
    assert src.kind == "model" and "rr_p95_lower" in df and "rr_p99_lower" not in df
    write(good.assign(rr_p99=0.0), dirs["model_dir"], "lag_response")
    assert "rr_p99 must be positive" in load_part("lag_response", **dirs)[1].reason


def test_reporting_flags_may_be_empty(dirs):
    write(pd.DataFrame(columns=["adm3_pcode", "week_start", "flag"]), dirs["model_dir"],
          "reporting_flags")
    df, src = load_part("reporting_flags", **dirs)
    assert src.kind == "model" and df.empty


def test_thresholds_app_unknown_city(dirs):
    write(pd.DataFrame({"city": ["Atlantis"], "year": [2023], "mw": [1], "thr_app": [1.0]}),
          dirs["model_dir"], "thresholds_app")
    assert "Atlantis" in load_part("thresholds_app", **dirs)[1].reason


def test_level_metrics_rates_checked(dirs):
    row = {"horizon": 1, "alert_level": "Watch", "n_weeks": 10, "n_outbreaks": 2,
           "hit_rate": 0.2, "base_rate": 0.07, "lift": 2.9, "capture_rate": 1.4,
           "median_lead_weeks": 1}
    write(pd.DataFrame([row]), dirs["model_dir"], "level_metrics")
    assert "capture_rate" in load_part("level_metrics", **dirs)[1].reason


# FALLBACK ORDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_model_then_baseline_then_missing(dirs):
    write(alerts_rows(), dirs["processed_dir"], "alerts", baseline=True)
    df, src = load_part("alerts", **dirs)
    assert src.kind == "baseline" and banner_for(src) == config.BASELINE_BANNER
    write(alerts_rows(), dirs["model_dir"], "alerts")
    assert load_part("alerts", **dirs)[1].kind == "model"
    df, src = load_part("auc", **dirs)
    assert src.kind == "missing" and df.empty and banner_for(src) == "Not available yet"


def test_load_model_file_ignores_baseline(dirs):
    write(alerts_rows(), dirs["processed_dir"], "alerts", baseline=True)
    df, reason = load_model_file("alerts", model_dir=dirs["model_dir"])
    assert df is None and "not found" in reason


def test_auc_borrows_missing_models_from_baseline(dirs):
    write(pd.DataFrame({"horizon": [1, 2], "model": "final_model", "auc": 0.8}),
          dirs["model_dir"], "auc")
    write(pd.DataFrame({"horizon": [1, 2], "model": "last_week_only", "auc": 0.7}),
          dirs["processed_dir"], "auc", baseline=True)
    df, src = load_auc(**dirs)
    assert src.kind == "model" and len(df) == 4
    assert df.set_index("model").source.to_dict() == {"final_model": "model",
                                                      "last_week_only": "baseline"}
    assert any("last_week_only" in w for w in src.warnings)


def test_banner_only_for_non_model():
    assert banner_for(OutputSource("model", None, "")) is None
    assert banner_for({"kind": "fallback"}).startswith("App fallback")


# LEVELS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_assign_levels_rules():
    df = alerts_rows(outbreak_prob=[0.05, 0.15, np.nan],
                     reporting_flag=[None, None, None])
    df.loc[0, "reporting_flag"] = "non_reporting"
    df.loc[1, "outbreak_prob"] = 0.25
    out = assign_levels(df, {"Watch": 0.1, "Warning": 0.2})
    assert out.alert_level.tolist() == [config.NO_REPORT_LEVEL, "Warning",
                                        config.NO_FORECAST_LEVEL]
    out = assign_levels(alerts_rows(outbreak_prob=[0.0, 0.1, 0.19]),
                        {"Watch": 0.1, "Warning": 0.2})
    assert out.alert_level.tolist() == ["Normal", "Watch", "Watch"]
    assert set(out.level_source) == {"cut-offs"}


def test_delivered_levels_are_kept():
    out = assign_levels(alerts_rows(alert_level=["Warning", None, None]))
    assert out.alert_level.iloc[0] == "Warning" and out.level_source.iloc[0] == "model"


def test_cutoffs_from_model_level_metrics_only():
    metrics = pd.DataFrame({"alert_level": ["Normal", "Watch", "Warning"],
                            "prob_cutoff": [0.0, 0.12, 0.3]})
    assert level_cutoffs(metrics, "model") == ({"Watch": 0.12, "Warning": 0.3}, "model")
    assert level_cutoffs(metrics, "baseline") == (config.LEVEL_CUTOFFS, "config")
    assert level_cutoffs(metrics.drop(columns="prob_cutoff"), "model")[1] == "config"


# THRESHOLDS AND OBSERVED DATA +++++++++++++++++++++++++++++++++++++++++++++++

def test_thresholds_2023_mapped_and_mw53_copied():
    app = pd.DataFrame({"city": "Dagupan", "year": 2020, "mw": range(1, 53), "thr_app": 2.0})
    app.loc[app.mw == 52, "thr_app"] = 7.0
    out = thresholds_from_contract(pd.DataFrame(), app)
    assert len(out) == 53 and set(out.adm3_pcode) == {P1}  # 2020 has 53 MWs
    assert out[out.mw_week == 53].threshold.iloc[0] == 7.0
    assert out.week_start.iloc[0] == pd.Timestamp("2019-12-29")


def test_history_wins_over_2023_table():
    hist = pd.DataFrame({"adm3_pcode": [P1], "week_start": [pd.Timestamp("2023-01-01")],
                         "mw_year": [2023], "mw_week": [1], "threshold": [9.0]})
    app = pd.DataFrame({"city": ["Dagupan"], "year": [2023], "mw": [1], "thr_app": [1.0]})
    assert thresholds_from_contract(hist, app).threshold.tolist() == [9.0]


def test_thresholds_table_model_first_app_only_as_fallback():
    cases = cases_rows()
    model = thresholds_from_contract(pd.DataFrame(), pd.DataFrame(
        {"city": ["Dagupan"], "year": [2023], "mw": [1], "thr_app": [42.0]}))
    out = thresholds_table(model, cases)
    assert out.threshold.tolist() == [42.0]          # no app values mixed in
    fallback = thresholds_table(model.iloc[0:0], cases)
    assert list(fallback.columns) == THRESHOLD_TABLE_COLUMNS
    assert set(fallback.source) == {"app: DOH mean + 2 SD (fallback)"}


def test_load_observed_from_contract(dirs):
    cases = cases_rows()
    write(cases, dirs["model_dir"], "cases")
    write(cases.rename(columns={"cases": "rain_mm_7d"}), dirs["model_dir"], "rain_imerg")
    write(pd.DataFrame({"adm3_pcode": [P2], "week_start": ["2014-01-05"],
                        "flag": ["non_reporting"]}), dirs["model_dir"], "reporting_flags")
    write(pd.DataFrame({"city": ["Dagupan"], "year": [2023], "mw": [1], "thr_app": [1.0]}),
          dirs["model_dir"], "thresholds_app")
    obs = load_observed(**dirs)
    assert {k: v.kind for k, v in obs["status"].items()} == {
        "cases": "model", "rain_imerg": "model", "reporting_flags": "model",
        "thresholds_history": "missing", "thresholds_app": "model"}
    flagged = obs["cases"][obs["cases"].reporting_flag.notna()]
    assert len(flagged) == 1 and flagged.adm3_pcode.iloc[0] == P2
    assert {"mw_year", "mw_week", "rain_mm"} <= set(obs["rain_weekly"].columns)


def test_load_observed_falls_back_to_parquet(dirs):
    cases = cases_rows()
    cases.assign(city_name="X").to_parquet(dirs["processed_dir"] / "cases_weekly.parquet")
    cases.rename(columns={"cases": "rain_mm"}).to_parquet(
        dirs["processed_dir"] / "rain_weekly.parquet")
    obs = load_observed(**dirs)
    kinds = {k: v.kind for k, v in obs["status"].items()}
    assert kinds["cases"] == kinds["rain_imerg"] == kinds["thresholds_history"] == "fallback"
    assert "CHIRPS" in obs["status"]["rain_imerg"].reason
    assert obs["thresholds"].source.str.startswith("app").all()


def test_load_observed_without_any_cases(dirs):
    with pytest.raises(FileNotFoundError, match="import_analysis_outputs"):
        load_observed(**dirs)


def test_every_part_has_a_label_and_file():
    assert set(PARTS) == set(config.CONTRACT_FILES) == set(config.CONTRACT_LABELS)
    with pytest.raises(ContractError):
        PARTS["cases"].validator(cases_rows().assign(week_start=pd.Timestamp("2015-01-05")))


# CITY CONFIDENCE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_city_confidence_validator():
    good = pd.DataFrame({"adm3_pcode": ["PH063022000", "PH072230000"],
                         "outbreak_weeks": [61, 3], "auc": [0.79, 0.47]})
    assert PARTS["city_confidence"].validator(good) == []
    for bad in (good.assign(auc=[1.2, 0.5]), good.assign(outbreak_weeks=[-1, 3]),
                pd.concat([good, good.iloc[:1]])):
        with pytest.raises(ContractError):
            PARTS["city_confidence"].validator(bad)


def test_city_confidence_file_is_delivered_and_valid():
    df, src = load_part("city_confidence")
    assert src.kind == "model" and len(df) == 12


def test_auc_scope_is_optional_and_checked(dirs):
    rows = pd.DataFrame({"horizon": [1, 1], "model": "final_model",
                         "scope": ["all weeks", "within city"], "auc": [0.85, 0.77]})
    assert PARTS["auc"].validator(rows) == ["auc.csv has no rows for ['last_week_only']"]
    with pytest.raises(ContractError, match="scope"):
        PARTS["auc"].validator(rows.assign(scope=["all weeks", "per city"]))
    with pytest.raises(ContractError, match="duplicate"):
        PARTS["auc"].validator(rows.assign(scope="all weeks"))
    write(rows.drop(columns="scope").iloc[:1], dirs["model_dir"], "auc")
    df, _ = load_auc(**dirs)
    assert df.scope.tolist() == ["all weeks"]                    # missing scope = all weeks


def test_episodes_and_rain_gain_validators_and_delivered_files():
    good = pd.DataFrame({"horizon": [1, 1], "episode": ["2+ weeks", "single week"],
                         "alert_level": ["Watch", "Watch"], "n": [3, 4], "share": [0.5, 0.4]})
    assert PARTS["episodes"].validator(good.copy()) == []
    for bad in (good.assign(horizon=[1, 3]), good.assign(episode=["2+ weeks", "never"]),
                good.assign(alert_level=["Watch", "Case signal only"]),
                good.assign(share=[0.5, 1.4]), pd.concat([good, good.iloc[:1]])):
        with pytest.raises(ContractError):
            PARTS["episodes"].validator(bad)
    gain = pd.DataFrame({"horizon": [1, 4], "gain_per_week": [0.03, 0.005], "lo": [0.01, -0.01],
                         "hi": [0.05, 0.02]})
    assert PARTS["rain_gain"].validator(gain.copy()) == []
    for bad in (gain.assign(horizon=[1, 5]), gain.assign(lo=[0.06, -0.01]),
                pd.concat([gain, gain.iloc[:1]])):
        with pytest.raises(ContractError):
            PARTS["rain_gain"].validator(bad)
    assert load_part("episodes")[1].kind == "model" and load_part("rain_gain")[1].kind == "model"


def test_replay_validator_and_delivered_file():
    good = pd.DataFrame({"event": "navotas", "adm3_pcode": P1,
                         "origin_week": ["2018-07-01", "2018-07-01"], "horizon": [1, 2],
                         "target_week": ["2018-07-01", "2018-07-08"],
                         "outbreak_prob": [0.1, 0.2], "alert_level": ["Watch", None],
                         "observed_cases": [1, 2]})
    for c in ("origin_week", "target_week"):
        good[c] = pd.to_datetime(good[c])
    assert PARTS["replay"].validator(good.copy()) == []
    for bad in (good.assign(horizon=[1, 3]), good.assign(outbreak_prob=[0.1, 1.5]),
                good.assign(alert_level=["Case signal only", None]),
                good.assign(target_week=pd.to_datetime(["2018-07-01", "2018-07-15"])),
                pd.concat([good, good.iloc[:1]])):
        with pytest.raises(ContractError):
            PARTS["replay"].validator(bad)
    df, src = load_part("replay")
    assert src.kind == "model" and set(df.event) == {"navotas", "washi", "iloilo"}
    assert set(df.horizon) == {1, 2}
