# LEAPto

LEAPto is a dashboard that gives 12 Philippine cities a leptospirosis alert level for the next
week and the week after, from satellite rainfall and past reported cases.
It is for city and regional health officers, who get suggested actions, and for residents, who
get a simple view of their city's risk.

## What the app shows

**Overview.** The map and a list, "All covered cities", show every city's alert level for the
chosen forecast week ("Next week" or "In 2 weeks"). The week can be stepped with the arrows or
picked from a date box. Clicking a city, on the map or in the list, opens a drawer with what the
level means in plain words, last week's rain against the city's usual, the cases reported in the
latest week against the city's outbreak line, a small rain-and-risk chart, the barangays with the
most high flood-hazard area, and a short list of suggested actions for a resident or a health
office. A health-office user can switch on a Flood alert for a city (session only), which adds
flood actions without changing the level. The map can also colour the city areas by last week's
rain or by flood hazard. A collapsed section, "Compare all cities", has a chart and a table.
Every date shown is a past week from the data, never today, and the note "Forecast, not
confirmed cases" is always visible.

| Level | Meaning |
|---|---|
| Warning | The week's chance of being an outbreak week is in the top 5% of the forecasts for the training years. Act now. |
| Watch | The next 15%. Risk is raised; prepare and monitor. |
| Normal | At or below the usual level for this time of year. |
| Case signal only | Too few outbreak weeks in testing to forecast a level (fewer than 5). The weekly case count is shown instead. |
| No report | The week was flagged as non-reporting. |

An outbreak week is a week with reported cases above the city's DOH epidemic threshold.

**Replay.** Pick an outbreak event (Navotas, June to August 2018; Cagayan de Oro, December 2011,
Typhoon Washi; Iloilo, 2011 to 2012) and play or step through it week by week. Three aligned
panels show NASA IMERG rain, reported cases (weeks above the outbreak line are marked) and the
level the app would have shown. Each week uses only forecasts made before that week. A "What
happened" box lists the heaviest rain, the first week above the outbreak line, the first rise to
Watch or Warning and the lead time over case reports, all computed from the data. Misses are
shown as misses.

**Data reliability.** Answers "How reliable is this?" with numbers from the testing years
(2014 to 2022): the share of weeks at each level that became outbreak weeks, a short list of
what the app cannot do, the data sources and the references. Under "More details" are the
technical tables, the rain-to-risk curve and the data rules. A number whose data is missing
reads "pending".

## Quick start

Python 3.10 (the pinned packages were tested on 3.10.7). Run every command in this README from
the app folder (`cd app` from the repository root).

**macOS / Linux**

```bash
cd app
python3 -m venv .venv          
source .venv/bin/activate
pip install -r requirements.txt
streamlit run main.py              
```

**Windows (PowerShell)**

```powershell
cd app
py -3.10 -m venv .venv      
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run main.py              
```

If PowerShell says "running scripts is disabled on this system" at the activate step, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, answer `Y`, and activate again. In
Command Prompt (cmd), activate with `.venv\Scripts\activate.bat` instead.

Once the environment is active, plain `python` and `pip` point to it on every system.

If you use **pyenv**: `.python-version` in this folder pins 3.10.7, so any `python` command here
fails with "version '3.10.7' is not installed" until you run `pyenv install 3.10.7` (or pick
another 3.10 for this shell with `pyenv shell 3.10`).

On the landing page click **Explore demo without an account**. Sign-in is demo-only: any email
and password work and nothing is stored.

To run the tests, with the environment from above active:

```bash
cd app
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite passes without the analysis folder; the two tests that compare against the modeling
team's own files skip when `../analysis` is absent.

On Windows, keep the folder path short. A very deep path makes `pyarrow` fail to load
("filename or extension is too long").

## Data

Everything the app reads is committed, in `data/processed/` and `data/model_outputs/`. It needs no
raw files, no analysis folder, no credentials and no network apart from the map tiles.

| Data | Source | In the app |
|---|---|---|
| Weekly reported leptospirosis cases, 12 cities, Dec 30, 2007 to Dec 25, 2022 | DOH PIDSR, via Project CCHAIN | `data/model_outputs/cases_weekly.csv` |
| Rainfall, weekly | NASA IMERG (Final, and Late as the model used it), supplied with the model results | `rain_weekly_imerg.csv` |
| Flood hazard (100-year, high) per city and 879 ranked barangays | Project NOAH | `data/processed/hazard_city.parquet`, `brgy_flood_rank.csv` |
| Population (2020 carried forward to 2021 and 2022) | WorldPop | `data/processed/pop_yearly.parquet` |
| City shapes and names | Project CCHAIN | `cities.geojson`, `cities.parquet` |

The data period is 2008 to 2022. Forecast weeks run from Dec 29, 2013 to Dec 25, 2022, the
years the model was tested on. The weeks are DOH morbidity weeks (Sunday to Saturday).

**How the model results reach the app.** The alert levels, chances, track record and replay
forecasts come from the modeling team's analysis project. The app never fits a model. A
development step, `scripts/import_analysis_outputs.py`, reads that project (read-only; set
`LEAPTO_ANALYSIS_DIR` to its path) and writes the files in `data/model_outputs/`, which are
committed. People who only run the app never need this step. The default analysis folder is
`../analysis`, next to the app folder:

```bash
cd app
python scripts/import_analysis_outputs.py    # analysis outputs -> data/model_outputs/
```

If a `data/model_outputs/` file is missing or invalid, the app falls back to a labelled
placeholder ("Baseline, model pending") or its own pipeline and says so on screen. If a file the
app cannot start without is missing, it names the file and the command to get it back.

## How alert levels work

The levels are the modeling team's. For each week the model gives the chance that the week is an
outbreak week; the cut-offs turn that chance into a level, are set again for each test year from
earlier years only, and are one set for all cities. `alerts.csv` carries the level for every
city-week, and the app shows it. In testing (1 week ahead, 5,372 city-weeks) 42% of Warning
weeks, 16% of Watch weeks and 2.5% of Normal weeks became outbreak weeks, against 6.9% of all
weeks (`level_metrics.csv`).

Cities are grouped from `city_confidence.csv`. Palayan, Legazpi and Mandaue had fewer than 5
outbreak weeks in testing and show "Case signal only". Cagayan de Oro and Tacloban are marked
"lower confidence" (test AUC below 0.70).

Common changes:

| To change | Edit (paths relative to this folder) |
|---|---|
| Level colours, level wording, cut-off text, the groups' thresholds | `config.py`: `LEVEL_COLORS`, `LEVEL_MEANINGS`, `LEVEL_RULE_TEXT`, `CASE_SIGNAL_MAX_OUTBREAK_WEEKS`, `LOWER_CONFIDENCE_AUC` |
| The week the app opens on | `config.py`: `DEFAULT_ORIGIN` (a Sunday between Dec 22, 2013 and Dec 25, 2022) |
| Page title, note texts, map colours and views | `config.py`: `OVERVIEW_TITLE`, `HONESTY_NOTE`, `MAP_VIEWS`, `RAINFALL_COLORSCALE`, `FLOOD_COLORSCALE` |
| Suggested actions | `content/actions.py` |
| Data reliability and Replay wording | `content/reliability_text.py`, `content/replay_text.py` |
| Look and feel | `static/style.css`, `.streamlit/config.toml` |

To change which levels the modeling team's model produces, change the analysis project and
re-import; the app only reads the result. Restart the app after editing `style.css`, because it
is read once per server process.

## Project structure

```
app/                     (this folder; run every command from here)
  main.py                entry point: landing, loading, then the three tabs
  config.py              every setting: levels, colours, wording, defaults, file lists
  data.py                cached loaders for the committed files
  state.py               session state and the share-link address parameters
  components/            one file per screen part: overview, city_details, city_map, legend,
                         replay, reliability, all_cities, header, auth, hover, ui ...
  content/               plain-language text: actions, reliability_text, replay_text, references
  logic/reasons.py       the "reasons seen in the data" lines in the city drawer
  static/                style.css, logo, icons, landing background
  src/                   tested functions with no screen code: weeks, views, replay,
                         reliability, contract (the data contract), load_outputs, import_analysis
  scripts/               import_analysis_outputs.py, build_processed.py (needs requirements-dev.txt),
                         make_baseline_forecast.py, make_static_svgs.py
  data/
    processed/           city shapes, hazard, flood ranking, fallback tables
    model_outputs/       the 13 files the app reads from the modeling team's results
  tests/                 unit tests and an app-level smoke test (Streamlit AppTest)
  docs/                  DATA_CONTRACT.md (file formats), DESIGN_V3.md, DEMO_SCRIPT.md and other notes
  design/                design mock-ups
  .streamlit/config.toml theme and server settings
  run.sh                 optional runner: data, import, baseline, app, test
  requirements.txt       runtime packages, pinned
  requirements-dev.txt   tests and data-build tools, pinned
```

## Limitations

- **Reported cases, not infections.** Surveillance counts only cases that reached a health
  facility and were reported, so every number is a lower bound.
- **Reporting lag.** Reports arrive about a week late, so the latest cases shown are from a
  week before the forecast week. The model uses the same delay.
- **Past data only.** Cases run to 2022 and forecasts cover 2014 to 2022. The app is a replay of
  those years, not a live service.
- **One to two weeks ahead.** Levels exist for the next week and the week after, not further.
- **Satellite rain misses extremes.** Weekly NASA IMERG rain at about 10 km cannot capture a
  disaster-scale flood. It was chosen over CHIRPS because CHIRPS missed Typhoon Washi (2011).
  In the Replay, the Washi event and the 2011 to 2012 Iloilo event are cases where the model
  gave no early signal for the largest outbreak. Those two events use a model trained on only
  about two years of data, so they are less certain.
- **Small cities.** Palayan, Legazpi and Mandaue show only the case count. Cagayan de Oro and
  Tacloban are less reliable. Flood hazard is one fixed snapshot.
- **Not a diagnosis.** A level describes a city-week and is linked to rainfall; it does not show
  what caused any case and says nothing about one person's risk. It never forecasts a number of
  people.

## Credits and references

Map imagery: Esri, Maxar, Earthstar Geographics (the live tiles credit it on the map as
"Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"). Landing background:
NASA Blue Marble Next Generation, public domain.

Data and imagery references (APA 7th):

- Department of Health, Epidemiology Bureau. (2023). *Philippine Integrated Disease
  Surveillance and Response (PIDSR) weekly city-level case counts, 2008–2022* [Data set].
  Compiled in Project CCHAIN.
- Esri. (n.d.). *World Imagery* [Basemap].
  https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9
- Funk, C., Peterson, P., Landsfeld, M., Pedreros, D., Verdin, J., Shukla, S., Husak, G.,
  Rowland, J., Harrison, L., Hoell, A., & Michaelsen, J. (2015). The climate hazards infrared
  precipitation with stations: A new environmental record for monitoring extremes. *Scientific
  Data, 2*, Article 150066. https://doi.org/10.1038/sdata.2015.66 (CHIRPS; used only by the
  fallback pipeline when the model results' rainfall file is missing.)
- Huffman, G. J., Stocker, E. F., Bolvin, D. T., Nelkin, E. J., & Tan, J. (2023). *GPM IMERG
  Final precipitation L3 1 day 0.1 degree x 0.1 degree V07* [Data set]. Goddard Earth Sciences
  Data and Information Services Center. https://doi.org/10.5067/GPM/IMERGDF/DAY/07
- Huffman, G. J., Stocker, E. F., Bolvin, D. T., Nelkin, E. J., & Tan, J. (2024). *GPM IMERG
  Late precipitation L3 1 day 0.1 degree x 0.1 degree V07* [Data set]. Goddard Earth Sciences
  Data and Information Services Center. https://doi.org/10.5067/GPM/IMERGDL/DAY/07
- Philippine Society for Microbiology and Infectious Diseases. (2010). *Leptospirosis: Clinical
  practice guidelines*. (Basis for the wording of the suggested actions in
  `content/actions.py`.)
- Stöckli, R., Vermote, E., Saleous, N., Simmon, R., & Herring, D. (2005). *The Blue Marble Next
  Generation: A true color Earth dataset including seasonal dynamics from MODIS*. NASA Earth
  Observatory. https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73909/
- Thinking Machines Data Science. (2024). *Project CCHAIN dataset: Open validated health,
  climate, environment, and socioeconomic data in 12 Philippine cities* [Data set]. Kaggle.
  https://doi.org/10.34740/kaggle/ds/4918229
- University of the Philippines Resilience Institute & NOAH Center. (n.d.). *Project NOAH flood
  hazard maps (5-, 25- and 100-year return periods)* [Data set]. https://noah.up.edu.ph
- WorldPop. (2018). *Global high resolution population denominators project: Unconstrained
  population counts 2000–2020* [Data set]. University of Southampton.
  https://doi.org/10.5258/SOTON/WP00647
