# =============================================================================
# 05c_settings.R  —  Stage 5c: do better model settings close the gap found by the ceiling test?
#
# Same rolling-origin test as Stage 5 (train 2008..Y, forecast Y+1, Y = 2013..2021, 1-4 weeks ahead,
# IMERG Late, 1-week reporting delay), recommended model "pooled_ar" plus:
#   pooled_ar4      + case history: mean of the 3 weeks before the last known week
#   pooled_ar_lvl   + recent level: each city's case rate over the last 52 known weeks, replacing the spline trend
#   pooled_ar4_lvl  both
# Compared with pooled_ar (forecasts from Stage 5) on the same weeks.
# Outputs: output/stage5/settings_*.csv, output/stage5/forecasts_settings.csv.gz, figs/settings_*.png
# =============================================================================

src5 <- readLines("R/05_validation.R")
eval(parse(text = src5[1:(grep("^# ---- Run \\(or reuse\\)", src5) - 1)]))
eval(parse(text = src5[grep("^p_exceed <- ", src5):(grep("^al <- add_alerts\\(fc\\)", src5) - 1)]))
eval(parse(text = src5[grep("^run_jobs <- function", src5):(grep("^if \\(!file.exists\\(FC\\)", src5) - 1)]))   # run_jobs()
NEW <- c("pooled_ar4", "pooled_ar_lvl", "pooled_ar4_lvl")
VL <- c(seasonal = "Seasonal only", pooled_ar = "Current (rain + last week's cases)", pooled_ar4 = "+ case history (3 earlier weeks)",
        pooled_ar_lvl = "+ recent level (replaces trend)", pooled_ar4_lvl = "+ both")
BLUE <- "#2a78d6"; ORANGE <- "#eb6834"; AQUA <- "#1baf7a"; GREY <- "#8a8984"; VIOLET <- "#6250d6"; INK <- "#0b0b0b"
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top", plot.title.position = "plot",
                                                strip.text = element_text(face = "bold", hjust = 0)))

FS <- file.path(OUT, "forecasts_settings.csv.gz")
if (!file.exists(FS) || Sys.getenv("STAGE5C_REFIT") == "1") {
  jobs <- CJ(origin = ORIGINS, h = HORIZONS, variant = NEW)[, `:=`(rain_train = MAIN_RAIN, rain_test = MAIN_RAIN, delay = DELAY)]
  log_step("Settings runs:", nrow(jobs), "fits on", CORES, "cores")
  fs <- run_jobs(jobs); fwrite(fs, FS)
} else fs <- fread(FS)
fs[, start := as.IDate(start)]
base <- fread(file.path(OUT, "forecasts.csv.gz"))[variant %in% c("pooled_ar", "seasonal")][, start := as.IDate(start)]
cols <- intersect(names(base), names(fs))
allf <- rbind(base[, ..cols], fs[, ..cols])
te <- add_alerts(allf)$test
fwrite(unique(fs[, .(origin, h, variant, converged, optimiser)])[converged == FALSE], file.path(OUT, "settings_not_converged.csv"))

# ---- scores -------------------------------------------------------------------------------
auc <- function(p, a) { ok <- !is.na(p) & !is.na(a); p <- p[ok]; a <- a[ok]; n1 <- sum(a); n0 <- sum(!a)
  if (!n1 || !n0) return(NA_real_); (sum(rank(p)[a]) - n1 * (n1 + 1) / 2) / (n1 * n0) }
x <- te[include == TRUE & !is.na(y) & !is.na(above_exc5) & !is.na(p_exc5)]
# same weeks for every variant (recent-level variants need 52 earlier weeks, so compare on common weeks)
key <- x[, .N, by = .(city, start, h)][N == uniqueN(x$variant), .(city, start, h)]
x <- merge(x, key, by = c("city", "start", "h"))
summ <- x[, {
  ac <- .SD[, .(a = auc(p_exc5, above_exc5), n = sum(above_exc5)), by = city][n >= 5]
  yr <- .SD[, .(o = sum(y), f = sum(mu)), by = .(city, year)]
  .(weeks = .N, auc_within_city = mean(ac$a), auc_all = auc(p_exc5, above_exc5),
    log_score = -mean(dnbinom(y, size = theta, mu = mu, log = TRUE)),
    weekly_error = sum(abs(y - mu)) / sum(y), yearly_error = sum(abs(yr$o - yr$f)) / sum(yr$o),
    prec20 = sum(p_exc5 >= .2 & above_exc5) / sum(p_exc5 >= .2), sens20 = sum(p_exc5 >= .2 & above_exc5) / sum(above_exc5),
    fa20 = sum(p_exc5 >= .2 & !above_exc5) / uniqueN(paste(city, year)),
    prec10 = sum(p_exc5 >= .1 & above_exc5) / sum(p_exc5 >= .1), sens10 = sum(p_exc5 >= .1 & above_exc5) / sum(above_exc5),
    fa10 = sum(p_exc5 >= .1 & !above_exc5) / uniqueN(paste(city, year)))
}, by = .(variant, h)]
fwrite(summ[order(h, match(variant, names(VL)))], file.path(OUT, "settings_summary.csv"))

# paired log-score comparison vs current, block bootstrap over city-years
set.seed(2024)
ls_cy <- x[, .(ls = -sum(dnbinom(y, size = theta, mu = mu, log = TRUE)), n = .N), by = .(variant, h, city, year)]
cmp <- rbindlist(lapply(NEW, function(v) rbindlist(lapply(HORIZONS, function(hh) {
  w <- dcast(ls_cy[h == hh & variant %in% c("pooled_ar", v)], city + year + n ~ variant, value.var = "ls"); w <- w[complete.cases(w)]
  dd_ <- w[["pooled_ar"]] - w[[v]]
  bt <- replicate(2000, { i <- sample(nrow(w), replace = TRUE); sum(dd_[i]) / sum(w$n[i]) })
  data.table(variant = v, h = hh, gain_per_week = sum(dd_) / sum(w$n), lo = quantile(bt, .025), hi = quantile(bt, .975),
             city_years_better = sum(dd_ > 0), city_years = nrow(w))
}))))
fwrite(cmp, file.path(OUT, "settings_paired_comparison.csv"))

# by city: within-city AUC, yearly error and bias, 1 week ahead
bycity <- x[h == 1, { yr <- .SD[, .(o = sum(y), f = sum(mu)), by = year]
  .(outbreak_weeks = sum(above_exc5), auc = auc(p_exc5, above_exc5), yearly_error = sum(abs(yr$o - yr$f)) / sum(yr$o), bias = sum(yr$f - yr$o) / sum(yr$o)) },
  by = .(variant, city)]
fwrite(bycity, file.path(OUT, "settings_by_city.csv"))
ceil <- fread(file.path(OUT, "ceiling_summary.csv"))

print(summ[order(h, match(variant, names(VL)))]); print(cmp)
print(dcast(bycity, city + outbreak_weeks ~ variant, value.var = "auc")[order(-outbreak_weeks)])
print(dcast(bycity, city ~ variant, value.var = "bias"))

# ---- figures --------------------------------------------------------------------------------
VCOL <- c(seasonal = GREY, pooled_ar = INK, pooled_ar4 = BLUE, pooled_ar_lvl = ORANGE, pooled_ar4_lvl = AQUA)
pl <- melt(summ, id.vars = c("variant", "h"), measure.vars = c("auc_within_city", "prec20", "yearly_error"))
pl[, variable := factor(variable, levels = c("auc_within_city", "prec20", "yearly_error"),
                        labels = c("AUC within city (higher better)", "Alerts real at 20% cut-off (higher better)", "Yearly % error (lower better)"))]
hl <- data.table(variable = factor(levels(pl$variable)[1:3], levels = levels(pl$variable)),
                 y = c(ceil[level %like% "^2", auc_within_city], NA, ceil[level %like% "^2", yearly_error]))
p <- ggplot(pl, aes(h, value, colour = variant)) + geom_line(linewidth = 0.9) + geom_point(size = 2) +
  geom_hline(data = hl[!is.na(y)], aes(yintercept = y), linetype = "dashed", colour = GREY) +
  facet_wrap(~variable, scales = "free_y") + scale_colour_manual(values = VCOL, labels = VL, name = NULL) +
  scale_x_continuous(breaks = HORIZONS) + guides(colour = guide_legend(nrow = 2)) +
  labs(x = "Forecast horizon (weeks ahead)", y = NULL, caption = "Dashed: hindsight model from the ceiling test")
ggsave(file.path(FIG, "settings_comparison.png"), p, width = 10, height = 4.2, dpi = 150, bg = "white")
log_step("Done")
