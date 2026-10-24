#!/usr/bin/env bash
# LEAPto pipeline runner: build data -> import model outputs -> baseline -> run app.
#
#   ./run.sh            all steps (needs the raw CSVs in data/raw/)
#   ./run.sh data       raw CSVs -> data/processed/*.parquet + cities.geojson
#   ./run.sh import     modeling team's outputs (../analysis or
#                       $LEAPTO_ANALYSIS_DIR, read-only) -> data/model_outputs/
#   ./run.sh baseline   forecasts_baseline.csv + placeholders for missing parts
#   ./run.sh app        start the dashboard (http://localhost:8501)
#   ./run.sh test       run the pytest suite
#
# Works in Git Bash on Windows and in any POSIX shell. Uses .venv if present.
set -euo pipefail
cd "$(dirname "$0")"

# ENVIRONMENT ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
elif [ -x .venv/Scripts/python.exe ]; then
  PY=.venv/Scripts/python.exe
else
  PY=${PYTHON:-python}
fi

# STEPS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
build_data() {
  if [ ! -f data/raw/climate_atmosphere.csv ] || [ ! -f data/raw/disease_pidsr_totals.csv ]; then
    echo "Raw Project CCHAIN CSVs are missing from data/raw/ (see README > Data)." >&2
    echo "The committed data/processed/ files already let you run: ./run.sh app" >&2
    exit 1
  fi
  "$PY" scripts/build_processed.py
}
import_outputs() { "$PY" scripts/import_analysis_outputs.py ||   echo "Model outputs not imported; keeping the committed data/model_outputs/." >&2; }
baseline() { "$PY" scripts/make_baseline_forecast.py; }
app() { "$PY" -m streamlit run main.py; }
tests() { "$PY" -m pytest -q; }

case "${1:-all}" in
  all)      build_data; import_outputs; baseline; app ;;
  data)     build_data ;;
  import)   import_outputs ;;
  baseline) baseline ;;
  app)      app ;;
  test)     tests ;;
  *) echo "usage: ./run.sh [all|data|import|baseline|app|test]" >&2; exit 2 ;;
esac
