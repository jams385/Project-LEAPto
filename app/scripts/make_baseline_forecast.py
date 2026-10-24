"""Write labelled placeholders for the model parts that are still missing.

    python scripts/make_baseline_forecast.py

Run after scripts/import_analysis_outputs.py (or build_processed.py). Writes
data/processed/<part>_baseline.csv, in the contract-v2 schema, for each of
alerts, level_metrics, auc ("last_week_only" rows) and reporting_flags that
the modeling team's files do not cover. The app labels each one
"Baseline, model pending". A stale placeholder is deleted once the model
file covers that part. Every file is read back through the app's validator.
"""

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]      # the app folder
for _p in (ROOT, ROOT.parent):                  # src/ and the `app` package
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import config  # noqa: E402
from src.baseline import (baseline_reporting_flags, build_baseline_alerts,  # noqa: E402
                          compute_level_metrics, last_week_only_auc)
from src.contract import (PARTS, assign_levels, load_model_file,  # noqa: E402
                          load_observed)
from src.load_outputs import baseline_filename, read_contract_csv  # noqa: E402

# HELPERS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def write_placeholder(df, part_name, processed_dir):
    """Write a v2 placeholder and validate it like the app would.

    Parameters
    ----------
    df : pandas.DataFrame
        Contract-schema table.
    part_name : str
        Key of src.contract.PARTS.
    processed_dir : pathlib.Path

    Returns
    -------
    str
        One summary line. Raises ContractError if the app would reject it.
    """
    part = PARTS[part_name]
    path = Path(processed_dir) / baseline_filename(part.filename)
    df.to_csv(path, index=False, date_format="%Y-%m-%d", float_format="%.6g")
    check = read_contract_csv(path, list(part.columns), part.dates,
                              optional_columns=part.optional, allow_empty=part.allow_empty)
    part.validator(check)
    return f"wrote placeholder {path.name}: {len(check):,} rows"


def drop_placeholder(part_name, processed_dir):
    """Delete a placeholder the model file now replaces.

    Parameters
    ----------
    part_name : str
    processed_dir : pathlib.Path

    Returns
    -------
    str | None
        A message if a file was deleted, else None.
    """
    path = Path(processed_dir) / baseline_filename(PARTS[part_name].filename)
    if path.exists():
        path.unlink()
        return f"removed stale placeholder {path.name} (model file present)"
    return None


# STEPS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def write_v2_placeholders(obs, model_dir, processed_dir):
    """Write placeholders for the v2 parts the model files do not cover.

    Parameters
    ----------
    obs : dict
        src.contract.load_observed output.
    model_dir, processed_dir : pathlib.Path

    Returns
    -------
    list[str]
        Summary lines (what was written, kept or removed).
    """
    lines = []
    model = {name: load_model_file(name, model_dir=model_dir)
             for name in config.BASELINE_PARTS}

    flags, _ = model["reporting_flags"]
    if flags is None:
        flags = baseline_reporting_flags(obs["cases"])
        lines.append(write_placeholder(flags, "reporting_flags", processed_dir))
    else:
        lines.append(drop_placeholder("reporting_flags", processed_dir))

    alerts, _ = model["alerts"]
    if alerts is None:
        alerts = build_baseline_alerts(obs["cases"], obs["thresholds"], flags)
        lines.append(write_placeholder(alerts, "alerts", processed_dir))
    else:
        lines.append(drop_placeholder("alerts", processed_dir))
    levelled = assign_levels(alerts, config.LEVEL_CUTOFFS)

    if model["level_metrics"][0] is None:
        metrics = compute_level_metrics(levelled, config.LEVEL_CUTOFFS)
        lines.append(write_placeholder(metrics, "level_metrics", processed_dir)
                     + f" (cut-offs {config.LEVEL_CUTOFFS})")
    else:
        lines.append(drop_placeholder("level_metrics", processed_dir))

    auc, _ = model["auc"]
    have = set(auc.model) if auc is not None else set()
    if "last_week_only" not in have:
        lines.append(write_placeholder(last_week_only_auc(alerts, obs["cases"]), "auc",
                                       processed_dir))
    else:
        lines.append(drop_placeholder("auc", processed_dir))
    return [line for line in lines if line]


# MAIN +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def main(model_dir=None, processed_dir=None):
    """Build, write and re-validate the placeholder files.

    Parameters
    ----------
    model_dir, processed_dir : pathlib.Path | None
        Overrides for config.MODEL_OUTPUTS_DIR / config.PROCESSED_DIR (tests).

    Reads
    -----
    data/model_outputs/ (contract files) with the app's fallbacks:
    data/processed/{cases_weekly,rain_weekly,cities}.parquet.

    Returns
    -------
    list[str]
        The printed summary lines. Raises FileNotFoundError if no observed
        cases are available at all.
    """
    t0 = time.perf_counter()
    model_dir = config.MODEL_OUTPUTS_DIR if model_dir is None else Path(model_dir)
    processed_dir = config.PROCESSED_DIR if processed_dir is None else Path(processed_dir)
    cities_path = processed_dir / "cities.parquet"
    cities = pd.read_parquet(cities_path) if cities_path.exists() else None
    obs = load_observed(cities, model_dir=model_dir, processed_dir=processed_dir)

    lines = [f"{name}: {src.kind} ({src.reason})" for name, src in obs["status"].items()
             if src.kind != "model"]
    lines += write_v2_placeholders(obs, model_dir, processed_dir)
    lines.append(f"done in {time.perf_counter() - t0:.1f}s")
    print("\n".join(lines))
    return lines


if __name__ == "__main__":
    main()
