"""Import the modeling team's R outputs into data/model_outputs/ (contract v2).

    python scripts/import_analysis_outputs.py
    python scripts/import_analysis_outputs.py --analysis-dir ../analysis

Reads the analysis project at --analysis-dir, else $LEAPTO_ANALYSIS_DIR, else
../analysis (its `analysis/` subfolder is used when present). That
folder is READ-ONLY: this script only opens files there for reading and
refuses to write anywhere inside it.

For each contract file it prints whether it was imported as-is, derived from
their outputs, or is missing (and what to ask the modeling team). Every file
it writes is read back through the same validator the app uses.
"""

import argparse
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]      # the app folder
for _p in (ROOT, ROOT.parent):                  # src/ and the `app` package
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import config  # noqa: E402
from src.baseline import compute_level_metrics  # noqa: E402
from src.contract import PARTS  # noqa: E402
from src.import_analysis import (SOURCES, check_levels, convert_auc,  # noqa: E402
                                 convert_city_confidence, convert_city_week,
                                 convert_forecasts, convert_lag_response,
                                 convert_episodes, convert_rain_gain,
                                 convert_replay, convert_thresholds_weekly)
from src.load_outputs import ContractError, read_contract_csv  # noqa: E402

# RESULTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

IMPORTED, DERIVED, MISSING = "imported as-is", "derived", "missing"


@dataclass
class ImportResult:
    """Outcome for one contract part.

    Attributes
    ----------
    part : str
        Key of src.contract.PARTS.
    status : str
        IMPORTED, DERIVED or MISSING.
    source : str
        The analysis file(s) used, or why nothing was written.
    rows : int
        Rows written (0 when missing).
    notes : list[str]
        Caveats to show (placeholder definitions, validator warnings).
    """

    part: str
    status: str
    source: str
    rows: int = 0
    notes: list = field(default_factory=list)


# PATHS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def resolve_analysis_root(base):
    """Return the folder that holds their data/ and output/ folders.

    Parameters
    ----------
    base : pathlib.Path
        The analysis project (repo root or its `analysis/` subfolder).

    Returns
    -------
    pathlib.Path
        base/analysis when it has output/ or data/, else base itself.
    """
    sub = Path(base) / "analysis"
    return sub if (sub / "output").is_dir() or (sub / "data").is_dir() else Path(base)


def ensure_outside(out_dir, analysis_dir):
    """Refuse to write inside the read-only analysis project.

    Parameters
    ----------
    out_dir, analysis_dir : pathlib.Path

    Returns
    -------
    None. Raises ValueError if out_dir is analysis_dir or inside it.
    """
    out, ana = Path(out_dir).resolve(), Path(analysis_dir).resolve()
    if out == ana or ana in out.parents:
        raise ValueError(f"refusing to write into the analysis folder: {out}")


def read_source(root, key):
    """Read one analysis file (read-only).

    Parameters
    ----------
    root : pathlib.Path
        resolve_analysis_root output.
    key : str
        Key of src.import_analysis.SOURCES.

    Returns
    -------
    pandas.DataFrame. Raises FileNotFoundError if the file is absent.
    """
    path = root / SOURCES[key]
    if not path.exists():
        raise FileNotFoundError(f"{SOURCES[key]} not found")
    return pd.read_csv(path, low_memory=False, dtype={"adm3_pcode": str})


# WRITING ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def check_written(path, part_name):
    """Read a written file back through the app's validator.

    Parameters
    ----------
    path : pathlib.Path
    part_name : str
        Key of src.contract.PARTS.

    Returns
    -------
    tuple[int, list[str]]
        (rows, validator warnings). Raises ContractError if the app would
        reject the file.
    """
    part = PARTS[part_name]
    df = read_contract_csv(path, list(part.columns), part.dates,
                           optional_columns=part.optional, allow_empty=part.allow_empty)
    return len(df), part.validator(df)


def write_part(df, part_name, out_dir):
    """Write a contract table and validate it.

    Parameters
    ----------
    df : pandas.DataFrame
        Table in contract columns (dates as Timestamps).
    part_name : str
        Key of src.contract.PARTS.
    out_dir : pathlib.Path

    Returns
    -------
    tuple[int, list[str]]
        As check_written.
    """
    path = Path(out_dir) / config.CONTRACT_FILES[part_name]
    df.to_csv(path, index=False, date_format="%Y-%m-%d", float_format="%.6g")
    return check_written(path, part_name)


# IMPORT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def run_import(analysis_dir, out_dir):
    """Convert every available analysis output into data/model_outputs/.

    Parameters
    ----------
    analysis_dir : pathlib.Path
        The analysis project (read-only).
    out_dir : pathlib.Path
        Destination (created if needed; must be outside analysis_dir).

    Returns
    -------
    list[ImportResult]
        One per contract part, in config.CONTRACT_FILES order. A part whose
        source is missing or malformed is reported as MISSING and any file
        already in out_dir for it is left untouched.
    """
    ensure_outside(out_dir, analysis_dir)
    root = resolve_analysis_root(analysis_dir)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results = {}

    def attempt(part, status, source, build, notes=()):
        """Run build() -> DataFrame, write it, and record the outcome."""
        try:
            rows, warnings = write_part(build(), part, out_dir)
            results[part] = ImportResult(part, status, source, rows, list(notes) + warnings)
        except (FileNotFoundError, ValueError) as err:  # incl. AnalysisFormatError, ContractError
            results[part] = ImportResult(part, MISSING, f"{source}: {err}")

    # City-week table -> cases, rain, flags
    try:
        city = convert_city_week(read_source(root, "city_week"))
    except (FileNotFoundError, ValueError) as err:
        city = None
        for part in ("cases", "rain_imerg", "reporting_flags"):
            results[part] = ImportResult(part, MISSING, str(err))
    if city is not None:
        src = SOURCES["city_week"]
        attempt("cases", DERIVED, f"{src} (cases, on the app's Sunday calendar)",
                lambda: city["cases"])
        attempt("rain_imerg", DERIVED,
                f"{src} ({config.ANALYSIS_RAIN_COLUMN} = IMERG Final; "
                f"{config.ANALYSIS_RAIN_LATE_COLUMN} kept as rain_mm_7d_late)",
                lambda: city["rain_imerg"])
        attempt("reporting_flags", DERIVED, f"{src} (include == FALSE)",
                lambda: city["reporting_flags"])
    flags = city["reporting_flags"] if city is not None else pd.DataFrame(
        columns=["adm3_pcode", "week_start", "flag"])

    # Thresholds: 2023 file copied byte-for-byte after validation; history derived
    try:
        path = root / SOURCES["thresholds_app"]
        if not path.exists():
            raise FileNotFoundError(f"{SOURCES['thresholds_app']} not found")
        check_written(path, "thresholds_app")
        dest = Path(out_dir) / config.CONTRACT_FILES["thresholds_app"]
        shutil.copyfile(path, dest)
        rows, warnings = check_written(dest, "thresholds_app")
        results["thresholds_app"] = ImportResult("thresholds_app", IMPORTED,
                                                 SOURCES["thresholds_app"], rows, warnings)
    except (FileNotFoundError, ContractError) as err:
        results["thresholds_app"] = ImportResult("thresholds_app", MISSING, str(err))
    attempt("thresholds_history", DERIVED,
            f"{SOURCES['thresholds_weekly']} (thr_exc5, thr_exc3 before 2013)",
            lambda: convert_thresholds_weekly(read_source(root, "thresholds_weekly")))

    # Forecasts -> alerts, with the modeling team's risk levels (kept for the
    # track record below)
    built = {}

    def build_alerts():
        """Convert the final model's forecasts and check the levels against theirs."""
        built["alerts"] = convert_forecasts(read_source(root, "forecasts"), flags,
                                            seasonal=read_source(root, "forecasts_seasonal"),
                                            cutoffs=read_source(root, "risk_cutoffs"))
        try:
            same, total = check_levels(built["alerts"], read_source(root, "risk_weekly"))
            built["level_check"] = (f"levels match their risk_levels_weekly.csv.gz for "
                                    f"{same:,} of {total:,} test weeks")
        except (FileNotFoundError, ValueError) as err:
            built["level_check"] = f"levels not checked: {err}"
        return built["alerts"]

    attempt("alerts", DERIVED,
            f"{SOURCES['forecasts']} (final model {config.ANALYSIS_ALERT_VARIANT}, test years) + "
            f"{SOURCES['risk_cutoffs']} (version {config.ANALYSIS_LEVEL_VERSION})",
            build_alerts,
            notes=["outbreak_prob = 1 - pnbinom(floor(thr_exc5*days/7), theta, mu), as in "
                   "their R/05_validation.R and R/05d_risk_levels.R",
                   "alert_level = their cut-offs for that test year (Warning = top 5% of "
                   "training forecasts, Watch = next 15%); flagged weeks = No report",
                   "rr_vs_usual = outbreak_prob / seasonal-only outbreak_prob "
                   f"({SOURCES['forecasts_seasonal']}): PLACEHOLDER definition, not shown",
                   f"horizons {config.ALERT_HORIZONS} (their cut-offs exist for these only); "
                   "covers 2014-2022 (their out-of-sample test years)"])
    if "level_check" in built:
        results["alerts"].notes.append(built["level_check"])

    # Validation summaries
    attempt("auc", DERIVED,
            f"{SOURCES['auc_final']} (final model) + {SOURCES['auc_settings']} (seasonal) + "
            f"{SOURCES['probability_scores']} (rain only)",
            lambda: convert_auc(read_source(root, "auc_final"), read_source(root, "auc_settings"),
                                read_source(root, "probability_scores")),
            notes=["two scopes: 'all weeks' (pooled) and 'within city' (their headline)",
                   "no 'last_week_only' model exists in their outputs; the baseline "
                   "script adds a placeholder row set"])
    attempt("lag_response", DERIVED, f"{SOURCES['lag_response']} (reshaped long -> wide)",
            lambda: convert_lag_response(read_source(root, "lag_response")))
    if "alerts" in built:
        # prob_cutoff is left empty on purpose: their cut-offs change every
        # test year, so there is no single cut-off to write.
        attempt("level_metrics", DERIVED,
                "alerts.csv above (their test forecasts and their risk levels)",
                lambda: compute_level_metrics(built["alerts"]),
                notes=["same numbers as their risk_levels_summary.csv (version "
                       f"{config.ANALYSIS_LEVEL_VERSION}, All cities)"])
    else:
        results["level_metrics"] = ImportResult(
            "level_metrics", MISSING, "no alerts were imported, so there is no track record")
    attempt("replay", DERIVED,
            f"{SOURCES['case_studies']} (view strict: trained on earlier years only)",
            lambda: convert_replay(read_source(root, "case_studies")),
            notes=["Washi and Iloilo 2011-12 use the 3-year outbreak line and are trained on "
                   "about 2 years of data (their report, stage 6)",
                   "their 'today's model' view is left out: it is not a replay"])
    attempt("episodes", DERIVED,
            f"{SOURCES['risk_episodes']} (version {config.ANALYSIS_LEVEL_VERSION})",
            lambda: convert_episodes(read_source(root, "risk_episodes")),
            notes=["the level each outbreak's first week was forecast at, for multi-week "
                   "outbreaks and single-week blips"])
    attempt("rain_gain", DERIVED,
            f"{SOURCES['paired']} (Rain vs no rain: the earlier pooled rain model vs the "
            "calendar)",
            lambda: convert_rain_gain(read_source(root, "paired")),
            notes=["at 1-4 weeks ahead; not the final model: it shows why the app stops at "
                   "2 weeks"])
    attempt("city_confidence", DERIVED,
            f"{SOURCES['city_auc']} (AUC of variant {config.ANALYSIS_ALERT_VARIANT})",
            lambda: convert_city_confidence(read_source(root, "city_auc")))

    return [results[p] for p in config.CONTRACT_FILES if p in results]


# REPORT +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def format_report(results, analysis_dir, out_dir):
    """Human-readable import report.

    Parameters
    ----------
    results : list[ImportResult]
    analysis_dir, out_dir : pathlib.Path

    Returns
    -------
    str
        One block per part, then the list of things to ask the modeling team.
    """
    lines = [f"Analysis folder (read-only): {analysis_dir}", f"Written to: {out_dir}", ""]
    for r in results:
        name = config.CONTRACT_FILES[r.part]
        rows = f"{r.rows:,} rows" if r.status != MISSING else "-"
        lines.append(f"[{r.status.upper():>14}] {name:<30} {rows:>12}  <- {r.source}")
        lines.extend(f"{'':>17}note: {n}" for n in r.notes)
    missing = [r for r in results if r.status == MISSING]
    lines += ["", f"{sum(r.status != MISSING for r in results)} of {len(results)} parts written; "
                  f"{len(missing)} missing."]
    if missing:
        lines.append("Run `python scripts/make_baseline_forecast.py` to write labelled "
                     "placeholders for missing parts.")
    return "\n".join(lines)


# MAIN +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def main(argv=None):
    """Parse arguments, run the import and print the report.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments (sys.argv[1:] when None).

    Returns
    -------
    int
        0 on success, 1 if the analysis folder does not exist or the output
        folder is inside it.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--analysis-dir", type=Path,
                        default=Path(os.environ.get(config.ANALYSIS_DIR_ENV,
                                                    config.ANALYSIS_DIR_DEFAULT)))
    parser.add_argument("--out-dir", type=Path, default=config.MODEL_OUTPUTS_DIR)
    args = parser.parse_args(argv)
    if not args.analysis_dir.is_dir():
        print(f"Analysis folder not found: {args.analysis_dir}\n"
              f"Set {config.ANALYSIS_DIR_ENV} or pass --analysis-dir.", file=sys.stderr)
        return 1
    try:
        results = run_import(args.analysis_dir, args.out_dir)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    print(format_report(results, args.analysis_dir.resolve(), args.out_dir.resolve()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
