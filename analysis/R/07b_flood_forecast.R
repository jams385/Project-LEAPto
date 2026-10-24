# =============================================================================
# 07b_flood_forecast.R  —  Stage 7b: does flood exposure improve the forecasts?
#
# Repeats the Stage 5 rolling-origin test for the recommended model (pooled rain + last week's cases,
# IMERG Late, 1-week reporting delay) with the rain effect of each city scaled by (1 + g * E_c), as in
# 07_flood.R. g is estimated by maximum likelihood on each origin's TRAINING years only, separately for
# each horizon, so the test years stay unseen. Forecasts are compared with the Stage 5 pooled_ar forecasts
# on the same weeks.
#
# Inputs : output/stage5/forecasts.csv.gz, output/stage7/flood_exposure_city.csv, Stage 5 inputs
# Outputs: output/stage7/forecast_*.csv, output/stage7/forecasts_flood.csv.gz, figs
# =============================================================================

src5 <- readLines("R/05_validation.R")
eval(parse(text = src5[1:(grep("^# ---- Run \\(or reuse\\)", src5) - 1)]))              # data + fit_forecast
eval(parse(text = src5[grep("^p_exceed <- ", src5):(grep("^al <- add_alerts\\(fc\\)", src5) - 1)]))   # scoring helpers
OUT7 <- file.path(PATHS$out, "stage7"); FIG7 <- file.path(OUT7, "figs")
VARIANT <- "pooled_ar"
BLUE <- "#2a78d6"; ORANGE <- "#eb6834"; AQUA <- "#1baf7a"; GREY <- "#8a8984"; VIOLET <- "#6250d6"
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top", plot.title.position = "plot"))

ex <- fread(file.path(OUT7, "flood_exposure_city.csv"))
E <- setNames((ex$mh100 - mean(ex$mh100)) / 10, ex$city)
G_RANGE <- c(-1 / max(E), -1 / min(E)) * 0.98

FF <- file.path(OUT7, "forecasts_flood.csv.gz")
if (!file.exists(FF) || Sys.getenv("STAGE7_REFIT") == "1") {
  jobs <- CJ(origin = ORIGINS, h = HORIZONS)
  log_step("Flood forecasts:", nrow(jobs), "origin x horizon jobs on", CORES, "cores")
  res <- mclapply(seq_len(nrow(jobs)), function(i) {
    j <- jobs[i]; t0 <- Sys.time()
    o <- optimize(function(g) fit_forecast(j$origin, j$h, VARIANT, flood_e = E, g = g, ll_only = TRUE), G_RANGE, maximum = TRUE, tol = 0.02)
    ll0 <- fit_forecast(j$origin, j$h, VARIANT, flood_e = E, g = 0, ll_only = TRUE)
    r <- fit_forecast(j$origin, j$h, VARIANT, flood_e = E, g = o$maximum)
    message(sprintf("%s | origin %d h %d  g %.3f  LR %.2f  %.0fs", format(Sys.time(), "%H:%M:%S"), j$origin, j$h, o$maximum,
                    2 * (o$objective - ll0), as.numeric(difftime(Sys.time(), t0, units = "secs"))))
    if (is.null(r)) return(NULL)
    r[, `:=`(variant = "pooled_ar_flood", g = o$maximum, lr_train = 2 * (o$objective - ll0))]
    r[set == "test" | !is.na(thr_std5) | !is.na(thr_exc5)]
  }, mc.cores = CORES, mc.preschedule = FALSE)
  ffc <- rbindlist(res); fwrite(ffc, FF)
} else ffc <- fread(FF)
ffc[, start := as.IDate(start)]
fwrite(unique(ffc[, .(origin, h, g, lr_train, converged)])[order(h, origin)], file.path(OUT7, "forecast_g_by_origin.csv"))

base <- fread(file.path(PATHS$out, "stage5", "forecasts.csv.gz"))[variant %in% c(VARIANT, "seasonal")][, start := as.IDate(start)]
both <- rbind(base, ffc[, names(base), with = FALSE])
al <- add_alerts(both); te <- al$test

# ---- Scores ----------------------------------------------------------------------------
cnt <- score_counts(groups(te), c("variant", "h", "grp"))
fwrite(cnt[order(grp, h, variant)], file.path(OUT7, "forecast_count_scores.csv"))
alr <- score_alerts(groups(te), c("variant", "h", "grp"))
fwrite(alr[order(threshold, grp, h, variant)], file.path(OUT7, "forecast_alert_scores.csv"))

auc <- function(p, a) { ok <- !is.na(p) & !is.na(a); p <- p[ok]; a <- a[ok]; n1 <- sum(a); n0 <- sum(!a)
  if (!n1 || !n0) return(NA_real_); (sum(rank(p)[a]) - n1 * (n1 + 1) / 2) / (n1 * n0) }
x <- te[include == TRUE & !is.na(above_exc5)]
auc_tab <- rbind(
  x[, .(scope = "All weeks, all cities", auc = auc(p_exc5, above_exc5)), by = .(variant, h)],
  x[, .(auc = auc(p_exc5, above_exc5), ob = sum(above_exc5)), by = .(variant, h, city)][ob >= 5, .(scope = "Within each city (mean of 9)", auc = mean(auc, na.rm = TRUE)), by = .(variant, h)],
  x[mw %between% c(22, 45), .(auc = auc(p_exc5, above_exc5), ob = sum(above_exc5)), by = .(variant, h, city)][ob >= 5, .(scope = "Within city, rainy season", auc = mean(auc, na.rm = TRUE)), by = .(variant, h)])
fwrite(auc_tab[order(scope, h, variant)], file.path(OUT7, "forecast_auc.csv"))
auc_city <- x[h == 1, .(auc = auc(p_exc5, above_exc5), outbreak_weeks = sum(above_exc5)), by = .(variant, city)]
fwrite(dcast(auc_city, city + outbreak_weeks ~ variant, value.var = "auc", fun.aggregate = mean, fill = NA)[order(-outbreak_weeks)], file.path(OUT7, "forecast_auc_by_city.csv"))

# fixed cut-offs (descriptive) for precision
fixed <- rbindlist(lapply(c(0.10, 0.20, 0.30), function(cc) x[h <= 2, .(cut = cc, alerts = sum(p_exc5 >= cc, na.rm = TRUE),
  sensitivity = mean(p_exc5[above_exc5] >= cc, na.rm = TRUE), precision = sum(p_exc5 >= cc & above_exc5, na.rm = TRUE) / sum(p_exc5 >= cc, na.rm = TRUE),
  false_alarms_per_city_year = sum(p_exc5 >= cc & !above_exc5, na.rm = TRUE) / uniqueN(paste(city, year))), by = .(variant, h)]))
fwrite(fixed[order(cut, h, variant)], file.path(OUT7, "forecast_fixed_cutoffs.csv"))

# paired comparison of log score, block bootstrap over city-years
set.seed(2024)
ls_cy <- te[include == TRUE & !is.na(y), .(ls = -sum(dnbinom(y, size = theta, mu = mu, log = TRUE)), n = .N), by = .(variant, h, city, year)]
cmp <- rbindlist(lapply(HORIZONS, function(hh) {
  w <- dcast(ls_cy[h == hh & variant %in% c(VARIANT, "pooled_ar_flood")], city + year + n ~ variant, value.var = "ls"); w <- w[complete.cases(w)]
  dd_ <- w[[VARIANT]] - w[["pooled_ar_flood"]]
  bt <- replicate(2000, { i <- sample(nrow(w), replace = TRUE); sum(dd_[i]) / sum(w$n[i]) })
  data.table(h = hh, gain_per_week = sum(dd_) / sum(w$n), lo = quantile(bt, .025), hi = quantile(bt, .975),
             city_years_better = sum(dd_ > 0), city_years = nrow(w))
}))
fwrite(cmp, file.path(OUT7, "forecast_paired_comparison.csv"))
city_ls <- dcast(te[include == TRUE & !is.na(y) & h %in% 1:2, .(ls = -mean(dnbinom(y, size = theta, mu = mu, log = TRUE))), by = .(variant, city)], city ~ variant, value.var = "ls")
city_ls[, gain := get(VARIANT) - pooled_ar_flood]
fwrite(city_ls[order(-gain)], file.path(OUT7, "forecast_logscore_by_city.csv"))

print(unique(ffc[, .(origin, h, g, lr_train)])[order(h, origin)])
print(cmp); print(auc_tab[order(scope, h, variant)]); print(alr[grp == "All cities" & threshold == "Outbreak-excluded"][order(h, variant)])
print(fixed[order(cut, h, variant)]); print(city_ls[order(-gain)])

# ---- Figure: g estimated on each training window ----------------------------------------
gg <- unique(ffc[, .(origin, h, g)])
p <- ggplot(gg, aes(origin + 1, g, colour = factor(h))) + geom_hline(yintercept = 0, colour = GREY) + geom_line(linewidth = 0.8) + geom_point(size = 2) +
  scale_colour_manual(values = c(`1` = BLUE, `2` = AQUA, `3` = ORANGE, `4` = VIOLET), name = "Weeks ahead") +
  scale_x_continuous(breaks = ORIGINS + 1) +
  labs(x = "Test year (g estimated on 2008 to the year before)", y = "g (rain-effect change per 10 points flood exposure)")
ggsave(file.path(FIG7, "forecast_g_by_origin.png"), p, width = 9, height = 3.8, dpi = 150, bg = "white")
log_step("Done")
