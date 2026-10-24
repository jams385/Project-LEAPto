# =============================================================================
# imerg_download.R  —  Download NASA IMERG daily rainfall (V07, 0.1°), 2003-2022
#
# Products : "final" (GPM_3IMERGDF, research quality) and "late" (GPM_3IMERGDL, ~14 h latency)
# Area kept: a box around each of the 12 cities, widened by 1.0° (~110 km) so upstream river
#            catchments are included. Everything else is discarded after download.
# Output   : data/external/imerg/<product>/<year>/imerg_<product>_<YYYYMMDD>.csv.gz  (lon, lat, pr mm/day)
#            data/external/imerg/download_log.csv   (method, bytes, seconds per day)
#
# HOW TO RUN (from the LeapTo project root, in R):
#   1. Trial — 7 days of each product, prints speed and an estimate for the full run:
#        source("R/imerg_download.R")
#   2. Full run — 2003-2022, both products (resumes automatically if interrupted):
#        Sys.setenv(IMERG_MODE = "full"); source("R/imerg_download.R")
#      Keep the Mac awake meanwhile: in a second Terminal run   caffeinate -i
#      (press Ctrl+C there when the download has finished).
#   Re-running the full command later only fetches days that are still missing.
#
# Requires the same Earthdata setup as R/imerg_test.R (~/.netrc + approved GES DISC app),
# and packages data.table, curl, ncdf4.
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages({ library(curl); library(ncdf4); library(parallel) })

MODE     <- Sys.getenv("IMERG_MODE", "trial")         # "trial" or "full"
PRODUCTS <- c("final", "late")
YEARS    <- 2003:2022
WORKERS  <- as.integer(Sys.getenv("IMERG_WORKERS", "4"))
MARGIN   <- 1.0                                       # degrees added around each city

ROOT <- "data/external/imerg"; dir.create(ROOT, recursive = TRUE, showWarnings = FALSE)
LOG  <- file.path(ROOT, "download_log.csv")

# IMERG 0.1° global grid: lon -179.95..179.95 (3600), lat -89.95..89.95 (1800); 0-based indices
PH_BOX <- list(lon = c(116, 127), lat = c(4, 21))
idx <- function(x, lo) as.integer(round((x - lo) / 0.1))
LON_I <- c(idx(116.05, -179.95), idx(126.95, -179.95))   # 2960..3069
LAT_I <- c(idx(4.05, -89.95), idx(20.95, -89.95))        # 940..1109

# ---- Area to keep: city bounding boxes (from barangay polygons) + margin ----
geo <- fread(file.path(PATHS$raw2, "brgy_geography.csv"), select = c("adm4_pcode", "geometry"))
loc <- fread(file.path(PATHS$raw, "location.csv"))[, .(adm4_pcode, adm3_en)][, city := CITY_SHORT[adm3_en]]
geo <- merge(geo, loc, by = "adm4_pcode")
bb <- geo[, {
  nums <- as.numeric(unlist(regmatches(geometry, gregexpr("-?[0-9]+\\.?[0-9]*", geometry))))
  x <- nums[c(TRUE, FALSE)]; y <- nums[c(FALSE, TRUE)]
  .(xmin = min(x), xmax = max(x), ymin = min(y), ymax = max(y))
}, by = .(adm4_pcode, city)][, .(xmin = min(xmin) - MARGIN, xmax = max(xmax) + MARGIN,
                                 ymin = min(ymin) - MARGIN, ymax = max(ymax) + MARGIN), by = city]
fwrite(bb, file.path(ROOT, "kept_boxes.csv"))
keep_cell <- function(lon, lat) {
  k <- rep(FALSE, length(lon))
  for (i in seq_len(nrow(bb))) k <- k | (lon >= bb$xmin[i] & lon <= bb$xmax[i] & lat >= bb$ymin[i] & lat <= bb$ymax[i])
  k
}

# ---- URL helpers ------------------------------------------------------------
product_info <- function(p) switch(p,
  final = list(coll = "GPM_3IMERGDF.07", prefix = "3B-DAY.MS.MRG.3IMERG"),
  late  = list(coll = "GPM_3IMERGDL.07", prefix = "3B-DAY-L.MS.MRG.3IMERG"))

make_handle <- function() {
  ck <- file.path(tempdir(), sprintf("earthdata_cookies_%d", Sys.getpid()))
  new_handle(netrc = 1L, netrc_file = path.expand("~/.netrc"), followlocation = 1L,
             cookiefile = ck, cookiejar = ck, useragent = "LeapTo-imerg-download", timeout = 300L)
}

listing_cache <- new.env()
file_name <- function(p, d) {
  info <- product_info(p)
  dir_url <- sprintf("https://data.gesdisc.earthdata.nasa.gov/data/GPM_L3/%s/%s/%s/", info$coll, format(d, "%Y"), format(d, "%m"))
  if (is.null(listing_cache[[dir_url]])) {
    html <- tryCatch(rawToChar(curl_fetch_memory(dir_url, handle = make_handle())$content), error = function(e) "")
    listing_cache[[dir_url]] <- unique(regmatches(html, gregexpr(paste0(gsub(".", "\\.", info$prefix, fixed = TRUE),
                                         "\\.[0-9]{8}-S000000-E235959\\.V07[A-Z]?\\.nc4"), html))[[1]])
  }
  hit <- grep(format(d, "%Y%m%d"), listing_cache[[dir_url]], value = TRUE)
  list(dir_url = dir_url, info = info,
       fname = if (length(hit)) hit[1] else sprintf("%s.%s-S000000-E235959.V07B.nc4", info$prefix, format(d, "%Y%m%d")))
}
full_url   <- function(f) paste0(f$dir_url, f$fname)
subset_url <- function(f, d) {
  ce <- sprintf("precipitation[0:0][%d:%d][%d:%d],lon[%d:%d],lat[%d:%d]",
                LON_I[1], LON_I[2], LAT_I[1], LAT_I[2], LON_I[1], LON_I[2], LAT_I[1], LAT_I[2])
  sprintf("https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/%s/%s/%s/%s.nc4?%s",
          f$info$coll, format(d, "%Y"), format(d, "%m"), f$fname, ce)
}

is_hdf5 <- function(path) file.exists(path) && identical(readBin(path, "raw", 4), as.raw(c(0x89, 0x48, 0x44, 0x46)))

read_crop <- function(path) {
  nc <- nc_open(path); on.exit(nc_close(nc))
  vname <- intersect(c("precipitation", "precipitationCal"), names(nc$var))[1]
  if (is.na(vname)) stop("no precipitation variable")
  lon <- as.vector(ncvar_get(nc, "lon")); lat <- as.vector(ncvar_get(nc, "lat"))
  dims <- vapply(nc$var[[vname]]$dim, function(x) x$name, "")
  ix <- which(lon >= PH_BOX$lon[1] & lon <= PH_BOX$lon[2]); iy <- which(lat >= PH_BOX$lat[1] & lat <= PH_BOX$lat[2])
  start <- count <- rep(1L, length(dims))
  start[dims == "lon"] <- min(ix); count[dims == "lon"] <- length(ix)
  start[dims == "lat"] <- min(iy); count[dims == "lat"] <- length(iy)
  v <- ncvar_get(nc, vname, start = start, count = count, collapse_degen = TRUE)
  if (which(dims == "lat") < which(dims == "lon")) v <- t(v)
  g <- data.table(expand.grid(lon = round(lon[ix], 2), lat = round(lat[iy], 2)))
  g[, pr := round(as.vector(v), 2)][pr < 0, pr := NA_real_]
  if (nrow(g) != 110L * 170L) stop(sprintf("unexpected grid size %d", nrow(g)))
  g[keep_cell(lon, lat)]
}

# ---- One day ----------------------------------------------------------------
METHOD <- NA_character_   # "subset" or "full"; decided on the first successful day of each worker
fetch_day <- function(p, d) {
  out <- file.path(ROOT, p, format(d, "%Y"), sprintf("imerg_%s_%s.csv.gz", p, format(d, "%Y%m%d")))
  if (file.exists(out)) return(NULL)
  dir.create(dirname(out), recursive = TRUE, showWarnings = FALSE)
  f <- file_name(p, d); tmp <- tempfile(fileext = ".nc4"); t0 <- Sys.time()
  try_get <- function(url) {
    r <- tryCatch(curl_fetch_disk(url, tmp, handle = make_handle()), error = function(e) list(status_code = -1))
    ok <- isTRUE(r$status_code == 200) && is_hdf5(tmp)
    g <- if (ok) tryCatch(read_crop(tmp), error = function(e) NULL) else NULL
    list(g = g, bytes = if (file.exists(tmp)) file.size(tmp) else NA_real_, status = r$status_code)
  }
  res <- NULL; used <- NA_character_
  if (!identical(METHOD, "full")) {
    res <- try_get(subset_url(f, d)); used <- "subset"
    if (is.null(res$g)) { if (is.na(METHOD)) METHOD <<- "full"; res <- NULL } else if (is.na(METHOD)) METHOD <<- "subset"
  }
  if (is.null(res)) { res <- try_get(full_url(f)); used <- "full" }
  unlink(tmp)
  secs <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
  if (is.null(res$g)) {
    return(data.table(product = p, date = d, method = used, ok = FALSE, status = res$status, bytes = res$bytes, secs = secs))
  }
  fwrite(res$g, out)
  data.table(product = p, date = d, method = used, ok = TRUE, status = res$status, bytes = res$bytes, secs = secs)
}

# ---- Run --------------------------------------------------------------------
days <- if (MODE == "full") seq(as.IDate(sprintf("%d-01-01", min(YEARS))), as.IDate(sprintf("%d-12-31", max(YEARS))), by = 1L) else
                            seq(as.IDate("2011-12-10"), as.IDate("2011-12-16"), by = 1L)
jobs <- CJ(product = PRODUCTS, date = days)
jobs[, out := file.path(ROOT, product, format(date, "%Y"), sprintf("imerg_%s_%s.csv.gz", product, format(date, "%Y%m%d")))]
todo <- jobs[!file.exists(out)]
log_step(sprintf("IMERG %s run: %d product-days requested, %d already done, %d to fetch with %d workers",
                 MODE, nrow(jobs), nrow(jobs) - nrow(todo), nrow(todo), WORKERS))

if (nrow(todo)) {
  # first day on its own: checks login and decides subset vs full download for all workers
  first <- fetch_day(todo$product[1], todo$date[1])
  if (!isTRUE(first$ok)) stop(sprintf(paste0("First download failed (HTTP %s). Check ~/.netrc (chmod 600) and that ",
                                              "'NASA GESDISC DATA ARCHIVE' is approved in your Earthdata profile."), first$status), call. = FALSE)
  log_step("Download method:", METHOD, sprintf("(%.1f s, %.2f MB for the first day)", first$secs, first$bytes / 1e6))
  fwrite(first, LOG, append = file.exists(LOG))
  rest <- todo[-1]
  chunk_size <- WORKERS * 25L
  chunks <- split(seq_len(nrow(rest)), ceiling(seq_len(nrow(rest)) / chunk_size))
  t_start <- Sys.time(); done <- 0L
  for (ch in chunks) {
    res <- rbindlist(mclapply(ch, function(i) fetch_day(rest$product[i], rest$date[i]), mc.cores = WORKERS), fill = TRUE)
    if (nrow(res)) fwrite(res, LOG, append = TRUE)
    done <- done + length(ch)
    el <- as.numeric(difftime(Sys.time(), t_start, units = "mins"))
    eta <- el / done * (nrow(rest) - done)
    log_step(sprintf("%d / %d done | failures in this batch: %d | elapsed %.0f min | about %.0f min left",
                     done, nrow(rest), sum(!res$ok), el, eta))
  }
}

# ---- Summary ----------------------------------------------------------------
lg <- fread(LOG)
miss <- jobs[!file.exists(out)]
cat(sprintf("\nFiles present: %d of %d product-days. Missing: %d\n", nrow(jobs) - nrow(miss), nrow(jobs), nrow(miss)))
if (nrow(miss)) cat("Re-run the same command to retry missing days.\n")
recent <- tail(lg[ok == TRUE], 200)
if (nrow(recent)) {
  per_day <- median(recent$secs); mb <- median(recent$bytes, na.rm = TRUE) / 1e6
  cat(sprintf("Method: %s | median %.1f s and %.2f MB downloaded per product-day\n", recent$method[1], per_day, mb))
  if (MODE == "trial") {
    n_full <- 2 * length(seq(as.IDate("2003-01-01"), as.IDate("2022-12-31"), by = 1L))
    cat(sprintf("Estimate for the full run (both products, 2003-2022, %d product-days, %d workers): about %.1f hours, %.0f GB downloaded\n",
                n_full, WORKERS, n_full * per_day / WORKERS / 3600, n_full * mb / 1000))
    kept <- sum(file.size(jobs$out[file.exists(jobs$out)])) / sum(file.exists(jobs$out))
    cat(sprintf("Disk space for the kept area: about %.0f MB in total\n", n_full * kept / 1e6))
    cat('To start it:  Sys.setenv(IMERG_MODE = "full"); source("R/imerg_download.R")\n')
  }
}
