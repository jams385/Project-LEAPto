# =============================================================================
# imerg_test.R  —  Is NASA IMERG rainfall better than CHIRPS for extreme events?
#
# Downloads IMERG daily rainfall (0.1°) for three storms with known station records,
# crops it to the Philippines, and compares it with the CHIRPS rainfall in our dataset
# and with the station readings.
#
#   Event                         Days (UTC)              Station reference
#   Washi (Sendong), CDO          2011-12-14 .. 12-19     Lumbia: 180.9 mm in 24 h
#   Ketsana (Ondoy), Metro Manila 2009-09-24 .. 09-28     Science Garden: 454.9 mm on 27 Sep
#   SW monsoon floods, Manila     2012-08-05 .. 08-10     Science Garden: 323.4 / 363.7 / 292.6 mm on 7-9 Aug
#
# ---- ONE-TIME SETUP (about 5 minutes) ----------------------------------------
# 1. Create a free NASA Earthdata account: https://urs.earthdata.nasa.gov
# 2. In your Earthdata profile, open "Applications" > "Authorized Apps" and approve
#    "NASA GESDISC DATA ARCHIVE" (without this, downloads return a login page).
# 3. Create a file ~/.netrc containing ONE line (use your own username/password):
#        machine urs.earthdata.nasa.gov login YOUR_USERNAME password YOUR_PASSWORD
#    then, in Terminal:   chmod 600 ~/.netrc
# 4. In R (project root):  install.packages(c("curl", "ncdf4")); renv::snapshot()
#
# ---- RUN ---------------------------------------------------------------------
#   From the LeapTo project root:   source("R/imerg_test.R")
#   Downloads ~17 daily files per product (each is deleted after cropping).
#   Outputs: data/external/imerg_test/*.csv.gz   (cropped daily grids)
#            output/imerg_test/*.csv             (comparison tables)
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages({ library(curl); library(ncdf4) })

# Which IMERG runs to test. "final" = research-quality (months of delay);
# "late" = available ~14 h after the day ends (what a live app could use).
PRODUCTS <- c("final", "late")

EVENTS <- data.table(
  event = c("Washi 2011", "Ondoy 2009", "Habagat 2012"),
  from  = as.IDate(c("2011-12-14", "2009-09-24", "2012-08-05")),
  to    = as.IDate(c("2011-12-19", "2009-09-28", "2012-08-10")),
  cities = list("Cagayan de Oro", c("Navotas", "Mandaluyong", "Muntinlupa"), c("Navotas", "Mandaluyong", "Muntinlupa"))
)

# Station locations (approximate) and published readings
STATIONS <- data.table(
  station = c("Lumbia (CDO)", "Science Garden (Quezon City)"),
  lon = c(124.611, 121.044), lat = c(8.416, 14.645),
  nearest_dataset_city = c("Cagayan de Oro", "Mandaluyong"),
  nearest_dataset_brgy = c("PH104305054", NA)          # Lumbia is itself a barangay in the dataset
)
STATION_OBS <- data.table(
  station = c("Lumbia (CDO)", "Science Garden (Quezon City)", "Science Garden (Quezon City)",
              "Science Garden (Quezon City)", "Science Garden (Quezon City)"),
  date = as.IDate(c("2011-12-16", "2009-09-26", "2012-08-07", "2012-08-08", "2012-08-09")),
  station_mm = c(180.9, 454.9, 323.4, 363.7, 292.6),
  note = c("24 h total during Washi (Wikipedia, citing PAGASA)",
           "reported for 27 Sep by KNMI (PAGASA 24 h to 08:00 local = Ondoy rain of 26 Sep)",
           "KNMI / GTS", "KNMI / GTS", "KNMI / GTS")
)

# Approximate box over the upstream Cagayan de Oro river catchment (Bukidnon highlands).
CDO_BASIN_BOX <- list(lon = c(124.45, 125.00), lat = c(7.90, 8.45))
PH_BOX <- list(lon = c(116, 127), lat = c(4, 21))   # crop extent

DL_DIR  <- "data/external/imerg_test"; OUT <- file.path(PATHS$out, "imerg_test")
dir.create(DL_DIR, recursive = TRUE, showWarnings = FALSE); dir.create(OUT, recursive = TRUE, showWarnings = FALSE)

# ---- Download helpers -------------------------------------------------------
product_info <- function(p) switch(p,
  final = list(coll = "GPM_3IMERGDF.07", prefix = "3B-DAY.MS.MRG.3IMERG"),
  late  = list(coll = "GPM_3IMERGDL.07", prefix = "3B-DAY-L.MS.MRG.3IMERG"))

make_handle <- function() {
  ck <- file.path(tempdir(), "earthdata_cookies")
  new_handle(netrc = 1L, netrc_file = path.expand("~/.netrc"), followlocation = 1L,
             cookiefile = ck, cookiejar = ck, useragent = "LeapTo-imerg-test")
}

month_listing <- new.env()
find_file_url <- function(p, d) {
  info <- product_info(p)
  dir_url <- sprintf("https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/%s/%s/%s/",
                     info$coll, format(d, "%Y"), format(d, "%m"))
  key <- paste(p, dir_url)
  if (is.null(month_listing[[key]])) {
    html <- tryCatch(rawToChar(curl_fetch_memory(dir_url, handle = make_handle())$content), error = function(e) "")
    month_listing[[key]] <- unique(regmatches(html, gregexpr(paste0(gsub(".", "\\.", info$prefix, fixed = TRUE),
                                                               "\\.[0-9]{8}-S000000-E235959\\.V07[A-Z]?\\.nc4"), html))[[1]])
  }
  hit <- grep(format(d, "%Y%m%d"), month_listing[[key]], value = TRUE)
  fname <- if (length(hit)) hit[1] else sprintf("%s.%s-S000000-E235959.V07B.nc4", info$prefix, format(d, "%Y%m%d"))
  paste0(dir_url, fname)
}

download_day <- function(p, d) {
  out_csv <- file.path(DL_DIR, sprintf("imerg_%s_%s.csv.gz", p, format(d, "%Y%m%d")))
  if (file.exists(out_csv)) return(fread(out_csv))
  url <- find_file_url(p, d); tmp <- tempfile(fileext = ".nc4")
  res <- curl_fetch_disk(url, tmp, handle = make_handle())
  sig <- readBin(tmp, "raw", 4)
  if (res$status_code != 200 || !identical(sig, as.raw(c(0x89, 0x48, 0x44, 0x46)))) {
    unlink(tmp)
    stop(sprintf(paste0("Download failed for %s (HTTP %s).\n  URL: %s\n  Check: ~/.netrc exists with chmod 600, ",
                        "and 'NASA GESDISC DATA ARCHIVE' is approved in your Earthdata profile."),
                 format(d), res$status_code, url), call. = FALSE)
  }
  g <- crop_imerg(tmp); unlink(tmp)
  fwrite(g, out_csv); g
}

# Read the IMERG daily 'precipitation' variable (mm/day) and crop to the Philippines
crop_imerg <- function(path) {
  nc <- nc_open(path); on.exit(nc_close(nc))
  vname <- intersect(c("precipitation", "precipitationCal"), names(nc$var))[1]
  if (is.na(vname)) stop("No precipitation variable found in ", path)
  lon <- ncvar_get(nc, "lon"); lat <- ncvar_get(nc, "lat")
  dims <- vapply(nc$var[[vname]]$dim, function(x) x$name, "")
  ix <- which(lon >= PH_BOX$lon[1] & lon <= PH_BOX$lon[2]); iy <- which(lat >= PH_BOX$lat[1] & lat <= PH_BOX$lat[2])
  start <- count <- rep(1L, length(dims))
  start[dims == "lon"] <- min(ix); count[dims == "lon"] <- length(ix)
  start[dims == "lat"] <- min(iy); count[dims == "lat"] <- length(iy)
  v <- ncvar_get(nc, vname, start = start, count = count, collapse_degen = TRUE)
  # put into [lon, lat] orientation
  if (which(dims == "lat") < which(dims == "lon")) v <- t(v)
  g <- data.table(expand.grid(lon = lon[ix], lat = lat[iy]))   # lon varies fastest, matching v[lon, lat]
  g[, pr := as.vector(v)]
  g[pr < 0, pr := NA_real_]
  g[, `:=`(lon = round(lon, 2), lat = round(lat, 2))][]
}

# ---- Barangay -> IMERG cell mapping -----------------------------------------
# Approximate barangay centroid = mean of polygon vertices (good enough at 0.1° resolution)
log_step("Barangay centroids")
geo <- fread(file.path(PATHS$raw2, "brgy_geography.csv"), select = c("adm4_pcode", "geometry"))
geo[, c("cx", "cy") := {
  nums <- as.numeric(unlist(regmatches(geometry, gregexpr("-?[0-9]+\\.?[0-9]*", geometry))))
  .(mean(nums[c(TRUE, FALSE)]), mean(nums[c(FALSE, TRUE)]))
}, by = adm4_pcode]
loc <- fread(file.path(PATHS$raw, "location.csv"))[, .(adm4_pcode, adm3_en, adm4_en)][, city := CITY_SHORT[adm3_en]]
wp  <- fread(file.path(PATHS$raw2, "worldpop_population.csv"), select = c("adm4_pcode", "date", "pop_count_total"))[
          year(as.IDate(date)) == 2020, .(adm4_pcode, pop = pop_count_total)]
brgy <- Reduce(function(a, b) merge(a, b, by = "adm4_pcode"), list(geo[, .(adm4_pcode, cx, cy)], loc, wp))
cell_of <- function(x) round(floor(x * 10) / 10 + 0.05, 2)   # IMERG cell centres are at x.x5
brgy[, `:=`(lon = cell_of(cx), lat = cell_of(cy))]
STATIONS[, `:=`(cell_lon = cell_of(lon), cell_lat = cell_of(lat))]

# ---- CHIRPS values from our dataset for the same days -----------------------
log_step("Reading CHIRPS for event days")
all_days <- EVENTS[, .(date = seq(from, to, by = 1L)), by = event]
clim <- fread(climate_file(), select = c("adm4_pcode", "date", "pr"))[, date := as.IDate(date)][date %in% all_days$date]
clim <- merge(clim, brgy[, .(adm4_pcode, city, pop)], by = "adm4_pcode")

# ---- Download IMERG and compare ---------------------------------------------
city_rows <- list(); stn_rows <- list(); basin_rows <- list()
for (p in PRODUCTS) for (i in seq_len(nrow(all_days))) {
  d <- all_days$date[i]; ev <- all_days$event[i]
  log_step("IMERG", p, format(d))
  g <- download_day(p, d)
  # city means (population-weighted over barangay cells), same as CHIRPS processing
  b <- merge(brgy, g, by = c("lon", "lat"), all.x = TRUE)
  cities <- EVENTS[event == ev, unlist(cities)]
  im <- b[city %in% cities, .(imerg_city = sum(pr * pop, na.rm = TRUE) / sum(pop[!is.na(pr)]),
                              imerg_max_cell = max(pr, na.rm = TRUE)), by = city]
  ch <- clim[date == d & city %in% cities, .(chirps_city = sum(pr * pop, na.rm = TRUE) / sum(pop[!is.na(pr)]),
                                             chirps_max_brgy = max(pr, na.rm = TRUE)), by = city]
  city_rows[[length(city_rows) + 1]] <- merge(im, ch, by = "city")[, `:=`(product = p, event = ev, date = d)]
  # stations: IMERG at the station's cell; CHIRPS at the barangay (Lumbia) or city mean (Science Garden proxy)
  s <- merge(STATIONS, g, by.x = c("cell_lon", "cell_lat"), by.y = c("lon", "lat"), all.x = TRUE)
  s[, chirps := fifelse(!is.na(nearest_dataset_brgy),
                        clim[date == d][match(s$nearest_dataset_brgy, adm4_pcode), pr],
                        ch[match(s$nearest_dataset_city, city), chirps_city])]
  stn_rows[[length(stn_rows) + 1]] <- s[, .(station, product = p, event = ev, date = d, imerg_cell = pr, chirps_nearby = chirps)]
  if (ev == "Washi 2011") {
    basin_rows[[length(basin_rows) + 1]] <- g[lon >= CDO_BASIN_BOX$lon[1] & lon <= CDO_BASIN_BOX$lon[2] &
                                              lat >= CDO_BASIN_BOX$lat[1] & lat <= CDO_BASIN_BOX$lat[2],
                                              .(product = p, date = d, basin_mean = mean(pr, na.rm = TRUE), basin_max = max(pr, na.rm = TRUE))]
  }
}

city_cmp <- rbindlist(city_rows); stn_cmp <- rbindlist(stn_rows); basin <- rbindlist(basin_rows)
num <- function(dt) { cols <- names(dt)[vapply(dt, is.double, TRUE)]; dt[, (cols) := lapply(.SD, round, 1), .SDcols = cols][] }

stn_cmp <- merge(stn_cmp, STATION_OBS[, .(station, date, station_mm)], by = c("station", "date"), all.x = TRUE)
fwrite(num(stn_cmp[order(product, event, station, date)]), file.path(OUT, "station_comparison_daily.csv"))
fwrite(num(city_cmp[order(product, event, city, date)]), file.path(OUT, "city_comparison_daily.csv"))
fwrite(num(basin[order(product, date)]), file.path(OUT, "cdo_basin_imerg_daily.csv"))

# Event totals (robust to day-boundary differences between products and stations)
stn_tot <- stn_cmp[, .(imerg_total = sum(imerg_cell), chirps_total = sum(chirps_nearby),
                       station_total_known_days = sum(station_mm, na.rm = TRUE),
                       imerg_on_known_days = sum(imerg_cell[!is.na(station_mm)]),
                       chirps_on_known_days = sum(chirps_nearby[!is.na(station_mm)])),
                   by = .(product, event, station)][station_total_known_days > 0]
city_tot <- city_cmp[, .(imerg_city_total = sum(imerg_city), chirps_city_total = sum(chirps_city),
                         imerg_peak_day = max(imerg_city), chirps_peak_day = max(chirps_city)), by = .(product, event, city)]
basin_tot <- basin[, .(event = "Washi 2011", basin_total_mean = sum(basin_mean), basin_peak_day_max_cell = max(basin_max)), by = product]
fwrite(num(stn_tot), file.path(OUT, "station_comparison_totals.csv"))
fwrite(num(city_tot), file.path(OUT, "city_comparison_totals.csv"))
fwrite(num(basin_tot), file.path(OUT, "cdo_basin_totals.csv"))

cat("\n=== Station check (mm, days with a published station reading) ===\n"); print(num(stn_tot))
cat("\n=== City means over each event window (mm) ===\n"); print(num(city_tot))
cat("\n=== Washi: IMERG over the upstream CDO catchment box (mm) ===\n"); print(num(basin_tot))
cat("\nDone. Tables are in", OUT, "\n")
