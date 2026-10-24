# =============================================================================
# 07g_glofas_forecast.R  —  Stage 7c, step 4: does river flow improve the forecasts?
#
# Same rolling-origin test as Stage 5 (train 2008..Y, forecast Y+1, Y = 2013..2021, 1-4 weeks ahead, IMERG
# Late, 1-week reporting delay). Base = the final model (pooled rain + recent level + case history,
# "pooled_ar4_lvl"). River versions add the weekly GloFAS river signal, known at forecast time:
#   _riv    : crossbasis over lags h..10 (like rain), river cities only        (main, form 1)
#   _rivs   : mean river signal over lags h..h+3, 3-df spline, river cities only (main, form 2)
#   _riv12 / _rivs12 : the same in all 12 cities (check)
# Rain stays in every model. Scores: log score (paired block bootstrap vs base), AUC within city, the final
# risk levels (one cut-off for all cities, set on training years as in Stage 5d), by city.
# Outputs: output/stage7/river_forecast_*.csv, output/stage7/forecasts_river.csv.gz, figs
# =============================================================================
src5 <- readLines("R/05_validation.R")
eval(parse(text = src5[1:(grep("^# ---- Run \\(or reuse\\)", src5) - 1)]))
eval(parse(text = src5[grep("^run_jobs <- function", src5):(grep("^if \\(!file.exists\\(FC\\)", src5) - 1)]))
OUT7 <- file.path(PATHS$out, "stage7"); FIG7 <- file.path(OUT7, "figs")
BASE <- "pooled_ar4_lvl"; NEWV <- paste0(BASE, c("_riv", "_rivs", "_riv12", "_rivs12"))
VL <- c(pooled_ar4_lvl = "Final model (no river)", pooled_ar4_lvl_riv = "+ river, like rain (river cities)",
        pooled_ar4_lvl_rivs = "+ river, simple (river cities)", pooled_ar4_lvl_riv12 = "+ river, like rain (all 12)",
        pooled_ar4_lvl_rivs12 = "+ river, simple (all 12)")
RIVER_CITIES <- fread(file.path(PATHS$processed, "glofas_city_week.csv"))[river_used == TRUE, unique(city)]

FR <- file.path(OUT7, "forecasts_river.csv.gz")
if (!file.exists(FR) || Sys.getenv("STAGE7C_REFIT") == "1") {
  jobs <- CJ(origin = ORIGINS, h = HORIZONS, variant = NEWV)[, `:=`(rain_train = MAIN_RAIN, rain_test = MAIN_RAIN, delay = DELAY)]
  log_step("River forecast runs:", nrow(jobs), "fits on", CORES, "cores")
  fr <- run_jobs(jobs); fwrite(fr, FR)
} else fr <- fread(FR)
base <- fread(file.path(OUT, "forecasts_settings.csv.gz"))[variant == BASE]
cols <- intersect(names(base), names(fr))
allf <- rbind(base[, ..cols], fr[, ..cols])[!is.na(thr_exc5)]
allf[, p := 1 - pnbinom(floor(thr_exc5 * days / 7), size = theta, mu = mu)]
allf <- allf[!is.na(p)]
fwrite(unique(fr[, .(origin, h, variant, converged)])[converged == FALSE], file.path(OUT7, "river_forecast_not_converged.csv"))

te <- allf[set == "test" & include == TRUE & !is.na(y) & !is.na(above_exc5)]
key <- te[, .N, by = .(city, start, h)][N == uniqueN(te$variant), .(city, start, h)]
te <- merge(te, key, by = c("city", "start", "h"))
te[, river_city := city %in% RIVER_CITIES]

auc <- function(p, a) { n1 <- sum(a); n0 <- sum(!a); if (n1 < 1 || !n0) return(NA_real_); (sum(rank(p)[a]) - n1 * (n1 + 1) / 2) / (n1 * n0) }
score <- function(x) x[, { ac <- .SD[, .(a = auc(p, above_exc5), n = sum(above_exc5)), by = city][n >= 5]
  .(weeks = .N, auc_within_city = mean(ac$a), auc_all = auc(p, above_exc5), log_score = -mean(dnbinom(y, size = theta, mu = mu, log = TRUE))) },
  by = .(variant, h)]
summ <- rbind(score(te)[, cities := "All cities"], score(te[river_city == TRUE])[, cities := "River cities"], score(te[river_city == FALSE])[, cities := "Other cities"])
fwrite(summ[order(cities, h, variant)], file.path(OUT7, "river_forecast_summary.csv"))

# paired log-score comparison vs base (block bootstrap over city-years)
set.seed(2024)
ls_cy <- te[, .(ls = -sum(dnbinom(y, size = theta, mu = mu, log = TRUE)), n = .N, river_city = river_city[1]), by = .(variant, h, city, year)]
cmp <- rbindlist(lapply(NEWV, function(v) rbindlist(lapply(c("All cities", "River cities"), function(g) rbindlist(lapply(HORIZONS, function(hh) {
  w <- dcast(ls_cy[h == hh & variant %in% c(BASE, v) & (g == "All cities" | river_city)], city + year + n ~ variant, value.var = "ls"); w <- w[complete.cases(w)]
  dd_ <- w[[BASE]] - w[[v]]
  bt <- replicate(2000, { i <- sample(nrow(w), replace = TRUE); sum(dd_[i]) / sum(w$n[i]) })
  data.table(variant = v, cities = g, h = hh, gain_per_week = sum(dd_) / sum(w$n), lo = quantile(bt, .025), hi = quantile(bt, .975),
             city_years_better = sum(dd_ > 0), city_years = nrow(w))
}))))))
fwrite(cmp, file.path(OUT7, "river_forecast_paired.csv"))

# risk levels (one cut-off for all cities, from training years: top 5% Warning, next 15% Watch)
tr <- allf[set == "train"]
cuts <- tr[, .(watch = quantile(p, 0.80), warn = quantile(p, 0.95)), by = .(variant, origin, h)]
lv <- merge(te, cuts, by = c("variant", "origin", "h"))
lv[, level := factor(fifelse(p >= warn, "Warning", fifelse(p >= watch, "Watch", "Normal")), levels = c("Normal", "Watch", "Warning"))]
rl <- lv[h <= 2, { ncy <- uniqueN(paste(city, year))
  .(warning_rate = mean(above_exc5[level == "Warning"]), watch_rate = mean(above_exc5[level == "Watch"]), normal_rate = mean(above_exc5[level == "Normal"]),
    caught = mean(level[above_exc5] != "Normal"), caught_warning = mean(level[above_exc5] == "Warning"),
    false_alarms_per_city_year = sum(level != "Normal" & !above_exc5) / ncy) }, by = .(variant, h)]
fwrite(rl[order(h, variant)], file.path(OUT7, "river_forecast_risk_levels.csv"))
bycity <- te[h == 1, .(outbreak_weeks = sum(above_exc5), auc = auc(p, above_exc5),
                       yearly_bias = { yr <- .SD[, .(o = sum(y), f = sum(mu)), by = year]; sum(yr$f - yr$o) / sum(yr$o) }), by = .(variant, city, river_city)]
fwrite(bycity, file.path(OUT7, "river_forecast_by_city.csv"))

options(width = 220)
print(summ[h <= 2][order(cities, h, variant), .(cities, h, variant, auc_w = round(auc_within_city, 3), auc_all = round(auc_all, 3), ls = round(log_score, 4))])
print(cmp[, .(variant, cities, h, gain = round(gain_per_week, 4), lo = round(lo, 4), hi = round(hi, 4), better = paste0(city_years_better, "/", city_years))])
print(rl[, lapply(.SD, function(v) if (is.numeric(v)) round(v, 3) else v)])
print(dcast(bycity, city + river_city + outbreak_weeks ~ variant, value.var = "auc")[order(-river_city, -outbreak_weeks), lapply(.SD, function(v) if (is.numeric(v)) round(v, 3) else v)])
print(dcast(bycity, city ~ variant, value.var = "yearly_bias")[, lapply(.SD, function(v) if (is.numeric(v)) round(v, 2) else v)])

# ---- figure: AUC within city by horizon ---------------------------------------------------------------
pl <- summ[cities != "Other cities"]; pl[, lab := factor(VL[variant], levels = VL)]
p <- ggplot(pl, aes(h, auc_within_city, colour = lab)) + geom_line(linewidth = 0.9) + geom_point(size = 2) + facet_wrap(~cities) +
  scale_colour_manual(values = c("#0b0b0b", "#2a78d6", "#1baf7a", "#9ec5f0", "#a8e0c9"), name = NULL) +
  scale_x_continuous(breaks = HORIZONS) + guides(colour = guide_legend(nrow = 2)) +
  theme_minimal(base_size = 10) + theme(legend.position = "top", panel.grid.minor = element_blank(), strip.text = element_text(face = "bold", hjust = 0)) +
  labs(x = "Forecast horizon (weeks ahead)", y = "AUC within city (higher is better)")
ggsave(file.path(FIG7, "river_forecast_auc.png"), p, width = 9, height = 4.2, dpi = 150, bg = "white")
log_step("Done")
