"""Generic contract-file reading with model -> baseline fallback.

`read_contract_csv` and `load_with_fallback` are shared by every contract
file; the parts themselves are defined in src/contract.py. A file that is
missing, empty or fails validation is skipped (with the reason recorded),
never fatal. Loaders return (DataFrame, OutputSource) so the UI can show a
"Baseline, model pending" banner.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app import config

log = logging.getLogger(__name__)

# SOURCES ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

class ContractError(ValueError):
    """A model-output file does not meet docs/DATA_CONTRACT.md."""


@dataclass(frozen=True)
class OutputSource:
    """Where a loaded table came from, for the UI banner and logs.

    Attributes
    ----------
    kind : str
        "model" (modeling team file), "baseline" (labelled placeholder in
        data/processed), "fallback" (the app's own pipeline or threshold
        logic, shown with a warning) or "missing" (nothing usable; empty table).
    path : Path | None
        File actually read, None when missing.
    reason : str
        Human-readable explanation, e.g. why the model file was skipped.
    warnings : tuple[str, ...]
        Non-fatal issues found by the validator.
    """

    kind: str
    path: Path | None
    reason: str
    warnings: tuple = field(default_factory=tuple)

    @property
    def is_baseline(self):
        """True unless the R team's own file was used."""
        return self.kind != "model"


def baseline_filename(filename):
    """Return the baseline fallback name for a contract file name.

    Parameters
    ----------
    filename : str
        e.g. "alerts.csv".

    Returns
    -------
    str
        e.g. "alerts_baseline.csv".
    """
    stem, _, ext = filename.rpartition(".")
    return f"{stem}_baseline.{ext}"


# READING AND VALIDATION +++++++++++++++++++++++++++++++++++++++++++++++++++++

def read_contract_csv(path, columns, date_columns=(), *, optional_columns=(),
                      allow_empty=False):
    """Read a contract CSV, keeping only the contract columns.

    Parameters
    ----------
    path : pathlib.Path
        CSV file.
    columns : list[str]
        Required columns, in output order.
    date_columns : iterable[str]
        Columns parsed as ISO dates (YYYY-MM-DD).
    optional_columns : iterable[str]
        Kept (after `columns`) when present; all other extra columns are dropped.
    allow_empty : bool
        Accept a header with no rows (e.g. a week list with nothing flagged).

    Returns
    -------
    pandas.DataFrame with `columns` plus whichever `optional_columns` exist.
    adm3_pcode, when present, is read as text.

    Raises
    ------
    ContractError
        File missing, 0 bytes, no data rows (unless allow_empty), missing
        columns or bad dates.
    """
    if not path.exists():
        raise ContractError(f"{path.name} not found")
    if path.stat().st_size == 0:
        raise ContractError(f"{path.name} is empty (0 bytes)")
    df = pd.read_csv(path, dtype={"adm3_pcode": str})
    if df.empty and not allow_empty:
        raise ContractError(f"{path.name} has a header but no rows")
    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ContractError(f"{path.name} is missing columns {missing}")
    df = df[list(columns) + [c for c in optional_columns if c in df.columns]].copy()
    for col in date_columns:
        parsed = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
        if parsed.isna().any():
            bad = df.loc[parsed.isna(), col].iloc[0]
            raise ContractError(f"{path.name}: {col} value {bad!r} is not a YYYY-MM-DD date")
        df[col] = parsed
    return df


# FALLBACK LOADING +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def load_with_fallback(filename, columns, validator, *, date_columns=(),
                       optional_columns=(), allow_empty=False,
                       model_dir=None, processed_dir=None):
    """Load a contract file from the model team, else its baseline copy.

    Parameters
    ----------
    filename : str
        Contract file name, e.g. "alerts.csv".
    columns : list[str]
        Required contract columns.
    validator : callable(DataFrame) -> list[str]
        Raises ContractError on fatal problems, returns warnings otherwise.
        It may normalise dtypes in place (e.g. booleans read as text).
    date_columns, optional_columns, allow_empty
        Passed to read_contract_csv.
    model_dir, processed_dir : pathlib.Path | None
        Where to look for the model file and the baseline file. None means
        config.MODEL_OUTPUTS_DIR / config.PROCESSED_DIR, read at call time.

    Returns
    -------
    tuple[pandas.DataFrame, OutputSource]
        The first usable table (model, then baseline). If neither is usable,
        an empty frame with `columns` and kind="missing". Never raises for
        contract problems; each skip is logged at WARNING level.
    """
    model_dir = config.MODEL_OUTPUTS_DIR if model_dir is None else model_dir
    processed_dir = config.PROCESSED_DIR if processed_dir is None else processed_dir
    reasons = []
    candidates = [("model", Path(model_dir) / filename),
                  ("baseline", Path(processed_dir) / baseline_filename(filename))]
    for kind, path in candidates:
        try:
            df = read_contract_csv(path, columns, date_columns,
                                   optional_columns=optional_columns,
                                   allow_empty=allow_empty)
            warnings = validator(df)
        except ContractError as err:
            reasons.append(f"{kind} file skipped: {err}")
            log.warning("%s file skipped: %s", kind, err)
            continue
        except (pd.errors.ParserError, UnicodeDecodeError) as err:
            reasons.append(f"{kind} file skipped: could not parse {path.name} ({err})")
            log.warning("%s file skipped: could not parse %s (%s)", kind, path.name, err)
            continue
        for w in warnings:
            log.warning("%s: %s", path.name, w)
        reason = "; ".join(reasons) if reasons else f"loaded {kind} file"
        return df, OutputSource(kind, path, reason, tuple(warnings))
    return (pd.DataFrame(columns=columns),
            OutputSource("missing", None, "; ".join(reasons)))
