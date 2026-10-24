"""Tests for the analysis-output adapter (src/import_analysis.py and
scripts/import_analysis_outputs.py), on a small fake analysis folder and,
when present, on the real ../analysis (read-only)."""

import hashlib
import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import config
from src.contract import PARTS, load_part
from src.import_analysis import (AnalysisFormatError, assign_their_levels, check_levels,
                                 convert_auc, convert_city_confidence, convert_city_week,
                                 convert_episodes, convert_forecasts, convert_lag_response,
                                 convert_rain_gain, convert_replay,
                                 convert_thresholds_weekly, nb_exceed_prob)

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "import_analysis_outputs", ROOT / "scripts" / "import_analysis_outputs.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

CITIES = {"Dagupan": "PH015518000", "Navotas": "PH137503000"}
FINAL = config.ANALYSIS_ALERT_VARIANT                     # the final model's variant


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def city_week():
    """Two cities x 2013-2014 x 52 weeks, in their city_week.csv layout."""
    rows = []
    for city, pcode in CITIES.items():
        for year in (2013, 2014):
            for mw in range(1, 53):
                rows.append({"city": city, "adm3_pcode": pcode, "year": year, "mw": mw,
                             "days": 7, "cases": mw % 4, "include": "TRUE",
                             "in_pidsr_period": "TRUE", "flag_zero_run": "FALSE",
                             "flag_low_year": "FALSE",
                             "pr_week_imf": 10.0 + mw, "pr_week_iml": 11.0 + mw})
    df = pd.DataFrame(rows)
    # Dagupan 2013 MW10: zero-run week; Navotas 2014: whole low-reporting year
    df.loc[(df.city == "Dagupan") & (df.year == 2013) & (df.mw == 10),
           ["include", "flag_zero_run"]] = "FALSE", "TRUE"
    low = (df.city == "Navotas") & (df.year == 2014)
    df.loc[low, ["include", "flag_low_year"]] = "FALSE", "TRUE"
    return df


def thresholds_weekly():
    rows = [{"city": c, "year": y, "mw": w,
             "thr_exc5": 2.5 if y == 2014 else np.nan, "thr_exc3": 3.0}
            for c in CITIES for y in (2013, 2014) for w in range(1, 53)]
    return pd.DataFrame(rows)


def thresholds_2023():
    return pd.DataFrame([{"city": c, "year": 2023, "mw": w, "thr_app": 1.5,
                          "thr_app_source": "outbreak-excluded 5-year"}
                         for c in CITIES for w in range(1, 53)])


def forecasts():
    """Final-model and seasonal-only test rows (origin 2013 -> 2014), plus one train row."""
    rows = []
    for variant, mu in ((FINAL, 2.0), ("seasonal", 1.0)):
        for city in CITIES:
            for h in (1, 2, 3, 4):
                for mw in range(1, 53):
                    rows.append({"origin": 2013, "h": h, "variant": variant, "set": "test",
                                 "city": city, "year": 2014, "mw": mw, "days": 7,
                                 "include": not (city == "Navotas"), "cases": mw % 4,
                                 "mu": mu, "theta": 0.5, "thr_exc5": 2.5,
                                 "above_exc5": mw % 4 == 3})
    train = dict(rows[0], set="train", year=2013)
    return pd.DataFrame(rows + [train])


def risk_cutoffs():
    """Their stage 5d cut-offs: V1 (used) and V2 (ignored), horizons 1-2 only."""
    return pd.DataFrame([{"origin": 2013, "h": h, "city": c, "watch": w, "warn": x,
                          "version": v}
                         for h in (1, 2) for c in CITIES
                         for v, w, x in (("V1", 0.2, 0.5), ("V2", 0.01, 0.02))])


P_FINAL = nb_exceed_prob([2], [2.0], [0.5])[0]          # every final-model row's chance
LEVEL_V1 = "Warning" if P_FINAL >= 0.5 else "Watch" if P_FINAL >= 0.2 else "Normal"


def risk_weekly():
    """Their weekly levels for the included (Dagupan) test weeks."""
    return pd.DataFrame([{"origin": 2013, "h": h, "city": "Dagupan", "year": 2014, "mw": mw,
                          "version": "V1", "level": LEVEL_V1}
                         for h in (1, 2) for mw in range(1, 53)])


def auc_final():
    return pd.DataFrame([{"variant": v, "h": h, "weeks": 100, "auc_within_city": 0.77,
                          "auc_all": 0.85, "log_score": 0.8, "yearly_error": 1.0, "cities": c}
                         for v in (FINAL, "pooled_ar4_lvl") for h in (1, 2, 3, 4)
                         for c in ("All cities", "Other 11 cities")])


def auc_settings():
    # Their file repeats the seasonal rows once per comparison.
    return pd.DataFrame([{"variant": v, "h": h, "weeks": 100, "auc_within_city": a,
                          "auc_all": b}
                         for v, a, b in (("seasonal", 0.67, 0.75), ("pooled_ar", 0.73, 0.81),
                                         ("seasonal", 0.67, 0.75))
                         for h in (1, 2, 3, 4)])


def probability_scores():
    return pd.DataFrame([
        {"h": h, "grp": g, "threshold": t, "variant": v, "auc": 0.8}
        for h in (1, 2, 3, 4) for g in ("All cities", "Davao")
        for t in ("Outbreak-excluded", "Standard")
        for v in ("pooled_ar", "pooled", "seasonal", "regional_ar")])


def case_study_weekly():
    """Stage 6 rows: the final model and seasonal, strict and today views, 2 horizons."""
    rows = []
    for view in ("strict", "today"):
        for model in (FINAL, "seasonal"):
            for h in (1, 2):
                for mw in (24, 25, 26):
                    rows.append({"event": "navotas", "view": view, "model": model, "h": h,
                                 "city": "Navotas", "year": 2018, "mw": mw, "cases": mw % 5,
                                 "threshold": None if mw == 26 else 1.0,
                                 "above": mw == 25, "p": None if mw == 26 else 0.3,
                                 "level": None if mw == 26 else "Watch"})
    return pd.DataFrame(rows)


def risk_episodes():
    """Their stage 5d episode table: V1 and V2, horizons 1-3."""
    rows = []
    for version in ("V1", "V2"):
        for h in (1, 2, 3):
            for episode in ("2+ weeks", "single week"):
                for level, share in (("Normal", 0.2), ("Watch", 0.5), ("Warning", 0.3)):
                    rows.append({"version": version, "h": h, "episode": episode, "level": level,
                                 "N": int(100 * share), "share": share})
    return pd.DataFrame(rows)


def paired():
    """Their paired comparisons: the rain one plus another comparison to ignore."""
    rows = [{"comparison": "Rain vs no rain", "better": "pooled", "than": "seasonal", "h": h,
             "gain_per_week": 0.03 / h, "lo": 0.01 - 0.004 * h, "hi": 0.05}
            for h in (1, 2, 3, 4)]
    rows.append({"comparison": "Regional vs pooled rain curve", "better": "regional",
                 "than": "pooled", "h": 1, "gain_per_week": 0.0, "lo": -0.01, "hi": 0.01})
    return pd.DataFrame(rows)


def city_auc():
    """stage5/washi_by_city.csv: one row per variant x city."""
    return pd.DataFrame({"variant": [FINAL, FINAL, "pooled_ar4_lvl", "pooled_ar4_lvl"],
                         "city": list(CITIES) * 2, "outbreak_weeks": [45, 3, 45, 3],
                         "auc": [0.874, 0.6, 0.5, 0.5], "yearly_bias": 0.1})


def lag_response():
    return pd.DataFrame([{"lag": lag, "rr": 1.0 + lag / 10, "lo": 0.9, "hi": 2.5, "level": lvl}
                         for lvl in ("P95", "P99") for lag in range(11)])


@pytest.fixture
def analysis(tmp_path):
    """A fake read-only analysis project laid out like the real one."""
    base = tmp_path / "leapto-analysis"
    root = base / "analysis"
    files = {
        "data/processed/city_week.csv": city_week(),
        "output/stage4/thresholds_2023_for_app.csv": thresholds_2023(),
        "output/stage4/thresholds_weekly.csv": thresholds_weekly(),
        "output/stage5/forecasts_washi.csv.gz": forecasts().query("variant == @FINAL"),
        "output/stage5/forecasts.csv.gz": forecasts().query("variant == 'seasonal'"),
        "output/stage5/risk_levels_cutoffs.csv": risk_cutoffs(),
        "output/stage5/risk_levels_weekly.csv.gz": risk_weekly(),
        "output/stage5/washi_summary.csv": auc_final(),
        "output/stage5/settings_summary.csv": auc_settings(),
        "output/stage5/probability_scores.csv": probability_scores(),
        "output/stage3/lag_response.csv": lag_response(),
        "output/stage5/washi_by_city.csv": city_auc(),
        "output/stage6/case_study_weekly.csv": case_study_weekly(),
        "output/stage5/risk_levels_episodes.csv": risk_episodes(),
        "output/stage5/paired_comparisons.csv": paired(),
    }
    for rel, df in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
    return base


def tree_digest(folder):
    """{relative path: sha256} of every file under `folder`."""
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).rglob("*")) if p.is_file()}


# NEGATIVE BINOMIAL ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_nb_exceed_prob_matches_direct_sum():
    mu, theta = 3.7, 0.8
    pmf = lambda j: math.exp(math.lgamma(j + theta) - math.lgamma(theta) - math.lgamma(j + 1)
                             + theta * math.log(theta / (mu + theta))
                             + j * math.log(mu / (mu + theta)))
    for k in (0, 1, 5, 20):
        expected = 1 - sum(pmf(j) for j in range(k + 1))
        assert nb_exceed_prob([k], [mu], [theta])[0] == pytest.approx(expected, abs=1e-12)


def test_nb_exceed_prob_edges():
    out = nb_exceed_prob([-1, np.nan, 0], [2.0, 2.0, np.nan], [1.0, 1.0, 1.0])
    assert out[0] == 1.0 and np.isnan(out[1]) and np.isnan(out[2])


# CONVERTERS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_city_week_cases_rain_flags():
    out = convert_city_week(city_week())
    cases, rain, flags = out["cases"], out["rain_imerg"], out["reporting_flags"]
    first_2014 = cases[(cases.mw_year == 2014) & (cases.mw_week == 1)].week_start.iloc[0]
    assert first_2014 == pd.Timestamp("2013-12-29")  # DOH MW1 2014, a Sunday
    assert (cases.week_start.dt.dayofweek == 6).all() and len(cases) == 2 * 104
    assert rain.rain_mm_7d.iloc[0] == 11.0 and rain.rain_mm_7d_late.iloc[0] == 12.0
    assert flags.flag.value_counts().to_dict() == {"low_reporting_year": 52, "non_reporting": 1}


def test_city_week_rejects_pcode_mismatch():
    cw = city_week()
    cw.loc[0, "adm3_pcode"] = "PH999"
    with pytest.raises(AnalysisFormatError, match="disagrees"):
        convert_city_week(cw)


def test_city_week_missing_column():
    with pytest.raises(AnalysisFormatError, match="missing columns"):
        convert_city_week(city_week().drop(columns="pr_week_imf"))


def test_thresholds_weekly_uses_3_year_fallback():
    out = convert_thresholds_weekly(thresholds_weekly())
    assert set(out[out.mw_year == 2013].source) == {"outbreak-excluded 3-year (fallback)"}
    assert set(out[out.mw_year == 2014].threshold) == {2.5}


def test_unknown_city_name_is_rejected():
    tw = thresholds_weekly()
    tw.loc[0, "city"] = "Atlantis"
    with pytest.raises(AnalysisFormatError, match="Atlantis"):
        convert_thresholds_weekly(tw)


def test_forecasts_to_alerts():
    flags = convert_city_week(city_week())["reporting_flags"]
    out = convert_forecasts(forecasts(), flags, cutoffs=risk_cutoffs())
    assert set(out.horizon) == set(config.ALERT_HORIZONS) and len(out) == 2 * 52 * 2
    assert (out.target_week - out.origin_week == pd.to_timedelta((out.horizon - 1) * 7, "D")).all()
    assert out.outbreak_prob.iloc[0] == pytest.approx(P_FINAL)
    assert out.rr_vs_usual.iloc[0] == pytest.approx(P_FINAL / nb_exceed_prob([2], [1.0], [0.5])[0])
    dagupan = out[out.adm3_pcode == CITIES["Dagupan"]]
    navotas = out[out.adm3_pcode == CITIES["Navotas"]]
    assert set(dagupan.alert_level) == {LEVEL_V1}             # their V1 cut-offs, not V2
    assert navotas.observed_outbreak.isna().all()  # include == FALSE -> outcome unknown
    assert set(navotas.reporting_flag) == {"low_reporting_year"}
    assert set(navotas.alert_level) == {config.NO_REPORT_LEVEL}
    assert out.model_version.iloc[0].startswith(f"dlnm-nb-{FINAL}")
    assert PARTS["alerts"].validator(out.copy()) is not None  # passes the app's validator


def test_forecasts_without_cutoffs_leave_levels_to_the_app():
    flags = convert_city_week(city_week())["reporting_flags"]
    out = convert_forecasts(forecasts(), flags)
    assert out[out.reporting_flag.isna()].alert_level.isna().all()


def test_seasonal_rows_can_come_from_another_file():
    flags = convert_city_week(city_week())["reporting_flags"]
    final, seasonal = forecasts().query("variant == @FINAL"), forecasts().query("variant == 'seasonal'")
    out = convert_forecasts(final, flags, seasonal=seasonal)
    assert out.rr_vs_usual.notna().all()
    with pytest.raises(AnalysisFormatError, match="seasonal"):
        convert_forecasts(final, flags)


def test_their_levels_need_a_cutoff():
    lv = assign_their_levels([0.6, 0.3, 0.1, np.nan, 0.9], [2013] * 5, [1, 1, 1, 1, 3],
                             ["Dagupan"] * 5, risk_cutoffs())
    assert lv.tolist() == ["Warning", "Watch", "Normal", None, None]   # no h3 cut-off


def test_check_levels_counts_matches():
    flags = convert_city_week(city_week())["reporting_flags"]
    out = convert_forecasts(forecasts(), flags, cutoffs=risk_cutoffs())
    assert check_levels(out, risk_weekly()) == (104, 104)
    wrong = risk_weekly()
    wrong.loc[0, "level"] = "Normal" if LEVEL_V1 != "Normal" else "Warning"
    assert check_levels(out, wrong) == (103, 104)


def test_forecasts_missing_variant():
    with pytest.raises(AnalysisFormatError, match="no test rows"):
        convert_forecasts(forecasts(), pd.DataFrame(columns=["adm3_pcode", "week_start", "flag"]),
                          variant="regional_ar")
    with pytest.raises(AnalysisFormatError, match="no test rows"):
        convert_forecasts(forecasts(), pd.DataFrame(columns=["adm3_pcode", "week_start", "flag"]),
                          usual_variant="regional_ar")


def test_auc_final_seasonal_and_rain_only():
    out = convert_auc(auc_final(), auc_settings(), probability_scores())
    assert set(out.model) == {"final_model", "rain_only", "seasonal_only"}
    assert set(out.horizon) == set(config.ALERT_HORIZONS)
    by = out.set_index(["model", "scope", "horizon"]).auc
    assert by["final_model", "within city", 1] == 0.77 and by["final_model", "all weeks", 2] == 0.85
    assert by["seasonal_only", "within city", 1] == 0.67               # duplicates dropped
    assert len(out) == 4 + 4 + 2                     # rain only has no within-city figure
    assert PARTS["auc"].validator(out.copy()) == ["auc.csv has no rows for ['last_week_only']"]


def test_replay_keeps_only_the_strict_final_model_rows():
    out = convert_replay(case_study_weekly())
    assert len(out) == 6 and set(out.event) == {"navotas"}              # no today's-model rows
    assert set(out.horizon) == {1, 2} and out.model_version.str.contains("as of then").all()
    h2 = out[(out.horizon == 2) & (out.target_week == out.target_week.max())]
    assert (h2.origin_week == h2.target_week - pd.Timedelta(weeks=1)).all()
    last = out[out.target_week == out.target_week.max()]
    assert last.outbreak_prob.isna().all() and last.alert_level.isna().all()   # no chance, no level
    assert last.observed_outbreak.isna().all()                                 # no outbreak line
    assert PARTS["replay"].validator(out.copy()) == []
    with pytest.raises(AnalysisFormatError, match="no strict rows"):
        convert_replay(case_study_weekly().assign(view="today"))
    with pytest.raises(AnalysisFormatError, match="missing columns"):
        convert_replay(case_study_weekly().drop(columns="level"))


def test_episodes_keep_their_version_and_the_shown_horizons():
    out = convert_episodes(risk_episodes())
    assert set(out.horizon) == set(config.ALERT_HORIZONS) and len(out) == 12     # no V2, no h3
    assert list(out.columns) == ["horizon", "episode", "alert_level", "n", "share"]
    assert PARTS["episodes"].validator(out.copy()) == []
    with pytest.raises(AnalysisFormatError, match="no rows for version"):
        convert_episodes(risk_episodes(), version="V9")
    with pytest.raises(AnalysisFormatError, match="missing columns"):
        convert_episodes(risk_episodes().drop(columns="share"))


def test_rain_gain_keeps_only_the_rain_comparison():
    out = convert_rain_gain(paired())
    assert out.horizon.tolist() == [1, 2, 3, 4] and list(out.columns) == [
        "horizon", "gain_per_week", "lo", "hi"]
    assert PARTS["rain_gain"].validator(out.copy()) == []
    with pytest.raises(AnalysisFormatError, match="Rain vs no rain"):
        convert_rain_gain(paired().assign(comparison="Other"))


def test_city_confidence_keeps_the_alert_variant():
    out = convert_city_confidence(city_auc())
    assert list(out.columns) == ["adm3_pcode", "city", "outbreak_weeks", "auc"]
    assert out.set_index("city").auc.to_dict() == {"Dagupan": 0.874, "Navotas": 0.6}
    with pytest.raises(AnalysisFormatError, match="unknown city"):
        convert_city_confidence(city_auc().assign(city=["Atlantis", "Navotas"] * 2))
    with pytest.raises(AnalysisFormatError, match="no rows for variant"):
        convert_city_confidence(city_auc().query("variant != @FINAL"))


def test_lag_response_wide():
    out = convert_lag_response(lag_response())
    assert list(out.lag_weeks) == list(range(11))
    assert {"rr_p95", "rr_p99_upper"} <= set(out.columns)
    with pytest.raises(AnalysisFormatError, match="P99"):
        convert_lag_response(lag_response().query("level == 'P95'"))


# SCRIPT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_run_import_writes_valid_files_and_never_touches_analysis(analysis, tmp_path):
    before = tree_digest(analysis)
    out = tmp_path / "model_outputs"
    results = {r.part: r for r in script.run_import(analysis, out)}
    assert tree_digest(analysis) == before
    assert results["thresholds_app"].status == script.IMPORTED
    derived = {p for p, r in results.items() if r.status == script.DERIVED}
    assert derived == {"alerts", "auc", "rain_imerg", "lag_response", "reporting_flags",
                       "cases", "thresholds_history", "level_metrics", "city_confidence", "replay",
                       "episodes", "rain_gain"}
    for part in derived | {"thresholds_app"}:
        df, src = load_part(part, model_dir=out, processed_dir=tmp_path / "none")
        assert src.kind == "model", (part, src.reason)
        assert len(df) == results[part].rows
    assert (out / "thresholds_2023_for_app.csv").read_bytes() == \
        (analysis / "analysis/output/stage4/thresholds_2023_for_app.csv").read_bytes()
    # The track record is derived from the imported alerts, cut-offs left empty
    # so the app keeps calling them placeholders.
    metrics, _ = load_part("level_metrics", model_dir=out, processed_dir=tmp_path / "none")
    assert set(metrics.alert_level) == set(config.ALERT_LEVELS)
    assert metrics.prob_cutoff.isna().all()


def test_missing_source_is_reported_and_others_still_import(analysis, tmp_path):
    (analysis / "analysis/output/stage5/forecasts.csv.gz").unlink()
    results = {r.part: r for r in script.run_import(analysis, tmp_path / "out")}
    assert results["alerts"].status == script.MISSING
    assert "not found" in results["alerts"].source
    assert results["level_metrics"].status == script.MISSING   # needs the alerts
    assert results["cases"].status == script.DERIVED
    report = script.format_report(list(results.values()), analysis, tmp_path / "out")
    assert "[       MISSING] alerts.csv" in report


def test_refuses_to_write_inside_analysis(analysis):
    with pytest.raises(ValueError, match="refusing"):
        script.run_import(analysis, analysis / "analysis" / "output")
    assert script.main(["--analysis-dir", str(analysis), "--out-dir",
                        str(analysis / "x")]) == 1
    assert not (analysis / "x").exists()


def test_main_missing_folder(tmp_path, capsys):
    assert script.main(["--analysis-dir", str(tmp_path / "nope"),
                        "--out-dir", str(tmp_path / "out")]) == 1
    assert "not found" in capsys.readouterr().err


def test_env_var_sets_default(analysis, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(config.ANALYSIS_DIR_ENV, str(analysis))
    assert script.main(["--out-dir", str(tmp_path / "out")]) == 0
    assert "13 of 13 parts written" in capsys.readouterr().out


# REAL ANALYSIS FOLDER (skipped when absent) +++++++++++++++++++++++++++++++++

REAL = config.ANALYSIS_DIR_DEFAULT


@pytest.mark.skipif(not script.resolve_analysis_root(REAL).joinpath("output", "stage5").is_dir(),
                    reason="../analysis not available")
def test_real_import_reproduces_their_numbers(tmp_path):
    results = {r.part: r for r in script.run_import(REAL, tmp_path)}
    assert results["reporting_flags"].rows == 386        # SPEC_V2: 386 excluded weeks
    assert results["cases"].rows == 12 * 780             # 12 cities x 2008-2022
    alerts, _ = load_part("alerts", model_dir=tmp_path, processed_dir=tmp_path / "none")
    h1 = alerts[(alerts.horizon == 1) & alerts.observed_outbreak.notna()]
    y = h1.observed_outbreak.astype(bool)
    ranks = h1.outbreak_prob.rank()
    auc = (ranks[y].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (~y).sum())
    assert auc == pytest.approx(0.8492, abs=5e-4)        # their washi_summary.csv auc_all
    assert y.mean() == pytest.approx(0.0689, abs=5e-4)   # base rate ~6.8-6.9%
    # Their levels are reproduced exactly (risk_levels_weekly.csv.gz, V1).
    assert any("for 10,744 of 10,744 test weeks" in n for n in results["alerts"].notes)
    # The track record equals their risk_levels_summary.csv (V1, All cities, 1 week ahead).
    metrics, _ = load_part("level_metrics", model_dir=tmp_path, processed_dir=tmp_path / "none")
    m = metrics[metrics.horizon == 1].set_index("alert_level")
    assert m.n_weeks.to_dict() == {"Normal": 4210, "Watch": 859, "Warning": 303}
    assert m.loc["Warning", "hit_rate"] == pytest.approx(0.4191, abs=1e-4)
    assert m.loc["Watch", "capture_rate"] == pytest.approx(0.7108, abs=1e-4)
