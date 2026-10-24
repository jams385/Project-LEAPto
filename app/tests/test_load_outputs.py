"""Tests for src/load_outputs.py: contract-file reading with baseline fallback."""

import logging

import pandas as pd
import pytest

from src.load_outputs import (ContractError, baseline_filename, load_with_fallback,
                              read_contract_csv)


# FIXTURES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@pytest.fixture
def dirs(tmp_path):
    model, processed = tmp_path / "model_outputs", tmp_path / "processed"
    model.mkdir()
    processed.mkdir()
    return {"model_dir": model, "processed_dir": processed}


def write(df, path):
    df.to_csv(path, index=False)
    return path


def rows(label="model"):
    return pd.DataFrame({"week_start": ["2015-03-01", "2015-03-08"], "value": [1.0, 2.0],
                         "label": label})


def positive(df):
    """Toy validator: values must be positive; warns on a 'odd' label."""
    if (df.value <= 0).any():
        raise ContractError("value must be positive")
    return ["odd label"] if (df.label == "odd").any() else []


def load(**dirs):
    return load_with_fallback("x.csv", ["week_start", "value", "label"], positive,
                              date_columns=("week_start",), **dirs)


# FALLBACK ORDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_model_file_preferred(dirs):
    write(rows(), dirs["model_dir"] / "x.csv")
    write(rows("baseline"), dirs["processed_dir"] / "x_baseline.csv")
    df, src = load(**dirs)
    assert src.kind == "model" and not src.is_baseline and set(df.label) == {"model"}
    assert df.week_start.dtype.kind == "M"


def test_missing_model_falls_back_to_baseline(dirs):
    write(rows("baseline"), dirs["processed_dir"] / "x_baseline.csv")
    df, src = load(**dirs)
    assert src.kind == "baseline" and src.is_baseline and "not found" in src.reason


def test_empty_model_file_falls_back(dirs):
    (dirs["model_dir"] / "x.csv").write_text("")
    write(rows("baseline"), dirs["processed_dir"] / "x_baseline.csv")
    _, src = load(**dirs)
    assert src.kind == "baseline" and "0 bytes" in src.reason


@pytest.mark.parametrize("break_it, message", [
    (lambda d: d.assign(value=-1.0), "value must be positive"),
    (lambda d: d.drop(columns="label"), "missing columns"),
    (lambda d: d.assign(week_start="01/03/2015"), "not a YYYY-MM-DD date"),
])
def test_invalid_model_file_falls_back_with_reason(dirs, break_it, message, caplog):
    write(break_it(rows()), dirs["model_dir"] / "x.csv")
    write(rows("baseline"), dirs["processed_dir"] / "x_baseline.csv")
    with caplog.at_level(logging.WARNING):
        _, src = load(**dirs)
    assert src.kind == "baseline" and message in src.reason
    assert message in caplog.text


def test_nothing_usable_returns_empty_missing(dirs):
    df, src = load(**dirs)
    assert src.kind == "missing" and df.empty and list(df.columns) == ["week_start", "value",
                                                                       "label"]


def test_validator_warnings_are_kept(dirs):
    write(rows("odd"), dirs["model_dir"] / "x.csv")
    _, src = load(**dirs)
    assert src.kind == "model" and src.warnings == ("odd label",)


# GENERIC READER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def test_optional_columns_kept_others_dropped(tmp_path):
    path = write(pd.DataFrame({"a": [1], "opt": [2], "junk": [3]}), tmp_path / "x.csv")
    df = read_contract_csv(path, ["a"], optional_columns=("opt", "absent"))
    assert list(df.columns) == ["a", "opt"]


def test_header_only_file_needs_allow_empty(tmp_path):
    path = write(pd.DataFrame(columns=["a"]), tmp_path / "x.csv")
    with pytest.raises(ContractError, match="no rows"):
        read_contract_csv(path, ["a"])
    assert read_contract_csv(path, ["a"], allow_empty=True).empty


def test_pcodes_stay_text(tmp_path):
    path = write(pd.DataFrame({"adm3_pcode": ["PH015518000"]}), tmp_path / "x.csv")
    assert read_contract_csv(path, ["adm3_pcode"]).adm3_pcode.iloc[0] == "PH015518000"


def test_directories_resolved_at_call_time(dirs, monkeypatch):
    from app import config
    write(pd.DataFrame({"a": [1]}), dirs["model_dir"] / "x.csv")
    monkeypatch.setattr(config, "MODEL_OUTPUTS_DIR", dirs["model_dir"])
    df, src = load_with_fallback("x.csv", ["a"], lambda d: [])
    assert src.kind == "model" and len(df) == 1


def test_helpers(tmp_path):
    assert baseline_filename("alerts.csv") == "alerts_baseline.csv"
    with pytest.raises(ContractError):
        read_contract_csv(tmp_path / "nope.csv", ["a"])
