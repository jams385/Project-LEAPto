# LEAPto

**Leptospirosis Early Alert Platform**: a dashboard that gives 12 Philippine cities a leptospirosis alert level for the next week and the week after.

Leptospirosis spreads through floodwater, and cases rise in the weeks after heavy rain. Although there are tools to describes a flood, not many the disease risk that follows it. Health offices need that lead time to pre-position doxycycline prophylaxis, supplies, and advisories before cases peak.

LEAPto links satellite rainfall (NASA IMERG) and past reported cases to an alert level (Warning, Watch or Normal) for each city and week, with suggested actions for residents and health offices.

## Where to start

| What you are looking for | Path |
|---|---|
| A quick summary of the project | [The project at a glance](#the-project-at-a-glance) |
| The main results | [What it found](#what-it-found) |
| How the model works: methods, results and validation | The model report: [`analysis/dataset_documentation/LeapTo_Overall_Model_Report.pdf`](analysis/dataset_documentation/LeapTo_Overall_Model_Report.pdf) |
| How to run the app | [Quick start](#quick-start), or [app/README.md](app/README.md) for more detail |
| A guided tour of the app's screens | The [demo script](app/docs/DEMO_SCRIPT.md) |
| How to reproduce the model | The [analysis pipeline](analysis/README.md): setup, data downloads and the order to run the scripts |
| How the app's code is organized | The [app code tour](app/docs/CODE_TOUR.md) |
| Where the data comes from | [Data sources and credits](#data-sources-and-credits) and [References](#references) |
| What the model can't do | [Limitations](#limitations) |


## The project at a glance

| | |
|---|---|
| **Problem** | Cases of leptospirosis peak weeks after floods, but there are no current tool that can turn rainfall into a disease alert that a city health office can act on. |
| **Data** | Weekly DOH PIDSR leptospirosis cases for 12 cities, 2008–2022 (Project CCHAIN); NASA IMERG satellite rainfall; Project NOAH flood hazard; WorldPop population. |
| **Method** | A pooled negative binomial distributed lag non-linear model (DLNM) measures how risk rises in the weeks after rain. A forecasting model (seasonality, recent case level and case history, plus rain known at forecast time, with a 1-week reporting delay) gives each city-week a chance of being an outbreak week, meaning above the city's DOH epidemic threshold (mean + 2 SD). That chance becomes Warning (top 5%), Watch (next 15%) or Normal. |
| **Validation** | Rolling-origin testing: for each year 2014–2022 the model was fitted only on earlier years, then scored against a seasonal-only baseline. Three known outbreaks were replayed as case studies, misses included. |
| **Impact** | One to two weeks of warning before cases peak, enough to pre-position prophylaxis, supplies and advisories. The app gives health offices suggested actions and residents a plain-language view of their city's risk. |
| **Limitations** | Reported cases only, data ends in 2022, satellite rain misses extreme local floods, and small cities have too few outbreaks to forecast. See [Limitations](#limitations). |

Flood hazard and GloFAS river flow were also tested as additions to the model (Stage 7 in the [analysis pipeline](analysis/README.md)).

## What it found

Weekly cases from 12 cities, 2008–2022. Forecasts were tested on 2014–2022 using only earlier data.

- **Rain comes before cases.** Risk peaks **2 weeks** after a heavy-rain week, at **1.77×** a typical week. About **23%** of cases followed a city's wettest 5% of weeks.
- **Alerts work.** **42%** of Warning weeks became outbreak weeks, against 7% of all weeks; Warning or Watch flagged **71%** of outbreak weeks one week ahead.
- **It beats the calendar.** AUC **0.85** vs 0.75 for seasonal timing alone. Rain adds skill 1–2 weeks ahead, not beyond.
- **Case studies:** caught Navotas 2018 (11 of 12 outbreak weeks flagged), missed Typhoon Washi (Cagayan de Oro, 2011), and did no better than the calendar for Iloilo 2011–2012.
- **Not every city:** Palayan, Legazpi and Mandaue have too few outbreaks to forecast; Cagayan de Oro and Tacloban are lower confidence.

Full results, confidence intervals and the 2-weeks-ahead figures are in the [model report](analysis/dataset_documentation/LeapTo_Overall_Model_Report.pdf). Sources: `analysis/output/stage3/headline_rr.csv`, `attributable_cases.csv`; `app/data/model_outputs/level_metrics.csv`, `auc.csv`, `rain_gain.csv`, `city_confidence.csv`; `analysis/output/stage6/case_study_summary.csv`.

## How the repository fits together

```
Project CCHAIN, NASA IMERG, GloFAS        (raw data, not committed: too large)
        │
        ▼
analysis/R/  stages 1–7                    R project: dataset → DLNM → thresholds → validation → case studies
        │
        ▼
analysis/output/stageN/                    model results (committed)
        │   app/scripts/import_analysis_outputs.py
        ▼
app/data/model_outputs/                    the 13 files the app reads (committed)
        │
        ▼
app/main.py                                Streamlit dashboard: Overview, Replay, Data reliability
```

| Folder | What is in it |
|---|---|
| [analysis/](analysis/README.md) | R project: dataset build, rainfall-case model (DLNM), DOH epidemic thresholds, forecast validation, case studies, and the model report. |
| [app/](app/README.md) | Streamlit dashboard (Overview, Replay, Data reliability), its tests, and the model results it reads in `app/data/model_outputs/`. |

The app never fits a model. It reads the committed files in `app/data/model_outputs/`, so it runs without `analysis/`.

## Quick start

Run the app (Python 3.10). Open a terminal in the repository folder, then follow the steps for your system.

**macOS / Linux** (Terminal)

```bash
cd app                             
python3 -m venv .venv             
source .venv/bin/activate          
pip install -r requirements.txt    # install the packages (first time only)
streamlit run main.py              # start the app: opens http://localhost:8501
```

**Windows** (PowerShell)

```powershell
cd app                             
py -m venv .venv             
.venv\Scripts\Activate.ps1         
pip install -r requirements.txt    # install the packages (first time only)
streamlit run main.py              # start the app: opens http://localhost:8501
```

If PowerShell says "running scripts is disabled on this system" at the activate step, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer `Y`, and activate again. In Command Prompt (cmd) instead of PowerShell, activate with `.venv\Scripts\activate.bat`.

To stop the app, press `Ctrl+C` in the terminal. Next time, only the `cd app`, activate and `streamlit run main.py` steps are needed. [app/README.md](app/README.md#quick-start) covers pyenv and running the tests.

On the landing page choose "Explore demo without an account".

Reproduce the model (R 4.6, RStudio):

```text
Open analysis/LeapTo.Rproj, then follow analysis/README.md
```

The raw data is not committed because of its size; [analysis/README.md](analysis/README.md) says where to get it.

## Data sources and credits

| Data | Used for | Source and terms |
|---|---|---|
| Weekly leptospirosis cases, 12 cities, 2008–2022 | Model, thresholds, app | DOH PIDSR, compiled by Epimetrics under data use agreements, published in [Project CCHAIN](https://thinkingmachines.github.io/project-cchain/open_data.html) (CC BY 4.0) |
| Barangay-level cases (Zamboanga, Muntinlupa) | Flood check in Stage 7 | City health and surveillance offices, via Project CCHAIN (CC BY 4.0) |
| Daily rainfall, CHIRPS | Compared with IMERG (Stage 2b) | Climate Hazards Center, UC Santa Barbara, via Project CCHAIN; public domain |
| Temperature and humidity, ERA5 | Confounder check (Stage 2) | Copernicus Climate Change Service, via Project CCHAIN. Contains modified Copernicus Climate Change Service information 2023 |
| Satellite rainfall, NASA GPM IMERG V07 (Final and Late) | Model and app | NASA GES DISC; free and open, source acknowledged as NASA asks |
| River discharge, GloFAS | River-flow check in Stage 7 | Copernicus Emergency Management Service, [CEMS-FLOODS licence](https://ewds.climate.copernicus.eu/licences/cems-floods). Contains modified Copernicus Emergency Management Service information 2026 |
| Flood hazard maps (5-, 25- and 100-year) | Stage 7 and app | UP Resilience Institute & NOAH Center (Project NOAH), via Project CCHAIN (CC BY 4.0) |
| Population | Rates and offsets | WorldPop (CC BY 4.0), via Project CCHAIN |
| City and barangay boundaries | App map | Project CCHAIN (CC BY 4.0) |
| Satellite basemap | App map | Esri World Imagery (Esri, Vantor, Earthstar Geographics, and the GIS User Community), used under Esri's terms; the map shows the required credit |
| Landing background | App | NASA Blue Marble Next Generation, public domain |

Project CCHAIN is by Thinking Machines Data Science with Epimetrics and the Manila Observatory; their data documentation is in [`analysis/dataset_documentation/`](analysis/dataset_documentation/).

## Limitations

- Surveillance counts only cases that were reported, so every number is a lower bound, and reports arrive about a week late.
- The data ends in 2022. Levels cover the next week and the week after, not further ahead.
- Weekly satellite rain at about 10 km misses extreme local floods. The model gave no early signal for Typhoon Washi.
- Small cities have too few outbreak weeks to forecast reliably. Flood hazard is a single fixed snapshot.
- A level describes a city and a week and is linked to rainfall. It does not say what caused any case or anything about one person's risk.

## License

- **Code:** [MIT License](LICENSE).
- **Data:** the raw source files are not in this repository. The committed data files (`analysis/data/processed/`, `analysis/output/`, `app/data/`) are derived from the sources above: aggregated to city and week, combined, and modelled. They keep the terms of those sources: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) for the Project CCHAIN and WorldPop data, and the Copernicus licences for ERA5 and GloFAS. Credit the sources listed above if you reuse them.

## Disclaimer

LEAPto is a research prototype that replays past years. It is not an official warning from the Department of Health, PAGASA or any local government, and it is not medical advice. The data and results are provided as is, without warranty. GloFAS river data is for information only and is not a flood warning.

## References

Copernicus Emergency Management Service. (2019). *River discharge and related historical data from the Global Flood Awareness System* (Version 4.0) [Data set]. Early Warning Data Store. https://doi.org/10.24381/cds.a4fdd6b9

Department of Health, Epidemiology Bureau. (2023). *Philippine Integrated Disease Surveillance and Response (PIDSR) weekly city-level case counts, 2008–2022* [Data set]. Compiled in Project CCHAIN.

Esri. (n.d.). *World Imagery* [Basemap]. https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9

Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, J., Shukla, S., Husak, G., Rowland, J., Harrison, L., Hoell, A., & Michaelsen, J. (2015). The climate hazards infrared precipitation with stations: A new environmental record for monitoring extremes. *Scientific Data, 2*, Article 150066. https://doi.org/10.1038/sdata.2015.66

Hersbach, H., Bell, B., Berrisford, P., Biavati, G., Horányi, A., Muñoz Sabater, J., Nicolas, J., Peubey, C., Radu, R., Rozum, I., Schepers, D., Simmons, A., Soci, C., Dee, D., & Thépaut, J.-N. (2023). *ERA5 hourly data on pressure levels from 1940 to present* [Data set]. Copernicus Climate Change Service (C3S) Climate Data Store. https://doi.org/10.24381/cds.bd0915c6

Hersbach, H., Bell, B., Berrisford, P., Biavati, G., Horányi, A., Muñoz Sabater, J., Nicolas, J., Peubey, C., Radu, R., Rozum, I., Schepers, D., Simmons, A., Soci, C., Dee, D., & Thépaut, J.-N. (2023). *ERA5 hourly data on single levels from 1940 to present* [Data set]. Copernicus Climate Change Service (C3S) Climate Data Store. https://doi.org/10.24381/cds.adbb2d47

Huffman, G. J., Stocker, E. F., Bolvin, D. T., Nelkin, E. J., & Tan, J. (2023). *GPM IMERG Final precipitation L3 1 day 0.1 degree x 0.1 degree V07* [Data set]. Goddard Earth Sciences Data and Information Services Center. https://doi.org/10.5067/GPM/IMERGDF/DAY/07

Huffman, G. J., Stocker, E. F., Bolvin, D. T., Nelkin, E. J., & Tan, J. (2024). *GPM IMERG Late precipitation L3 1 day 0.1 degree x 0.1 degree V07* [Data set]. Goddard Earth Sciences Data and Information Services Center. https://doi.org/10.5067/GPM/IMERGDL/DAY/07

Stöckli, R., Vermote, E., Saleous, N., Simmon, R., & Herring, D. (2005). *The Blue Marble Next Generation: A true color Earth dataset including seasonal dynamics from MODIS*. NASA Earth Observatory. https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73909/

Thinking Machines Data Science. (2024). *Project CCHAIN dataset: Open validated health, climate, environment, and socioeconomic data in 12 Philippine cities* [Data set]. Kaggle. https://doi.org/10.34740/kaggle/ds/4918229

University of the Philippines Resilience Institute & NOAH Center. (n.d.). *Project NOAH flood hazard maps (5-, 25- and 100-year return periods)* [Data set]. https://noah.up.edu.ph

WorldPop. (2018). *Global high resolution population denominators project: Unconstrained population counts 2000–2020* [Data set]. University of Southampton. https://doi.org/10.5258/SOTON/WP00647
