# LEAPto — statistical analysis

Statistical analysis for the LEAPto app: weekly leptospirosis cases vs. rainfall in 12 Philippine cities (2008–2022). This analysis produces the rainfall–case model (DLNM), the DOH epidemic thresholds, the forecast validation and the case studies used by the app.

The methods and results are written up in the report, [`dataset_documentation/LeapTo_Overall_Model_Report.pdf`](dataset_documentation/LeapTo_Overall_Model_Report.pdf).

## Setup

1. Open `LeapTo.Rproj` in RStudio. This sets the working directory to this folder. **All scripts assume they're run from here**, so don't use `setwd()`.

2. Restore packages (first time only):
   ```r
   renv::restore()
   ```
   R 4.6.1 was used.

3. Get the raw data, more on it in the next section.

4. Only for the river-flow scripts (Stage 7c): Python 3 with `numpy`, `pandas`, `xarray` (with a netCDF backend), `shapely` and `matplotlib`, plus `cdsapi` for the download.

## Data

`data/raw/` and `data/external/` are **not committed** because they're too large (`climate_atmosphere.csv` alone is 544 MB). `data/processed/` **is** committed, so Stages 2 to 6, `07b` and `07e`–`07g` run without them. The scripts that still need them are the downloads, Stage 1 (`01`, `01b`), `07_flood.R` (raw Project NOAH, location, WorldPop and barangay case files), `07c` (raw barangay shapes and the GloFAS files), `07d` (GloFAS files) and `imerg_test.R`.

| Folder | Contents | Source |
|---|---|---|
| `data/raw/` | `disease_pidsr_totals.csv`, `disease_lgu_disaggregated_totals.csv`, `climate_atmosphere.csv`, `location.csv`, `calendar.csv`, `worldpop_population.csv`, `brgy_geography.csv`, `project_noah_hazards.csv` | [Project CCHAIN](https://doi.org/10.34740/kaggle/ds/4918229) (data documentation in [`dataset_documentation/`](dataset_documentation/)) |
| `data/external/imerg/` | NASA IMERG daily rainfall, Final and Late | `R/imerg_download.R` (free NASA Earthdata account) |
| `data/external/glofas/` | GloFAS river discharge | `R/glofas_download.py` (Copernicus EWDS account) |
| `data/processed/` | `city_week*.csv/.rds`: one row per city × DOH morbidity week; daily IMERG and GloFAS city series | built by `01`, `01b`, `07d` and `07e` |

## Run order

Run each script from this folder, in this order: R scripts with e.g. `source("R/03_dlnm.R")`, Python scripts with e.g. `python3 R/07c_glofas_rivers.py`. Every R script loads `R/_common.R`, which holds the shared paths and helper functions, either directly or through the earlier script it builds on.

**"App"** marks scripts whose outputs the dashboard imports (through `app/scripts/import_analysis_outputs.py`).

| Order | Script | What it does | Output | App |
|---|---|---|---|---|
| once | `R/imerg_download.R` | Download NASA IMERG daily rainfall, 2003–2022 | `data/external/imerg/` | |
| once | `R/glofas_download.py` | Download GloFAS river discharge, 2003–2022 | `data/external/glofas/all/` | |
| 1 | `R/01_build_dataset.R` | Build the city × week dataset and data-quality tables; runs `01b_add_imerg.R` at the end | `data/processed/city_week*`, `output/stage1/` | ✓ |
| 1b | `R/01b_add_imerg.R` | Add IMERG rainfall columns (run by `01`) | `data/processed/`, `output/stage1/imerg_*` | |
| 2 | `R/02_eda.R` | Exploratory analysis: seasonality, lag correlations, overdispersion, COVID shift | `output/stage2/` | |
| 2b | `R/02b_rainfall_sources.R` | Compare CHIRPS with IMERG Final and Late | `output/stage2b/` | |
| 3 | `R/03_dlnm.R` | Pooled negative binomial DLNM: how risk rises in the weeks after rain | `output/stage3/` (incl. `main_model.rds`) | ✓ |
| 3c | `R/03c_washi_check.R` | Do the Stage 3 results depend on Typhoon Washi? (needs `03`) | `output/stage3/washi_check.csv` | |
| 4 | `R/04_thresholds.R` | DOH epidemic thresholds per city (mean + 2 SD) | `output/stage4/` | ✓ |
| 5 | `R/05_validation.R` | Rolling-origin forecast validation, 2014–2022 | `output/stage5/forecasts.csv.gz`, scores | ✓ |
| 5b | `R/05b_ceiling.R` | Ceiling test: how good could any forecast be? (needs `03`–`05`) | `output/stage5/ceiling_*` | |
| 5c | `R/05c_settings.R` | Compare model settings (case history, recent level) | `output/stage5/settings_*`, `forecasts_settings.csv.gz` | ✓ |
| 5e | `R/05e_washi_setaside.R` | **Final forecasting model**: the 5c model with Typhoon Washi set aside | `output/stage5/washi_*`, `forecasts_washi.csv.gz` | ✓ |
| 5d | `R/05d_risk_levels.R` | Normal / Watch / Warning cut-offs (**needs `05e`**) | `output/stage5/risk_levels_*` | ✓ |
| 6 | `R/06_case_studies.R` | Case studies: Washi (CDO 2011), Navotas 2018, Iloilo 2011–2012 (needs `05e`) | `output/stage6/` | ✓ |
| 7 | `R/07_flood.R` | Flood hazard as an effect modifier of the rain effect | `output/stage7/` (flood) | |
| 7b | `R/07b_flood_forecast.R` | Does flood exposure improve the forecasts? (needs `05`, `07`) | `output/stage7/forecast_*` | |
| 7c | `R/07c_glofas_rivers.py` | Choose each city's river cell; check against known floods | `output/stage7/glofas_*` | |
| 7d | `R/07d_glofas_weekly.py` | Daily river flow per city | `data/processed/glofas_city_day.csv` | |
| 7e | `R/07e_glofas_signal.R` | Weekly river-flow signal | `data/processed/glofas_city_week.csv`, `output/stage7/glofas_signal_*` | |
| 7f | `R/07f_glofas_explain.R` | Does river flow explain cases beyond rain? | `output/stage7/river_explain_*` | |
| 7g | `R/07g_glofas_forecast.R` | Does river flow improve the forecasts? (needs `05c`) | `output/stage7/river_forecast_*` | |
| check | `R/imerg_test.R` | One-off: IMERG vs CHIRPS vs station records for three storms | `data/external/imerg_test/`, `output/imerg_test/` | |

`05e` runs before `05d` and `06` because they read its `forecasts_washi.csv.gz`.
