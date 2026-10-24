# =============================================================================
# 01_build_dataset.R  —  Stage 1: build the city-week analysis dataset
#
# Inputs  : data/raw/{disease_pidsr_totals, climate_atmosphere, location, calendar}.csv
#           data/raw/worldpop_population.csv


# Also runs R/01b_add_imerg.R at the end (adds IMERG columns) when data/external/imerg exists.
# Outputs : data/processed/city_week.{csv,rds}       PRIMARY: one row per city x DOH morbidity week
#           data/processed/city_week_altA.{csv,rds}  first-week fold rule: only a 1-day stretch folds
#           data/processed/city_week_altB.{csv,rds}  PIDSR dates as delivered (date - 1 = Sunday start)
#           output/stage1/*.csv                       data-quality tables (primary version)
#
# Key choices:
#   * Rows are DOH morbidity weeks (MW, Sunday-Saturday, 52 per year, MW1 starts Jan 1, MW52 ends
#     Dec 31). Row N of each PIDSR year is taken to be MW N. See doh_mw_calendar() in _common.R.
#   * City rainfall = population-weighted mean of barangay daily CHIRPS rainfall, summed over the
#     exact MW dates. Because edge-of-year MWs are 4-14 days long, `pr_week` is expressed per
#     7 days (total / days * 7); `pr_total` keeps the raw sum. Model offset: log(pop * days / 7).
#   * Area-weighted and unweighted rainfall versions kept for sensitivity.
#   * Barangay Tumalutab (Zamboanga, PH097332095) has no CHIRPS data (island not on land
#     mask); it is dropped and the remaining weights renormalised.
#   * WorldPop ends in 2020. 2021-2022 city population is extrapolated log-linearly from
#     2016-2020 (primary); a 2020 carry-forward version is kept for sensitivity.
#   * Weekly population = annual value placed at 1 July, linearly interpolated to the MW midpoint.
# =============================================================================

source("R/_common.R")
OUT <- file.path(PATHS$out, "stage1"); dir.create(OUT, showWarnings = FALSE, recursive = TRUE)

# ---- 1. Locations -----------------------------------------------------------
loc <- fread(file.path(PATHS$raw, "location.csv"))[, .(adm3_pcode, adm3_en, adm4_pcode, brgy_area = brgy_total_area)]
loc[, city := CITY_SHORT[adm3_en]]
stopifnot(!anyNA(loc$city), uniqueN(loc$adm4_pcode) == 879)

# ---- 2. Population ----------------------------------------------------------
log_step("Population")
wp <- fread(file.path(PATHS$raw2, "worldpop_population.csv"),
            select = c("adm4_pcode", "date", "pop_count_total"))
wp[, year := year(as.IDate(date))]
wp <- merge(wp, loc[, .(adm4_pcode, adm3_pcode, city)], by = "adm4_pcode")
dq_pop_na <- wp[is.na(pop_count_total), .N, by = .(adm4_pcode, city)]

city_pop <- wp[, .(pop = sum(pop_count_total, na.rm = TRUE)), by = .(adm3_pcode, city, year)]

extrap <- city_pop[year >= 2016, {
  fit <- lm(log(pop) ~ year)
  .(year = 2021:2022, pop_loglin = exp(predict(fit, data.frame(year = 2021:2022))),
    pop_carry = pop[year == 2020])
}, by = .(adm3_pcode, city)]
city_pop_full <- rbind(
  city_pop[, .(adm3_pcode, city, year, pop_loglin = pop, pop_carry = pop, pop_source = "WorldPop")],
  extrap[, .(adm3_pcode, city, year, pop_loglin, pop_carry, pop_source = "extrapolated")]
)
setorder(city_pop_full, city, year)
fwrite(city_pop_full, file.path(OUT, "city_population_annual.csv"))

# Barangay population shares within city (used as rainfall weights); 2021-22 use 2020 shares
wp[, w_pop := pop_count_total / sum(pop_count_total, na.rm = TRUE), by = .(adm3_pcode, year)]

# ---- 3. Rainfall & temperature: barangay-day -> city-day ---------------------
log_step("Reading climate (large file)")
clim <- fread(climate_file(), select = c("adm4_pcode", "date", "pr", "tave", "rh"))
clim[, date := as.IDate(date)]
log_step("Climate rows:", nrow(clim))

dq_clim_na <- clim[, .(n_days = .N, pr_na = sum(is.na(pr)), tave_na = sum(is.na(tave))), by = adm4_pcode][pr_na > 0 | tave_na > 0]
dq_clim_na <- merge(dq_clim_na, loc[, .(adm4_pcode, city)], by = "adm4_pcode")

clim <- merge(clim, loc[, .(adm4_pcode, adm3_pcode, city, brgy_area)], by = "adm4_pcode")
clim[, year := pmin(year(date), 2020L)]
clim <- merge(clim, wp[, .(adm4_pcode, year, w_pop)], by = c("adm4_pcode", "year"), all.x = TRUE)

# weighted means that ignore barangays with missing values (renormalise weights)
wmean <- function(x, w) { ok <- !is.na(x) & !is.na(w); sum(x[ok] * w[ok]) / sum(w[ok]) }
log_step("Aggregating to city-day")
city_day <- clim[, .(
  pr_pop   = wmean(pr, w_pop),
  pr_area  = wmean(pr, brgy_area),
  pr_mean  = mean(pr, na.rm = TRUE),
  pr_brgy_max = max(pr, na.rm = TRUE),
  tave     = wmean(tave, w_pop),
  rh       = wmean(rh, w_pop)
), by = .(adm3_pcode, city, date)]
rm(clim); invisible(gc())

# ---- 4. Disease data --------------------------------------------------------
log_step("Disease data")
pidsr <- fread(file.path(PATHS$raw, "disease_pidsr_totals.csv"),
               select = c("date", "adm3_pcode", "disease_common_name", "case_total"))
pidsr[, date := as.IDate(date)]
stopifnot(all(wday(pidsr$date) == 2L))
# row N within each year = morbidity week N (52 rows per year, verified)
wk_index <- unique(pidsr[, .(date)])[order(date)][, `:=`(year = year(date), mw = seq_len(.N)), by = year(date)]
stopifnot(wk_index[, .N, by = year][, all(N == 52)])
pidsr <- merge(pidsr, wk_index, by = "date")

lepto <- pidsr[disease_common_name == "LEPTOSPIROSIS", .(adm3_pcode, year, mw, date_as_delivered = date, cases = case_total)]
core  <- pidsr[disease_common_name %in% CORE_DISEASES,
               .(core_cases = sum(case_total), dengue = sum(case_total[disease_common_name == "DENGUE FEVER"])),
               by = .(adm3_pcode, year, mw)]

pop_pts <- city_pop_full[, .(adm3_pcode, mid = as.IDate(sprintf("%d-07-01", year)), pop_loglin, pop_carry)]
interp_pop <- function(code, x, col) { p <- pop_pts[adm3_pcode == code]; approx(as.numeric(p$mid), p[[col]], xout = as.numeric(x), rule = 2)$y }

# ---- 5. Build one analysis dataset for a given week calendar ----------------
# cal: year, mw, start, end, days (contiguous periods; year/mw NA for unlabelled weeks)
build_dataset <- function(cal, version) {
  log_step("Building version:", version)
  cal <- copy(cal)[order(start)][, period := .I]
  daymap <- cal[, .(date = seq(start, end, by = 1L)), by = period]
  cd <- merge(city_day, daymap, by = "date")
  wk <- cd[, .(
    n_days_climate = .N,
    pr_total     = sum(pr_pop),
    pr_week_area = sum(pr_area) / .N * 7,
    pr_week_mean = sum(pr_mean) / .N * 7,
    pr_day_max   = max(pr_pop),          # wettest single day (city average)
    pr_brgy_max  = max(pr_brgy_max),     # wettest barangay-day
    heavy_days   = sum(pr_pop >= 50),    # days with >= 50 mm city-average rain
    tave = mean(tave), rh = mean(rh)
  ), by = .(adm3_pcode, city, period)]
  dt <- merge(wk, cal, by = "period")
  stopifnot(all(dt$n_days_climate == dt$days))   # every period fully covered by climate data
  dt[, n_days_climate := NULL]
  dt[, pr_week := pr_total / days * 7]           # primary exposure, mm per 7 days
  dt[, heavy_days_7 := heavy_days / days * 7]

  if (version == "altB") {
    lep <- lepto[, .(adm3_pcode, start = date_as_delivered - 1L, cases, date_as_delivered)]
    dt <- merge(dt, lep, by = c("adm3_pcode", "start"), all.x = TRUE)
    dt <- merge(dt, core[wk_index, on = .(year, mw)][, .(adm3_pcode, start = date - 1L, core_cases, dengue)],
                by = c("adm3_pcode", "start"), all.x = TRUE)
  } else {
    dt <- merge(dt, lepto, by = c("adm3_pcode", "year", "mw"), all.x = TRUE)
    dt <- merge(dt, core, by = c("adm3_pcode", "year", "mw"), all.x = TRUE)
  }
  setorder(dt, city, start)

  dt[, in_pidsr_period := start >= as.IDate("2008-01-01") & start <= as.IDate("2022-12-31")]
  dt[, flag_gap_week := in_pidsr_period & is.na(cases)]   # only possible in altB
  dt[, mid := start + as.integer((end - start) / 2)]
  dt[, pop := interp_pop(.BY$adm3_pcode, mid, "pop_loglin"), by = adm3_pcode]
  dt[, pop_carry := interp_pop(.BY$adm3_pcode, mid, "pop_carry"), by = adm3_pcode]
  dt[, log_offset := log(pop * days / 7)]

  # ---- Data-quality flags ----
  # (a) all seven core PIDSR diseases zero in a week -> possible non-reporting. A run of L
  #     all-zero weeks is flagged when improbable for that city: p0 = share of all-zero weeks
  #     2008-2019; flag runs with 780 * p0^L < 0.05 (L_min floored at 2).
  dt[in_pidsr_period == TRUE & !flag_gap_week, flag_all_zero := core_cases == 0]
  dt[in_pidsr_period == TRUE & !flag_gap_week, all_zero_run := run_length_of(flag_all_zero), by = city]
  dt[!is.na(flag_all_zero) & !flag_all_zero, all_zero_run := 0L]
  zero_rule <- dt[in_pidsr_period == TRUE & year <= 2019 & !is.na(flag_all_zero),
                  .(p0 = max(mean(flag_all_zero), 1 / 780)), by = city]
  zero_rule[, L_min := pmax(2L, as.integer(ceiling(log(0.05 / 780) / log(p0))))]
  dt <- merge(dt, zero_rule[, .(city, L_min)], by = "city", all.x = TRUE)
  dt[, flag_zero_run := !is.na(flag_all_zero) & flag_all_zero & all_zero_run >= L_min]

  # (b) reporting-collapse years: BOTH all core diseases < 25% of the city's median year AND
  #     non-dengue core diseases < 50% (dengue alone swings ~10x between years).
  yr_tot <- dt[in_pidsr_period == TRUE & !is.na(year), .(core_year = sum(core_cases, na.rm = TRUE),
                                          nondengue_year = sum(core_cases - dengue, na.rm = TRUE),
                                          lepto_year = sum(cases, na.rm = TRUE),
                                          dengue_year = sum(dengue, na.rm = TRUE),
                                          zero_weeks = sum(flag_all_zero, na.rm = TRUE)), by = .(city, year)]
  yr_tot[, core_rel := round(core_year / median(core_year), 2), by = city]
  yr_tot[, nondengue_rel := round(nondengue_year / median(nondengue_year), 2), by = city]
  yr_tot[, flag_low_year := core_rel < 0.25 & nondengue_rel < 0.5]
  dt <- merge(dt, yr_tot[, .(city, year, flag_low_year)], by = c("city", "year"), all.x = TRUE)

  # (c) COVID-19 period (Luzon ECQ from 16 Mar 2020; MWs starting on/after 15 Mar 2020)
  dt[, flag_covid := start >= as.IDate("2020-03-15")]

  # Default modelling subset. Low-reporting years excluded only pre-COVID; 2020-22 kept with flag_covid.
  dt[, include := in_pidsr_period & !flag_gap_week & !flag_zero_run &
                   !(flag_low_year %in% TRUE & year <= 2019)]

  # ---- Time variables ----
  setorder(dt, city, start)
  dt[, time := seq_len(.N), by = city]          # consecutive period index (lags = rows)
  dt[, mid := NULL]
  setcolorder(dt, c("city", "adm3_pcode", "year", "mw", "start", "end", "days", "time",
                    "cases", "pop", "log_offset", "pr_week", "pr_total"))
  dt[, calendar_version := version]
  list(dt = dt[], yr_tot = yr_tot, zero_rule = zero_rule)
}

cal_primary <- doh_mw_calendar(2003:2022, min_first_days = 4L)
cal_altA    <- doh_mw_calendar(2003:2022, min_first_days = 2L)
cal_altB    <- delivered_calendar(2003:2022)

res  <- build_dataset(cal_primary, "primary")
resA <- build_dataset(cal_altA, "altA")
resB <- build_dataset(cal_altB, "altB")
dt <- res$dt; yr_tot <- res$yr_tot; zero_rule <- res$zero_rule

fwrite(dt, file.path(PATHS$processed, "city_week.csv"));            saveRDS(dt, file.path(PATHS$processed, "city_week.rds"))
fwrite(resA$dt, file.path(PATHS$processed, "city_week_altA.csv"));  saveRDS(resA$dt, file.path(PATHS$processed, "city_week_altA.rds"))
fwrite(resB$dt, file.path(PATHS$processed, "city_week_altB.csv"));  saveRDS(resB$dt, file.path(PATHS$processed, "city_week_altB.rds"))
for (f in c("dq_gap_weeks.csv")) if (file.exists(file.path(OUT, f))) file.remove(file.path(OUT, f))  # obsolete

# ---- 6. Calendar tables -----------------------------------------------------
cal_cmp <- merge(cal_primary[, .(year, mw, start_p = start, end_p = end, days_p = days)],
                 cal_altA[, .(year, mw, start_a = start, end_a = end, days_a = days)], by = c("year", "mw"))
cal_cmp <- merge(cal_cmp, cal_altB[!is.na(mw), .(year, mw, start_b = start, end_b = end)], by = c("year", "mw"))
cal_cmp[, jan1 := weekdays(as.IDate(sprintf("%d-01-01", year)))]
cal_cmp[, shift_b_vs_p := as.integer(start_b - start_p)]   # days the delivered dates are offset
fwrite(cal_cmp[year >= 2008], file.path(OUT, "calendar_comparison.csv"))
fwrite(cal_primary, file.path(OUT, "doh_mw_calendar_primary.csv"))

# Exposure agreement between versions (same city, year, MW)
ver_cmp <- merge(dt[in_pidsr_period == TRUE, .(city, year, mw, pr_p = pr_week, cases)],
                 resA$dt[in_pidsr_period == TRUE, .(city, year, mw, pr_a = pr_week)], by = c("city", "year", "mw"))
ver_cmp <- merge(ver_cmp, resB$dt[!is.na(mw) & in_pidsr_period == TRUE, .(city, year, mw, pr_b = pr_week)],
                 by = c("city", "year", "mw"))
ver_summary <- ver_cmp[, .(r_primary_altA = round(cor(pr_p, pr_a), 3), r_primary_altB = round(cor(pr_p, pr_b), 3),
                           weeks_differ_A = sum(abs(pr_p - pr_a) > 1e-6), weeks = .N), by = city]
fwrite(ver_summary, file.path(OUT, "calendar_version_rain_agreement.csv"))

# ---- 7. Data-quality tables (primary) ---------------------------------------
fwrite(yr_tot, file.path(OUT, "dq_city_year_reporting.csv"))
fwrite(dq_clim_na, file.path(OUT, "dq_climate_missing.csv"))
fwrite(dq_pop_na, file.path(OUT, "dq_population_missing.csv"))
fwrite(zero_rule, file.path(OUT, "dq_zero_run_rule.csv"))

zero_runs <- dt[order(city, start)][flag_zero_run == TRUE][
  , grp := cumsum(c(1L, diff(time) != 1L)), by = city][
  , .(start = min(start), end = max(end), weeks = .N), by = .(city, grp)][, grp := NULL]
fwrite(zero_runs, file.path(OUT, "dq_zero_runs.csv"))

city_summary <- dt[in_pidsr_period == TRUE, .(
  weeks = .N,
  lepto_total = sum(cases, na.rm = TRUE),
  lepto_mean = round(mean(cases, na.rm = TRUE), 2),
  var_to_mean = round(var(cases, na.rm = TRUE) / mean(cases, na.rm = TRUE), 1),
  pct_zero = round(100 * mean(cases == 0, na.rm = TRUE)),
  max_week = max(cases, na.rm = TRUE),
  pop_2020 = round(city_pop[city == .BY$city & year == 2020, pop]),
  rate_per100k_yr = round(1e5 * sum(cases, na.rm = TRUE) / mean(pop) / 15, 1),
  rain_mm_yr = round(sum(pr_total) / 15),
  all_zero_weeks = sum(flag_all_zero, na.rm = TRUE),
  weeks_flag_zero_run = sum(flag_zero_run), weeks_flag_low_year = sum(flag_low_year %in% TRUE),
  weeks_excluded = sum(!include)
), by = city][order(-lepto_total)]
fwrite(city_summary, file.path(OUT, "city_summary.csv"))

rain_cmp <- dt[, .(r_pop_area = round(cor(pr_week, pr_week_area), 3),
                   r_pop_mean = round(cor(pr_week, pr_week_mean), 3)), by = city]
fwrite(rain_cmp, file.path(OUT, "rain_weighting_correlation.csv"))

for (v in list(res, resA, resB)) with(v$dt, log_step(calendar_version[1], ":", length(cases), "rows;",
  sum(include), "included; lepto total", sum(cases, na.rm = TRUE), "; in model", sum(cases[include])))
print(city_summary); print(ver_summary)

# ---- 9. Add NASA IMERG rainfall ----------------------------------------------
# Rebuilding the datasets above drops the IMERG columns, so re-add them automatically
# whenever the downloaded IMERG files are present (see R/imerg_download.R).
if (dir.exists("data/external/imerg/final") && dir.exists("data/external/imerg/late")) {
  log_step("Adding IMERG rainfall (R/01b_add_imerg.R)")
  source("R/01b_add_imerg.R")
} else {
  message("IMERG files not found in data/external/imerg - skipping IMERG columns. Run R/imerg_download.R first.")
}
