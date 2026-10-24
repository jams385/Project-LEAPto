# =============================================================================
# 05b_ceiling.R  —  How good could any forecast be? (ceiling test for Stage 5)
#
# Compares, on the Stage 5 test weeks (2014-2022, outbreak-excluded 5-year threshold):
#   1. Current forecast     : Stage 5 model (pooled rain + last week's cases), 1 week ahead, out of sample
#   2. Hindsight model      : Stage 3 main model fitted on ALL years (incl. the test years), scored on real outbreaks
#   3. Ceiling B            : counts simulated from the hindsight model (negative binomial); forecaster knows the
#                             hindsight expected count mu -> limit for any model that sees what this one sees
#   4. Ceiling A (absolute) : same simulation, but the forecaster knows each week's TRUE rate (mu x the random
#                             week-to-week burst that the negative binomial adds) -> only chance remains, i.e.
#                             which of the people at risk happen to get sick and be reported that week
# Scores: AUC within each city, precision/sensitivity at fixed cut-offs, weekly and yearly % error.
# Ceilings are averaged over N_SIM simulated histories.
# Outputs: output/stage5/ceiling_*.csv, output/stage5/figs/ceiling.png
# =============================================================================

src3 <- readLines("R/03_dlnm.R"); eval(parse(text = src3[1:(grep("^d <- prep\\(\\)", src3) - 1)]))
OUT5 <- file.path(PATHS$out, "stage5"); set.seed(20261022)
N_SIM <- 200L; CUTS <- c(0.10, 0.20, 0.30)
M3 <- readRDS(file.path(PATHS$out, "stage3", "main_model.rds"))$spec

# ---- hindsight model ----------------------------------------------------------------
log_step("Fitting hindsight model (Stage 3 main, all years)")
d <- prep()
fm <- fit_dlnm(d, L = M3$L, var_q = VAR_SPECS[[M3$var]], nk = M3$nk)
m <- fm$data
m[, mu := predict(fm$model, type = "response")]
th <- exp(fixef(fm$model)$disp); names(th) <- sub("^dgrp", "", names(th)); m[, theta := th[as.character(dgrp)]]
thr <- fread(file.path(PATHS$out, "stage4", "thresholds_weekly.csv"))[, .(city, year, mw, thr_exc5, above_exc5)]
x <- merge(m[, .(city = as.character(city), year, mw, days, y, mu, theta)], thr, by = c("city", "year", "mw"))
x <- x[year %between% c(2014, 2022) & !is.na(thr_exc5)]
x[, k := floor(thr_exc5 * days / 7)]                           # outbreak week = count above k
stopifnot(all(x$above_exc5 == (x$y > x$k)))

# ---- scoring -----------------------------------------------------------------------------
auc <- function(p, a) { n1 <- sum(a); n0 <- sum(!a); if (n1 < 1 || !n0) return(NA_real_); (sum(rank(p)[a]) - n1 * (n1 + 1) / 2) / (n1 * n0) }
score <- function(p, a, mean_fc, yy, city, year) {
  dt <- data.table(p, a, mean_fc, yy, city, year)
  ac <- dt[, .(auc = auc(p, a), n = sum(a)), by = city][n >= 5]
  fx <- rbindlist(lapply(CUTS, function(c) dt[, .(cut = c, sensitivity = sum(p >= c & a) / sum(a), precision = sum(p >= c & a) / max(1, sum(p >= c)),
                                                 false_alarms = sum(p >= c & !a) / uniqueN(paste(city, year)))]))
  yr <- dt[, .(o = sum(yy), f = sum(mean_fc)), by = .(city, year)]
  list(main = data.table(auc_within_city = mean(ac$auc), auc_all = auc(dt$p, dt$a), outbreak_share = mean(dt$a),
                         weekly_error = sum(abs(dt$yy - dt$mean_fc)) / sum(dt$yy), yearly_error = sum(abs(yr$o - yr$f)) / sum(yr$o)),
       cuts = fx)
}
pnb <- function(k, mu, theta) 1 - pnbinom(k, size = theta, mu = mu)

# 1. current forecast (Stage 5, out of sample, 1 week ahead)
fc <- fread(file.path(OUT5, "forecasts.csv.gz"))[set == "test" & variant == "pooled_ar" & h == 1 & include == TRUE & !is.na(above_exc5) & !is.na(y)]
fc[, p := pnb(floor(thr_exc5 * days / 7), mu, theta)]; fc <- fc[!is.na(p)]
s1 <- score(fc$p, fc$above_exc5, fc$mu, fc$y, fc$city, fc$year)
# 2. hindsight model on the real outbreaks
s2 <- score(pnb(x$k, x$mu, x$theta), x$above_exc5, x$mu, x$y, x$city, x$year)

# 3-4. simulated histories
log_step("Simulating", N_SIM, "histories")
sims <- lapply(seq_len(N_SIM), function(i) {
  lam <- x$mu * rgamma(nrow(x), shape = x$theta, rate = x$theta)  # true weekly rate incl. bursts (NB = Poisson-gamma)
  ys <- rpois(nrow(x), lam); a <- ys > x$k
  list(B = score(pnb(x$k, x$mu, x$theta), a, x$mu, ys, x$city, x$year),
       A = score(1 - ppois(x$k, lam), a, lam, ys, x$city, x$year))
})
avg <- function(which, part) { r <- rbindlist(lapply(sims, function(s) s[[which]][[part]])); if (part == "main") r[, lapply(.SD, mean)] else r[, lapply(.SD, mean), by = cut] }
lvl <- c("1. Current forecast (1 week ahead)", "2. Hindsight model (all years, real outbreaks)", "3. Ceiling B (knows hindsight risk)", "4. Ceiling A (knows true weekly rate)")
main <- rbind(cbind(level = lvl[1], s1$main), cbind(level = lvl[2], s2$main), cbind(level = lvl[3], avg("B", "main")), cbind(level = lvl[4], avg("A", "main")))
cuts <- rbind(cbind(level = lvl[1], s1$cuts), cbind(level = lvl[2], s2$cuts), cbind(level = lvl[3], avg("B", "cuts")), cbind(level = lvl[4], avg("A", "cuts")))
# spread of the ceilings across simulated histories
spread <- rbindlist(lapply(c("B", "A"), function(w) { r <- rbindlist(lapply(sims, function(s) s[[w]]$main))
  data.table(level = if (w == "B") lvl[3] else lvl[4], auc_within_lo = quantile(r$auc_within_city, .05), auc_within_hi = quantile(r$auc_within_city, .95)) }))
fwrite(main, file.path(OUT5, "ceiling_summary.csv")); fwrite(cuts, file.path(OUT5, "ceiling_cutoffs.csv")); fwrite(spread, file.path(OUT5, "ceiling_spread.csv"))
print(main); print(cuts[order(cut, level)]); print(spread)

# ---- figure ----------------------------------------------------------------------------------
BL <- c("#8a8984", "#6fa3e3", "#2a78d6", "#0b0b0b")
pl <- melt(main[, .(level, `AUC within city` = auc_within_city)], id.vars = "level")
pc <- cuts[cut == 0.20, .(level, `Alerts real at 20% cut-off` = precision, `Outbreak weeks caught at 20%` = sensitivity)]
pl <- rbind(pl, melt(pc, id.vars = "level"))
pl[, level := factor(level, levels = lvl)]
p <- ggplot(pl, aes(level, value, fill = level)) + geom_col(width = 0.7) + geom_text(aes(label = sprintf("%.2f", value)), vjust = -0.3, size = 3) +
  facet_wrap(~variable, scales = "free_y") + scale_fill_manual(values = BL, guide = "none") +
  scale_x_discrete(labels = c("Current\nforecast", "Hindsight\nmodel", "Ceiling B", "Ceiling A\n(absolute)")) +
  scale_y_continuous(expand = expansion(mult = c(0, 0.12))) + labs(x = NULL, y = NULL)
ggsave(file.path(OUT5, "figs", "ceiling.png"), p, width = 9, height = 3.8, dpi = 150, bg = "white")
log_step("Done")
