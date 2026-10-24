# =============================================================================
# 05e_washi_setaside.R  —  does setting Typhoon Washi aside fix the Cagayan de Oro over-forecast?
#
# Same rolling-origin test as Stage 5 (train 2008..Y, forecast Y+1, Y = 2013..2021, 1-4 weeks ahead, IMERG Late,
# 1-week reporting delay). Base = the final model ("pooled_ar4_lvl"). New = the same model with Washi's 5 outbreak
# weeks in Cagayan de Oro (18 Dec 2011 - 21 Jan 2012) set aside as training outcomes ("pooled_ar4_lvl_nw"); those
# weeks still count as recent case history.
# Scores: log score (paired block bootstrap), AUC within city, risk levels (Stage 5d rule), Cagayan de Oro's yearly
# and December-January error, results by city.
# Outputs: output/stage5/washi_*.csv, output/stage5/forecasts_washi.csv.gz, figs/washi_cdo_seasonal.png
# =============================================================================
src5 <- readLines("R/05_validation.R")
eval(parse(text = src5[1:(grep("^# ---- Run \\(or reuse\\)", src5) - 1)]))
eval(parse(text = src5[grep("^run_jobs <- function", src5):(grep("^if \\(!file.exists\\(FC\\)", src5) - 1)]))
BASE <- "pooled_ar4_lvl"; NEWV <- "pooled_ar4_lvl_nw"
VL <- c(pooled_ar4_lvl = "Final model", pooled_ar4_lvl_nw = "Final model, Washi set aside")
FW <- file.path(OUT, "forecasts_washi.csv.gz")
if (!file.exists(FW) || Sys.getenv("STAGE5E_REFIT") == "1") {
  jobs <- CJ(origin = ORIGINS, h = HORIZONS, variant = NEWV)[, `:=`(rain_train = MAIN_RAIN, rain_test = MAIN_RAIN, delay = DELAY)]
  log_step("Washi set-aside runs:", nrow(jobs), "fits on", CORES, "cores")
  fw <- run_jobs(jobs); fwrite(fw, FW)
} else fw <- fread(FW)
base <- fread(file.path(OUT, "forecasts_settings.csv.gz"))[variant == BASE]
cols <- intersect(names(base), names(fw))
allf <- rbind(base[, ..cols], fw[, ..cols])[!is.na(thr_exc5)]
allf[, p := 1 - pnbinom(floor(thr_exc5 * days / 7), size = theta, mu = mu)]
allf <- allf[!is.na(p)]
fwrite(unique(fw[, .(origin, h, variant, converged)])[converged == FALSE], file.path(OUT, "washi_not_converged.csv"))

te <- allf[set == "test" & include == TRUE & !is.na(y) & !is.na(above_exc5)]
key <- te[, .N, by = .(city, start, h)][N == uniqueN(te$variant), .(city, start, h)]
te <- merge(te, key, by = c("city", "start", "h"))
te[, cdo := city == "Cagayan de Oro"]

auc <- function(p, a) { n1 <- sum(a); n0 <- sum(!a); if (n1 < 1 || !n0) return(NA_real_); (sum(rank(p)[a]) - n1 * (n1 + 1) / 2) / (n1 * n0) }
score <- function(x) x[, { ac <- .SD[, .(a = auc(p, above_exc5), n = sum(above_exc5)), by = city][n >= 5]
  .(weeks = .N, auc_within_city = mean(ac$a), auc_all = auc(p, above_exc5), log_score = -mean(dnbinom(y, size = theta, mu = mu, log = TRUE)),
    yearly_error = { yr <- .SD[, .(o = sum(y), f = sum(mu)), by = .(city, year)]; mean(abs(yr$f - yr$o) / pmax(yr$o, 1)) }) }, by = .(variant, h)]
summ <- rbind(score(te)[, cities := "All cities"], score(te[cdo == FALSE])[, cities := "Other 11 cities"])
fwrite(summ[order(cities, h, variant)], file.path(OUT, "washi_summary.csv"))

set.seed(2024)
ls_cy <- te[, .(ls = -sum(dnbinom(y, size = theta, mu = mu, log = TRUE)), n = .N, cdo = cdo[1]), by = .(variant, h, city, year)]
cmp <- rbindlist(lapply(c("All cities", "Cagayan de Oro", "Other 11 cities"), function(g) rbindlist(lapply(HORIZONS, function(hh) {
  w <- dcast(ls_cy[h == hh & (g == "All cities" | (g == "Cagayan de Oro") == cdo)], city + year + n ~ variant, value.var = "ls"); w <- w[complete.cases(w)]
  dd_ <- w[[BASE]] - w[[NEWV]]
  bt <- replicate(2000, { i <- sample(nrow(w), replace = TRUE); sum(dd_[i]) / sum(w$n[i]) })
  data.table(cities = g, h = hh, gain_per_week = sum(dd_) / sum(w$n), lo = quantile(bt, .025), hi = quantile(bt, .975),
             city_years_better = sum(dd_ > 0), city_years = nrow(w))
}))))
fwrite(cmp, file.path(OUT, "washi_paired.csv"))

# risk levels (one cut-off for all cities from training forecasts: top 5% Warning, next 15% Watch)
cuts <- allf[set == "train", .(watch = quantile(p, 0.80), warn = quantile(p, 0.95)), by = .(variant, origin, h)]
lv <- merge(te, cuts, by = c("variant", "origin", "h"))
lv[, level := factor(fifelse(p >= warn, "Warning", fifelse(p >= watch, "Watch", "Normal")), levels = c("Normal", "Watch", "Warning"))]
rl_f <- function(x) x[h <= 2, { ncy <- uniqueN(paste(city, year))
  .(warning_rate = mean(above_exc5[level == "Warning"]), watch_rate = mean(above_exc5[level == "Watch"]), normal_rate = mean(above_exc5[level == "Normal"]),
    caught = mean(level[above_exc5] != "Normal"), caught_warning = mean(level[above_exc5] == "Warning"),
    false_alarms_per_city_year = sum(level != "Normal" & !above_exc5) / ncy, outbreak_weeks = sum(above_exc5)) }, by = .(variant, h)]
rl <- rbind(rl_f(lv)[, cities := "All cities"], rl_f(lv[cdo == TRUE])[, cities := "Cagayan de Oro"])
fwrite(rl[order(cities, h, variant)], file.path(OUT, "washi_risk_levels.csv"))

# Cagayan de Oro: yearly totals and December-January vs the rest of the year
cd <- te[cdo == TRUE & h == 1]
cd[, season := fifelse(month(as.IDate(start)) %in% c(12, 1), "December-January", "February-November")]
cdo_season <- cd[, .(observed = sum(y), forecast = round(sum(mu), 1)), by = .(variant, season)][, error := round(forecast / observed - 1, 2)]
cdo_year <- dcast(cd[, .(f = round(sum(mu), 1), o = sum(y)), by = .(variant, year)], year + o ~ variant, value.var = "f")
setnames(cdo_year, "o", "observed")
cdo_tot <- cd[, .(observed = sum(y), forecast = sum(mu)), by = variant][, error := forecast / observed - 1]
fwrite(cdo_season, file.path(OUT, "washi_cdo_season.csv")); fwrite(cdo_year, file.path(OUT, "washi_cdo_by_year.csv"))
bycity <- te[h == 1, .(outbreak_weeks = sum(above_exc5), auc = auc(p, above_exc5),
                       yearly_bias = { yr <- .SD[, .(o = sum(y), f = sum(mu)), by = year]; sum(yr$f - yr$o) / sum(yr$o) }), by = .(variant, city)]
fwrite(bycity, file.path(OUT, "washi_by_city.csv"))

options(width = 200)
print(summ[h <= 2][order(cities, h, variant), .(cities, h, variant, auc_w = round(auc_within_city, 3), auc_all = round(auc_all, 3), ls = round(log_score, 4), yearly_error = round(yearly_error, 3))])
print(cmp[, .(cities, h, gain = round(gain_per_week, 4), lo = round(lo, 4), hi = round(hi, 4), better = paste0(city_years_better, "/", city_years))])
print(rl[, lapply(.SD, function(v) if (is.numeric(v)) round(v, 3) else v)])
print(cdo_tot); print(cdo_season); print(cdo_year)
print(dcast(bycity, city + outbreak_weeks ~ variant, value.var = c("auc", "yearly_bias"))[, lapply(.SD, function(v) if (is.numeric(v)) round(v, 3) else v)])

# ---- figure: Cagayan de Oro forecasts by month, with and without Washi set aside --------------------------
mo <- te[cdo == TRUE & h == 1, .(forecast = sum(mu)), by = .(variant, m = month(as.IDate(start)))]
ob <- te[cdo == TRUE & h == 1 & variant == BASE, .(observed = sum(y)), by = .(m = month(as.IDate(start)))]
p <- ggplot() + geom_col(data = ob, aes(m, observed), fill = "#c9c8c2", width = 0.7) +
  geom_line(data = mo, aes(m, forecast, colour = VL[variant]), linewidth = 0.9) + geom_point(data = mo, aes(m, forecast, colour = VL[variant]), size = 2) +
  scale_colour_manual(values = c("#eb6834", "#0b0b0b"), name = NULL) + scale_x_continuous(breaks = 1:12, labels = month.abb) +
  theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top") +
  labs(x = NULL, y = "Cases, 2014–2022 total", subtitle = "Cagayan de Oro: reported cases (bars) and 1-week-ahead forecasts (lines) by month, rolling-origin test years")
ggsave(file.path(FIG, "washi_cdo_seasonal.png"), p, width = 8, height = 4, dpi = 150, bg = "white")
log_step("Done")
