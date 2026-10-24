# Shared paths and helpers for the LeapTo stat-modelling pipeline.
# Run every numbered script from the project root (the folder containing renv.lock).

suppressPackageStartupMessages({
  library(data.table)
})

PATHS <- list(
  raw        = "data/raw",
  raw2       = "data/raw",       # was "raw datasets"; all raw files now live in data/raw
  processed  = "data/processed",
  out        = "output"
)
for (p in c(PATHS$processed, PATHS$out)) dir.create(p, showWarnings = FALSE, recursive = TRUE)

# Climate file can be the original CSV or a gzipped copy (used when transferring the 544 MB file).
climate_file <- function() {
  f <- file.path(PATHS$raw, "climate_atmosphere.csv")
  if (file.exists(f)) return(f)
  g <- paste0(f, ".gz")
  if (file.exists(g)) return(g)
  stop("climate_atmosphere.csv not found in data/raw")
}

# Short display names for the 12 cities
CITY_SHORT <- c(
  "Dagupan City" = "Dagupan", "Palayan City" = "Palayan", "Legazpi City" = "Legazpi",
  "Iloilo City" = "Iloilo", "Mandaue City" = "Mandaue", "Tacloban City" = "Tacloban",
  "Zamboanga City" = "Zamboanga", "Cagayan de Oro City" = "Cagayan de Oro",
  "Davao City" = "Davao", "City of Mandaluyong" = "Mandaluyong",
  "City of Navotas" = "Navotas", "City of Muntinlupa" = "Muntinlupa"
)

# PIDSR diseases reported for the full 2008-2022 window (rotavirus and chikungunya start later)
CORE_DISEASES <- c("ACUTE BLOODY DIARRHEA", "CHOLERA", "DENGUE FEVER", "HEPATITIS A",
                   "LEPTOSPIROSIS", "RABIES", "TYPHOID FEVER")

# Run-length helper: length of the run each element belongs to
run_length_of <- function(x) {
  r <- rle(x)
  rep(r$lengths, r$lengths)
}

log_step <- function(...) cat(format(Sys.time(), "%H:%M:%S"), "|", ..., "\n")

# ---- DOH morbidity-week calendar -------------------------------------------------
# Rules confirmed from DOH/EB weekly surveillance reports (2012, 2013, 2017, 2018, 2019, 2022):
#   * morbidity weeks (MW) run Sunday-Saturday; every year has exactly 52 MWs
#   * MW1 starts on 1 January and ends on the first Saturday; if that stretch is shorter
#     than `min_first_days` it is folded into the following week
#     (confirmed: 2019 kept a 5-day MW1, Jan 1-5; 2022 folded a 1-day stretch, MW1 = Jan 1-8)
#   * MW52 ends on 31 December and absorbs any leftover days (2012 MW52 = Dec 23-31)
# The cut-off between 2 and 4 days is NOT confirmed; min_first_days = 4 is the primary
# assumption (ISO-like), min_first_days = 2 is the alternative (only a 1-day stretch folds).
doh_mw_calendar <- function(years, min_first_days = 4L) {
  rbindlist(lapply(years, function(y) {
    jan1  <- as.IDate(sprintf("%d-01-01", y)); dec31 <- as.IDate(sprintf("%d-12-31", y))
    first_len <- 8L - wday(jan1)                      # days from Jan 1 to first Saturday (Sun=1)
    e1 <- jan1 + first_len - 1L
    if (first_len < min_first_days) e1 <- e1 + 7L
    starts <- c(jan1, e1 + 1L + 7L * (0:50))
    ends   <- c(e1, starts[2:51] + 6L, dec31)
    data.table(year = y, mw = 1:52, start = starts, end = ends)
  }))[, days := as.integer(end - start) + 1L][]
}

# Calendar implied by the dates as delivered in disease_pidsr_totals.csv: row N of year Y is
# dated the Monday after the Nth Sunday of Y. Taking each date - 1 (a Sunday) as the start
# gives continuous 7-day Sunday-Saturday weeks; 53-Sunday years leave one unlabelled week.
delivered_calendar <- function(years) {
  first_sun <- function(y) { j <- as.IDate(sprintf("%d-01-01", y)); j + (8L - wday(j)) %% 7L }
  lab <- rbindlist(lapply(years, function(y)
    data.table(year = y, mw = 1:52, start = first_sun(y) + 7L * (0:51))))
  grid <- data.table(start = seq(first_sun(min(years)), first_sun(max(years)) + 7L * 51L, by = 7L))
  cal <- merge(grid, lab, by = "start", all.x = TRUE)
  cal[, `:=`(end = start + 6L, days = 7L)]
  setcolorder(cal, c("year", "mw", "start", "end", "days"))[]
}
