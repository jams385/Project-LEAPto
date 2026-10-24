"""Single source of truth for LEAPto's alert levels, paths and display constants.

Every cut-off, level wording, colour and file path the app or src/ uses is
defined here. The Watch/Warning cut-offs and the track-record numbers are
placeholders: the modeling team's level_metrics.csv overrides them when present
(src/contract.level_cutoffs, src/views.level_descriptions).
"""

from pathlib import Path

# PATHS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# The app folder (the one holding this file, data/, src/, tests/ and scripts/). Every
# path below is built from it, never from the working directory. This folder is also
# the `app` package, so its parent must be on sys.path (the entry points add it).
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
MODEL_OUTPUTS_DIR = DATA_DIR / "model_outputs"



# MODEL OUTPUTS, CONTRACT V2 (docs/DATA_CONTRACT.md) ++++++++++++++++++++++++++

# Part name -> file in MODEL_OUTPUTS_DIR. Placeholders from
# scripts/make_baseline_forecast.py use the same name + `_baseline`.
CONTRACT_FILES = {
    "alerts": "alerts.csv",
    "level_metrics": "level_metrics.csv",
    "auc": "auc.csv",
    "rain_imerg": "rain_weekly_imerg.csv",
    "lag_response": "lag_response.csv",
    "reporting_flags": "reporting_flags.csv",
    "thresholds_app": "thresholds_2023_for_app.csv",
    # Added to the SPEC_V2 list: full-history observed cases and thresholds,
    # so the charts and Replay never need the raw CCHAIN CSVs.
    "cases": "cases_weekly.csv",
    "thresholds_history": "thresholds_weekly.csv",
    # Added for DESIGN_V3: per-city test AUC and outbreak-week count, which
    # decide each city's confidence group (see CITY CONFIDENCE below).
    "city_confidence": "city_confidence.csv",
    # Added for Replay: the modeling team's stage 6 "as of then" forecasts.
    "replay": "replay_weekly.csv",
    # Added for Data reliability: how outbreaks started, and what rain adds.
    "episodes": "episodes.csv",
    "rain_gain": "rain_gain.csv",
}
# Shown in the data-source list and banners.
CONTRACT_LABELS = {
    "alerts": "Alert forecasts",
    "level_metrics": "Track record by level",
    "auc": "AUC comparison",
    "rain_imerg": "IMERG rainfall",
    "lag_response": "Rain lag-response curve",
    "reporting_flags": "Reporting flags",
    "thresholds_app": "Epidemic thresholds (2023)",
    "cases": "Reported cases",
    "thresholds_history": "Epidemic thresholds (2011-2022)",
    "city_confidence": "Confidence per city",
    "replay": "Replay forecasts (case studies)",
    "episodes": "How outbreaks started",
    "rain_gain": "What rain adds to the forecast",
}
# Parts that get a labelled placeholder from the baseline script when missing.
BASELINE_PARTS = ("alerts", "level_metrics", "auc", "reporting_flags")
BASELINE_BANNER = "Baseline, model pending"

# The modeling team set Watch/Warning cut-offs for 1 and 2 weeks ahead only
# (stage 5d), so alerts.csv carries these horizons.
ALERT_HORIZONS = (1, 2)
REPORTING_FLAGS = ("non_reporting", "low_reporting_year")
# auc.csv must compare these two; other model names are allowed and kept.
AUC_REQUIRED_MODELS = ("last_week_only", "final_model")
# auc.csv `scope`: AUC over all city-weeks pooled, or averaged within each city
# (the modeling team's headline figure). Missing scope means "all weeks".
AUC_SCOPES = ("all weeks", "within city")


# ALERT LEVELS (SPEC_V2 §2) ++++++++++++++++++++++++++++++++++++++++++++++++++

# Forecast levels, lowest first. Case signal only / No report are display states.
ALERT_LEVELS = ("Normal", "Watch", "Warning")
# Cities with too few cases to forecast (DESIGN_V3): the weekly case count is
# the signal instead of a level. Which cities: see CITY CONFIDENCE below.
CASE_SIGNAL_LEVEL = "Case signal only"
NO_REPORT_LEVEL = "No report"
# Shown where alerts.csv has no row (outside the model's 2014-2022 forecasts).
NO_FORECAST_LEVEL = "No forecast"
ALL_LEVELS = ALERT_LEVELS + (CASE_SIGNAL_LEVEL, NO_REPORT_LEVEL)
# Lowest outbreak_prob for each level, used ONLY when alerts.csv leaves
# alert_level empty (the baseline placeholder). The modeling team's alerts
# carry their own levels (LEVEL_RULE_TEXT); a level_metrics.csv with
# prob_cutoff also overrides these.
LEVEL_CUTOFFS = {"Watch": 0.10, "Warning": 0.20}
# How the modeling team sets the levels (their R/05d_risk_levels.R, version V1):
# Warning = the top 5% of the training years' forecasts (95th percentile), Watch
# = the next 15% (80th percentile), re-set each test year, one cut-off for all.
LEVEL_RULE_WARNING_PCT = 5
LEVEL_RULE_WATCH_PCT = 15
LEVEL_RULE_TEXT = (f"Warning = a forecast chance in the top {LEVEL_RULE_WARNING_PCT}% of the "
                   f"forecasts for the training years, Watch = the next {LEVEL_RULE_WATCH_PCT}%. "
                   "The cut-offs are set again for each year from earlier years only, one "
                   "cut-off for all cities")
LEVEL_COLORS = {
    "Warning": "#E04848",
    "Watch": "#F2994A",
    "Normal": "#3BAA5C",
    CASE_SIGNAL_LEVEL: "#6B7A90",
    NO_REPORT_LEVEL: "#6B7A90",
    NO_FORECAST_LEVEL: "#4A5868",
}
# Display order, most urgent first (legend, city list).
DISPLAY_LEVELS = ("Warning", "Watch", "Normal", CASE_SIGNAL_LEVEL, NO_REPORT_LEVEL,
                  NO_FORECAST_LEVEL)

# Sentence shown under each level. {lift} is "about N×" from the track record.
LEVEL_MEANINGS = {
    "Warning": "Outbreak week is about {lift} as likely as usual. Act now.",
    "Watch": "Risk is raised, about {lift} a usual week. Prepare and monitor.",
    "Normal": "Risk is at or below the usual level for this time of year.",
    CASE_SIGNAL_LEVEL: "Too few cases here to forecast a level. Watch the weekly case "
                       "count instead.",
    NO_REPORT_LEVEL: "This week was flagged as non-reporting.",
    NO_FORECAST_LEVEL: ("No forecast for this week: forecasts cover 2014–2022, and a week "
                        "with no outbreak line has none."),
}
# PLACEHOLDER track record (SPEC_V2 §2 table), used only when no
# level_metrics.csv exists at all; any level_metrics.csv overrides it.
LEVEL_TRACK_RECORD = {
    "Warning": {"hit_rate": 0.44, "lift": 6.0},
    "Watch": {"hit_rate": 0.17, "lift": 2.5},
    "Normal": {"hit_rate": None, "lift": None},
}
BASE_RATE = 0.068  # share of city-weeks that are outbreak weeks (SPEC_V2 §1)
LEVEL_TRACK_TEXT = "In testing, {hit} of {level} weeks became outbreak weeks."
# rr_vs_usual above this is shown as "over N× usual risk".
MAX_RR_SHOWN = 10

# CITY PANEL: rain -> risk timeline (SPEC_V2 §4B)
TIMELINE_WEEKS_BACK = 10
# A city's "heavy-rain week" = its wettest 5% of weeks (the modeling team's P95).
HEAVY_RAIN_QUANTILE = 0.95
# Used when lag_response.csv is missing (numbers from the modeling team, Stage 3).
LAG_CAPTION_FALLBACK = ("Heavy rain raises risk +41% the next week and peaks about 2 "
                        "weeks later.")
PEAK_CAPTION_FALLBACK = "Risk usually peaks 2 weeks after heavy rain."
# Weeks after heavy rain with raised risk, when lag_response.csv is missing
# (the modeling team's Stage 3: raised in weeks 1-5, normal by week 6).
LAG_WINDOW_FALLBACK = (1, 5)


# REASONS ("What we're seeing", app/logic/reasons.py) ++++++++++++++++++++++++

# Heavy rain: a week 1 or 2 weeks before the forecast week with at least this
# many times the city's usual rain for that week of the year, and at least
# this many mm (so 4 mm vs a usual 1 mm never counts).
REASON_HEAVY_RAIN_RATIO = 2.0
REASON_HEAVY_RAIN_MIN_MM = 50.0
# Cases: last week's reported cases at or above this share of the outbreak line.
REASON_CASES_NEAR_SHARE = 0.75
# Flood: the city's most flood-prone barangay has at least this share (%) of
# its area at high flood hazard (city-wide shares are only 2-17%).
REASON_FLOOD_BRGY_PCT = 40.0
# Seasonal pattern: morbidity weeks either side of the forecast week.
REASON_SEASON_WINDOW_WEEKS = 1


# OVERVIEW + CITY DRAWER (docs/DESIGN_V3.md §1) ++++++++++++++++++++++++++++++

PAGES = ("Overview", "Replay", "Data reliability")
PRIORITY_LEVELS = ("Warning", "Watch")
OVERVIEW_TITLE = "Leptospirosis risk after rainfall"
MAP_HEIGHT_OVERVIEW_PX = 640
MAP_HINT = "Click a city to see its details"
# Columns: [map, city list]; with a city open: [map, drawer, city list].
LAYOUT_OVERVIEW = [2.1, 1]
LAYOUT_OVERVIEW_DRAWER = [1.3, 1.25, 0.9]
DRAWER_PAST_WEEKS = 6        # rain bars in the drawer's mini chart
DRAWER_ACTIONS = 3           # "Do now"
DRAWER_BARANGAYS = 3         # "Focus barangays"
# Reports arrive about a week late: at a forecast made for the week starting
# on the origin, rain is known to the end of last week, but reported cases
# only to the end of the week before (the model uses the same delay).
CASES_REPORT_DELAY_WEEKS = 1


# CITY CONFIDENCE (city_confidence.csv, from the modeling team's stage 7) ++++++

# Groups, decided from data by src.views.confidence_groups:
#   case_signal  fewer than CASE_SIGNAL_MAX_OUTBREAK_WEEKS outbreak weeks in
#                the 2014-2022 test, too few to forecast a level
#   lower        test AUC below LOWER_CONFIDENCE_AUC (the model ranks
#                outbreak weeks less well there)
#   standard     everything else
CASE_SIGNAL_MAX_OUTBREAK_WEEKS = 5
LOWER_CONFIDENCE_AUC = 0.70  # kept at 0.70 (user, 2026-10-24): Zamboanga's 0.704 is standard
CONFIDENCE_GROUPS = ("standard", "lower", "case_signal")
# Note under the city name (province, then the note) in the list and drawer.
CONFIDENCE_NOTES = {
    "standard": "standard confidence",
    "lower": "lower confidence",
    "case_signal": "too few cases to forecast",
}
# Used ONLY when city_confidence.csv is missing: the groups the same rules
# give on the final model's per-city test (stage 5 washi_by_city.csv), so the
# app still runs.
CONFIDENCE_FALLBACK = {
    "PH104305000": "lower",        # Cagayan de Oro City, AUC 0.62
    "PH083747000": "lower",        # Tacloban City, AUC 0.68
    "PH034919000": "case_signal",  # Palayan City, 1 outbreak week
    "PH050506000": "case_signal",  # Legazpi City, 3 outbreak weeks
    "PH072230000": "case_signal",  # Mandaue City, 3 outbreak weeks
}


# ANALYSIS IMPORT (scripts/import_analysis_outputs.py) ++++++++++++++++++++++++

# The modeling team's R project, next to this folder; override with env var LEAPTO_ANALYSIS_DIR.
ANALYSIS_DIR_ENV = "LEAPTO_ANALYSIS_DIR"
ANALYSIS_DIR_DEFAULT = ROOT.parent / "analysis"
# The final forecasting model (report, "Final model and app settings"): rain
# + recent level + case history, Typhoon Washi's weeks set aside in training,
# IMERG Late rain, 1-week reporting delay (stage 5e, forecasts_washi.csv.gz).
ANALYSIS_ALERT_VARIANT = "pooled_ar4_lvl_nw"
# Their risk-level version (stage 5d): "V1" = one cut-off for all cities (adopted).
ANALYSIS_LEVEL_VERSION = "V1"
# Variant used as "usual for this time of year" in rr_vs_usual (placeholder
# definition: outbreak_prob / seasonal-only outbreak_prob, same week).
ANALYSIS_USUAL_VARIANT = "seasonal"
# Their variant names -> auc.csv model names.
ANALYSIS_AUC_MODELS = {
    "pooled_ar4_lvl_nw": "final_model",
    "pooled": "rain_only",
    "seasonal": "seasonal_only",
}
# IMERG Final is the shown rainfall (SPEC_V2 §1); Late is kept as an extra column.
ANALYSIS_RAIN_COLUMN = "pr_week_imf"
ANALYSIS_RAIN_LATE_COLUMN = "pr_week_iml"
# Their city names (no pcode in their stage 4/5 files) -> adm3_pcode.
ANALYSIS_CITY_PCODES = {
    "Iloilo": "PH063022000",
    "Cagayan de Oro": "PH104305000",
    "Davao": "PH112402000",
    "Zamboanga": "PH097332000",
    "Dagupan": "PH015518000",
    "Navotas": "PH137503000",
    "Muntinlupa": "PH137603000",
    "Mandaluyong": "PH137401000",
    "Tacloban": "PH083747000",
    "Palayan": "PH034919000",
    "Legazpi": "PH050506000",
    "Mandaue": "PH072230000",
}


# EPIDEMIC THRESHOLDS (DOH method, app-side FALLBACK) ++++++++++++++++++++++++

# The modeling team's thresholds are used whenever they exist. The app's own
# computation below runs only when they are missing (with a visible warning).
# Same morbidity week in the previous N years; use as few as MIN when early
# in the record. Fewer than MIN usable years -> no threshold.
THRESHOLD_LOOKBACK_YEARS = 5
THRESHOLD_MIN_YEARS = 3
ALERT_SD = 1.0       # alert threshold    = seasonal mean + 1 SD
EPIDEMIC_SD = 2.0    # epidemic threshold = seasonal mean + 2 SD
SD_DDOF = 1          # sample standard deviation
# MW53 exists only in 2008/2014/2020 and has no history; compare it to MW52.
MW53_FALLBACK_WEEK = 52

# FORECASTS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

# model_version of the placeholder alerts_baseline.csv.
BASELINE_ALERTS_VERSION = "PLACEHOLDER baseline-seasonal-v0 (no rainfall)"
# The placeholder needs this many prior years of the same MW to give a chance.
BASELINE_MIN_YEARS = 3
# Its seasonal chance pools the target MW +/- this many weeks across prior years.
BASELINE_WINDOW_WEEKS = 1


# DASHBOARD ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

STATIC_DIR = ROOT / "static"
# Files the app cannot start without, all committed to the repository (path from
# the project root -> what to do when it is missing). Everything else under
# data/ has a labelled fallback or hides its section, so it is not listed here.
_RESTORE = "Restore it from the repository; it is a committed app file."
_REBUILD = ("Restore it from the repository, or rebuild it with "
            "`python scripts/build_processed.py` (needs `pip install -r requirements-dev.txt` "
            "and the raw Project CCHAIN CSVs in data/raw/).")
RUNTIME_FILES = {
    "data/processed/cities.parquet": _REBUILD,
    "data/processed/hazard_city.parquet": _REBUILD,
    "data/processed/cities.geojson": _REBUILD,
    **{f"static/{name}": _RESTORE for name in (
        "style.css", "logo.png", "mark.png", "bg_satellite.jpg", "waves.svg",
        "icon_bell.svg", "icon_chart.svg", "icon_shield.svg")},
}
DEFAULT_ROLE = "Resident"
# First screen: a real week with Warning cities, the start of Navotas's main
# July 2018 outbreak (Navotas and two other cities at Warning next week).
DEFAULT_ORIGIN = "2018-07-08"
ROLES = ("Resident", "Health office")
# Horizons on the toggle (DESIGN_V3 conflict 1). Must be a subset of
# ALERT_HORIZONS: the modeling team's levels exist for 1 and 2 weeks ahead.
HORIZONS = (1, 2)
HORIZON_NAMES = {1: "Next week", 2: "In 2 weeks", 3: "In 3 weeks"}
FORECAST_SCOPE_NOTE = "Forecast for the next 1–2 weeks"
# Always-visible honesty note and the data period behind every number.
HONESTY_NOTE = "Forecast, not confirmed cases"
DATA_PERIOD = "Data 2008–2022"

# DATA RELIABILITY (DESIGN_V3 §3) ++++++++++++++++++++++++++++++++++++++++++++

RELIABILITY_BAR_MAX = 0.5          # the bars run 0-50% of weeks (DESIGN_V3)
# Weeks forecast at or above this chance are checked against what happened.
RELIABILITY_CALIBRATION_FROM = 0.5
PENDING_TEXT = "pending"           # shown where a number has no data source yet
REPLAY_EVENT_WASHI = "washi"       # the replay event for "cannot foresee a sudden flood"

# REPLAY (DESIGN_V3 §2) +++++++++++++++++++++++++++++++++++++++++++++++++++++

# Seasons in dropdown order (first = default). `event` is the name in
# replay_weekly.csv; `from`/`to` are the first and last forecast week shown
# (Sundays). `flood_alert` adds a link to the Flood alert for sudden floods.
REPLAY_SEASONS = (
    {"event": "navotas", "label": "Navotas, Jun–Aug 2018", "title": "Navotas, June–August 2018",
     "city": "PH137503000", "from": "2018-06-03", "to": "2018-08-26"},
    {"event": "washi", "label": "Cagayan de Oro, Dec 2011 (Typhoon Washi)",
     "title": "Cagayan de Oro, December 2011 (Typhoon Washi)", "city": "PH104305000",
     "from": "2011-11-06", "to": "2012-02-26", "flood_alert": True},
    {"event": "iloilo", "label": "Iloilo City, 2011–2012", "title": "Iloilo City, 2011–2012",
     "city": "PH063022000", "from": "2011-01-02", "to": "2012-12-23"},
)
REPLAY_SUBTITLE = ("Each week shows only what the model could have known at the time. It was "
                   "trained on earlier years only.")
REPLAY_PANEL_WEEKS = 12           # weeks shown at once in the three panels
REPLAY_PLAY_SECONDS = 1.0         # one step per second while playing
REPLAY_HEAVY_RAIN_MM = 250        # darker rain bar at or above this (DESIGN_V3)
REPLAY_HORIZON = 1                # the forecast shown on the panels: next week
# A Watch/Warning that had already been on for MORE than this many weeks
# without an outbreak (false-alarm weeks just before) is background, not a
# warning of the outbreak; no lead time is claimed for it.
REPLAY_BACKGROUND_FLAG_WEEKS = 2
# "What happened" adds a size note only when one outbreak run holds at least
# this share of the city's cases over the whole record.
REPLAY_SIZE_NOTE_MIN_SHARE = 0.5
# Dot colours of the "What happened" entries.
REPLAY_DOT_COLORS = {"rain": "#4FB3E6", "above": "#E04848", "largest": "#E04848", "alert": "#F2994A",
                     "warning": "#E04848", "peak_forecast": "#F2994A", "peak_cases": "#E04848",
                     "size": "#6B7A90"}
# Before 2014 only a 3-year outbreak line exists (the model's test years are
# 2014-2022); the Replay says so for these events.
REPLAY_THREE_YEAR_EVENTS = ("washi", "iloilo")

# FLOOD ALERT (modeling report, stage 6) ++++++++++++++++++++++++++++++++++++
# Switched on by a health office after a major flood; shown beside the level
# (the forecast level itself never changes). Lasts this many weeks from the
# selected forecast week; kept in the session only.
FLOOD_ALERT_WEEKS = 4
FLOOD_ALERT_ROLE = "Health office"

# Cities flagged at Watch so often that Watch is background there (modeling
# report, stage 5d: Davao). The drawer adds DESIGN line WATCH_BACKGROUND_TEXT.
WATCH_BACKGROUND_CITIES = frozenset({"PH112402000"})  # Davao City
WATCH_BACKGROUND_TEXT = ("{city} is at Watch about {n} weeks a year, so treat Watch here as "
                         "background and act on Warning.")

ISLAND_GROUPS = ("Luzon", "Visayas", "Mindanao")
REGION_TO_ISLAND_GROUP = {
    "Region I": "Luzon", "Region III": "Luzon", "Region V": "Luzon",
    "National Capital Region": "Luzon",
    "Region VI": "Visayas", "Region VII": "Visayas", "Region VIII": "Visayas",
    "Region IX": "Mindanao", "Region X": "Mindanao", "Region XI": "Mindanao",
}


# EXTRA INFO SECTIONS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# Collapsed expanders: a clear title, then a one-line plain description in grey
# (Streamlit colour directive). The title always comes first.
COMPARE_LABEL = ("Compare all cities  :gray[A chart and a table of every city's numbers "
                 "side by side]")
RELIABILITY_MORE_LABEL = ("More details  :gray[Technical tables, the rain-to-risk curve and "
                          "the data rules]")


# MAP ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

MAP_LAYERS = ("Risk", "Rainfall", "Flood hazard")
# The only basemap: Esri World Imagery (satellite), raster tiles, no API key.
# Esri requires the attribution, which the map shows. MAP_INK is the colour of
# city labels and outlines, and MAP_HALO the thin ring under every city marker,
# chosen so the level colours stay readable on imagery.
BASEMAP_URL = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
               "World_Imagery/MapServer/tile/{z}/{y}/{x}")
BASEMAP_ATTRIBUTION = "Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community"
MAP_INK = "#FFFFFF"
MAP_HALO = "#0B1E33"
MAP_SELECTED_RING_EXTRA = 10  # px added to the open city's marker for its neutral outline
MAP_HEIGHT_PX = 625
MAP_MARKER_SIZE = 16  # px; every city the same size (no predicted-case scaling)
# Quick views (buttons over the map). "Philippines" is the default overview.
MAP_VIEWS = {
    "Philippines": {"lat": 11.5, "lon": 122.6, "zoom": 5.15},
    "Luzon": {"lat": 15.6, "lon": 121.3, "zoom": 6.4},
    "Visayas": {"lat": 10.9, "lon": 123.7, "zoom": 6.75},
    "Mindanao": {"lat": 8.0, "lon": 124.6, "zoom": 6.5},
}
DEFAULT_MAP_VIEW = "Philippines"
# The map cannot be panned or zoomed out past this box. It is the Philippines
# plus the side margin the wide map needs to show the whole country at once
# (a tighter box would force-zoom the overview in).
MAP_BOUNDS = {"west": 105.0, "east": 140.0, "south": -1.0, "north": 25.0}
MAP_MAX_CITY_ZOOM = 11.5
# Project NOAH column used for "% high flood-hazard area" (100-year flood).
FLOOD_HAZARD_COLUMN = "pct_area_flood_hazard_100yr_high"
# Barangays ranked by that column (scripts/build_processed.py, committed).
FLOOD_RANK_FILE = "brgy_flood_rank.csv"
TOP_FLOOD_BARANGAYS = 5
# Map colour ramps for the Rainfall and Flood hazard layers (Risk uses LEVEL_COLORS).
RAINFALL_COLORSCALE = [[0, "#16324F"], [0.5, "#2F80C0"], [1, "#8FD3FF"]]
FLOOD_COLORSCALE = [[0, "#1B2F45"], [0.5, "#4C7FA8"], [1, "#9ED0F0"]]
