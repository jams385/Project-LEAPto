# =============================================================================
# 01b_add_imerg.R  —  Add NASA IMERG rainfall to the weekly datasets
#
# Run AFTER 01_build_dataset.R (it adds columns to that script's outputs) and after
# R/imerg_download.R has fetched data/external/imerg/{final,late}/.
#
# Inputs  : data/external/imerg/<product>/<year>/imerg_<product>_<YYYYMMDD>.csv.gz
#           data/processed/city_week{,_altA,_altB}.rds
# Outputs : the same city_week*.rds/.csv with new columns (suffix _imf = IMERG Final, _iml = IMERG Late)
#           data/processed/city_day_imerg.csv     daily city rainfall by product
#           output/stage1/imerg_*.csv             mapping and quality checks
#
# Method (mirrors the CHIRPS processing in 01_build_dataset.R):
#   * each barangay is assigned the IMERG 0.1° cell containing its centroid
#     (centroid = mean of polygon vertices; adequate at ~11 km resolution)
#   * city daily rainfall = population-weighted mean over barangays (WorldPop shares by year,
#     2020 shares for 2021-22)
#   * weekly values summed over each morbidity week's true dates; pr_week_* is per 7 days
#   * pr_basin_*: mean rainfall over an approximate box covering the upstream Cagayan de Oro
#     river catchment (124.45-125.00 E, 7.90-8.45 N); NA for other cities
# =============================================================================

source("R/_common.R")
OUT <- file.path(PATHS$out, "stage1")
IMERG_DIR <- "data/external/imerg"
PRODUCTS <- c(imf = "final", iml = "late")
CDO_BASIN_BOX <- list(lon = c(124.45, 125.00), lat = c(7.90, 8.45))

# ---- Barangay -> IMERG cell -------------------------------------------------
log_step("Barangay centroids")
geo <- fread(file.path(PATHS$raw2, "brgy_geography.csv"), select = c("adm4_pcode", "geometry"))
geo[, c("cx", "cy") := {
  nums <- as.numeric(unlist(regmatches(geometry, gregexpr("-?[0-9]+\\.?[0-9]*", geometry))))
  .(mean(nums[c(TRUE, FALSE)]), mean(nums[c(FALSE, TRUE)]))
}, by = adm4_pcode]
loc <- fread(file.path(PATHS$raw, "location.csv"))[, .(adm4_pcode, adm3_pcode, adm3_en)][, city := CITY_SHORT[adm3_en]]
cell_of <- function(x) round(floor(x * 10) / 10 + 0.05, 2)     # IMERG cell centres at x.x5
brgy <- merge(geo[, .(adm4_pcode, cx, cy)], loc, by = "adm4_pcode")
brgy[, `:=`(lon = cell_of(cx), lat = cell_of(cy))]
cells_city <- brgy[, .(n_brgy = .N, n_cells = uniqueN(paste(lon, lat))), by = city]
fwrite(cells_city, file.path(OUT, "imerg_cells_per_city.csv"))

wp <- fread(file.path(PATHS$raw2, "worldpop_population.csv"), select = c("adm4_pcode", "date", "pop_count_total"))
wp[, year := year(as.IDate(date))]
wp <- merge(wp, brgy[, .(adm4_pcode, city)], by = "adm4_pcode")
wp[, w := pop_count_total / sum(pop_count_total, na.rm = TRUE), by = .(city, year)]
# weight per city-cell-year (sum of barangay shares that fall in the cell)
wcell <- merge(wp[, .(adm4_pcode, year, w)], brgy[, .(adm4_pcode, city, lon, lat)], by = "adm4_pcode")[
  , .(w = sum(w, na.rm = TRUE)), by = .(city, year, lon, lat)]

needed <- unique(rbind(brgy[, .(lon, lat)],
  CJ(lon = round(seq(CDO_BASIN_BOX$lon[1] + 0.05, CDO_BASIN_BOX$lon[2] - 0.05, by = 0.1), 2),
     lat = round(seq(CDO_BASIN_BOX$lat[1] + 0.05, CDO_BASIN_BOX$lat[2] - 0.05, by = 0.1), 2))))

# ---- Read daily IMERG -------------------------------------------------------
read_product <- function(p) {
  files <- list.files(file.path(IMERG_DIR, p), pattern = "\\.csv\\.gz$", recursive = TRUE, full.names = TRUE)
  log_step("Reading", length(files), p, "files")
  rbindlist(lapply(files, function(f) {
    g <- fread(f)[needed, on = .(lon, lat), nomatch = 0L]
    g[, date := as.IDate(sub(".*_(\\d{8})\\.csv\\.gz$", "\\1", f), format = "%Y%m%d")]
  }))
}
daily <- rbindlist(lapply(names(PRODUCTS), function(k) read_product(PRODUCTS[[k]])[, src := k]))
stopifnot(!anyNA(daily$pr))

# city daily, population-weighted
daily[, year := pmin(year(date), 2020L)]
cd <- merge(daily, wcell, by = c("lon", "lat", "year"), allow.cartesian = TRUE)
city_day <- cd[, .(pr = sum(pr * w) / sum(w)), by = .(src, city, date)]
basin_day <- daily[lon >= CDO_BASIN_BOX$lon[1] & lon <= CDO_BASIN_BOX$lon[2] &
                   lat >= CDO_BASIN_BOX$lat[1] & lat <= CDO_BASIN_BOX$lat[2],
                   .(pr_basin = mean(pr)), by = .(src, date)][, city := "Cagayan de Oro"]
city_day <- merge(city_day, basin_day, by = c("src", "city", "date"), all.x = TRUE)
stopifnot(city_day[, .N, by = .(src, city)][, all(N == 7305L)])

# ---- Quality check: Late vs Final ---------------------------------------------
w <- dcast(city_day, city + date ~ src, value.var = "pr")
w[, late_flag := iml > 150 & iml > 3 * pmax(imf, 1)]
qc <- w[, .(days = .N, r_daily = round(cor(imf, iml), 3), mean_final = round(mean(imf) * 365.25),
            mean_late = round(mean(iml) * 365.25), max_final = round(max(imf)), max_late = round(max(iml)),
            late_flag_days = sum(late_flag)), by = city]
fwrite(qc, file.path(OUT, "imerg_final_vs_late_qc.csv"))
fwrite(w[late_flag == TRUE][order(-iml)], file.path(OUT, "imerg_late_flagged_days.csv"))

city_day_wide <- dcast(city_day, city + date ~ src, value.var = c("pr", "pr_basin"))
fwrite(city_day_wide, file.path(PATHS$processed, "city_day_imerg.csv"))

# ---- Add weekly columns to each calendar version --------------------------------
add_to <- function(file) {
  dt <- readRDS(file.path(PATHS$processed, file))
  old <- grep("_(imf|iml)$", names(dt), value = TRUE); if (length(old)) dt[, (old) := NULL]
  per <- unique(dt[, .(city, start, end, days)])
  daymap <- per[, .(date = seq(start, end, by = 1L)), by = .(city, start, end, days)]
  x <- merge(daymap, city_day, by = c("city", "date"), allow.cartesian = TRUE)
  wk <- x[, .(pr_total = sum(pr), pr_day_max = max(pr), heavy_days = sum(pr >= 50),
              pr_basin_total = if (all(is.na(pr_basin))) NA_real_ else sum(pr_basin), n = .N),
          by = .(src, city, start, days)]
  stopifnot(all(wk$n == wk$days))
  wk[, `:=`(pr_week = pr_total / days * 7, pr_basin = pr_basin_total / days * 7, n = NULL, pr_basin_total = NULL)]
  wide <- dcast(wk, city + start ~ src, value.var = c("pr_week", "pr_total", "pr_day_max", "heavy_days", "pr_basin"))
  dt <- merge(dt, wide, by = c("city", "start"), all.x = TRUE)
  stopifnot(!anyNA(dt$pr_week_imf), !anyNA(dt$pr_week_iml))
  setorder(dt, city, start)
  saveRDS(dt, file.path(PATHS$processed, file)); fwrite(dt, sub("\\.rds$", ".csv", file.path(PATHS$processed, file)))
  log_step("Updated", file, ":", nrow(dt), "rows")
  dt
}
res <- lapply(c("city_week.rds", "city_week_altA.rds", "city_week_altB.rds"), add_to)

print(cells_city); print(qc)
log_step("Late flagged days (Late > 150 mm and > 3x Final):", sum(w$late_flag))
