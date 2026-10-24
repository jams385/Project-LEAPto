# =============================================================================
# 02_eda.R  —  Stage 2: exploratory analysis to set up the Stage 3 DLNM
#
# Inputs  : data/processed/city_week{,_altA,_altB}.rds   (from 01_build_dataset.R)
# Outputs : output/stage2/*.csv, output/stage2/figs/*.png
#
# Analyses:
#   1 rain & cases time series        6 count-model check (Poisson vs NB, zeros)
#   2 seasonal timing                 7 temperature / humidity overlap with rain
#   3 lag correlations (raw, adjusted) 8 extreme weeks
#   4 heavy-rain event study          9 calendar-version preview of (3)
#   5 rainfall distribution          10 COVID shift
#
# "Adjusted" = after removing each city's seasonal pattern (3 Fourier pairs over the
# 52 morbidity weeks), long-term trend (natural spline, ~1 df per 2 years), a COVID
# indicator and the population offset, using a per-city negative binomial baseline model.
# Heavy rain = a city's wettest 5% of weeks (2008-2022), as agreed.
# Rainfall source: IMERG Final (pr_week_imf), chosen in Stage 2b. Set RAIN_COL <- "pr_week" to
# rerun every analysis on CHIRPS instead (the CHIRPS-vs-IMERG comparison is in 02b_rainfall_sources.R).
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages({ library(ggplot2); library(MASS); library(splines); library(glmmTMB) })
OUT <- file.path(PATHS$out, "stage2"); FIG <- file.path(OUT, "figs")
dir.create(FIG, showWarnings = FALSE, recursive = TRUE)

MAX_LAG   <- 12L      # weeks examined
HEAVY_Q   <- 0.95     # heavy-rain definition
EVENT_WIN <- -4:12    # weeks around heavy-rain events
set.seed(20261020)
RAIN_COL  <- "pr_week_imf"
RAIN_LABEL <- c(pr_week_imf = "IMERG Final", pr_week_iml = "IMERG Late", pr_week = "CHIRPS")[[RAIN_COL]]

# Load a weekly dataset with the chosen rainfall source in pr_week (CHIRPS kept as pr_week_chirps)
load_week <- function(f) {
  d <- readRDS(file.path(PATHS$processed, f))
  stopifnot(RAIN_COL %in% names(d))
  d[, pr_week_chirps := pr_week][, pr_week := get(RAIN_COL)][]
}

BLUE <- "#2a78d6"; ORANGE <- "#eb6834"; AQUA <- "#1baf7a"; GREY <- "#8a8984"; INK <- "#0b0b0b"
theme_set(theme_minimal(base_size = 10) +
          theme(panel.grid.minor = element_blank(), strip.text = element_text(face = "bold", hjust = 0),
                plot.title.position = "plot", legend.position = "top"))
save_fig <- function(p, name, w = 9, h = 6) ggsave(file.path(FIG, name), p, width = w, height = h, dpi = 150, bg = "white")

# ---- Helpers ----------------------------------------------------------------
fourier <- function(mw, K = 3) {
  m <- sapply(1:K, function(k) cbind(sin(2 * pi * k * mw / 52), cos(2 * pi * k * mw / 52)))
  m <- matrix(m, ncol = 2 * K); colnames(m) <- paste0(rep(c("s", "c"), K), rep(1:K, each = 2)); m
}

# Adds lagged rainfall (log1p and anomaly), baseline expected counts and Pearson residuals
prepare <- function(d) {
  d <- copy(d)[order(city, time)]
  d[, lr := log1p(pr_week)]
  # rainfall anomaly: log1p rain minus the city's seasonal mean (Fourier fit on all 2003-2022 weeks)
  F_cols <- paste0(rep(c("s", "c"), 3), rep(1:3, each = 2))
  d[, (F_cols) := as.data.table(fourier(mw))]
  d[, lr_anom := residuals(lm(lr ~ s1 + c1 + s2 + c2 + s3 + c3, na.action = na.exclude)), by = city]
  for (l in 0:MAX_LAG) {
    d[, (paste0("pr_l", l)) := shift(pr_week, l), by = city]
    d[, (paste0("an_l", l)) := shift(lr_anom, l), by = city]
  }
  d[, `:=`(mu = NA_real_, presid = NA_real_)]
  fits <- list()
  for (cc in unique(d$city)) {
    idx <- which(d$city == cc & d$include)
    sub <- d[idx]
    nyr <- uniqueN(sub$year)
    sub[, tspl := NULL]
    B <- ns(sub$time, df = max(2, round(nyr / 2))); colnames(B) <- paste0("t", seq_len(ncol(B)))
    sub <- cbind(sub, B)
    rhs <- paste(c("s1 + c1 + s2 + c2 + s3 + c3", colnames(B),
                   if (uniqueN(sub$flag_covid) > 1) "flag_covid"), collapse = " + ")
    form <- as.formula(paste("cases ~", rhs, "+ offset(log_offset)"))
    nb <- tryCatch(glmmTMB(form, family = nbinom2, data = sub), error = function(e) {
      message("  NB failed for ", cc, " (", conditionMessage(e), ")"); NULL })
    po <- glm(form, family = poisson, data = sub)
    fit <- if (is.null(nb)) po else nb
    d[idx, mu := fitted(fit)]
    d[idx, presid := residuals(fit, type = "pearson")]
    fits[[cc]] <- list(nb = nb, po = po, n = nrow(sub))
  }
  setattr(d, "fits", fits)
  d
}

lagcor <- function(d) {
  m <- d[include == TRUE]
  per_city <- rbindlist(lapply(0:MAX_LAG, function(l) m[, .(
    lag = l,
    raw = suppressWarnings(cor(cases, get(paste0("pr_l", l)), method = "spearman", use = "complete.obs")),
    adj = suppressWarnings(cor(presid, get(paste0("an_l", l)), use = "complete.obs")),
    n = .N), by = city]))
  pooled <- rbindlist(lapply(0:MAX_LAG, function(l) {
    x <- m$presid; y <- m[[paste0("an_l", l)]]; ok <- complete.cases(x, y)
    r <- cor(x[ok], y[ok]); n <- sum(ok); z <- atanh(r); se <- 1 / sqrt(n - 3)
    data.table(lag = l, adj = r, lo = tanh(z - 1.96 * se), hi = tanh(z + 1.96 * se),
               raw = per_city[lag == l, mean(raw, na.rm = TRUE)], n = n)
  }))
  list(per_city = per_city, pooled = pooled)
}

# ---- Load -------------------------------------------------------------------
log_step("Loading and fitting baseline models")
d  <- prepare(load_week("city_week.rds"))
fits <- attr(d, "fits")
city_order <- d[include == TRUE, .(n = sum(cases)), by = city][order(-n), city]
d[, city_f := factor(city, levels = city_order)]
pd <- d[in_pidsr_period == TRUE]

# ---- 1. Time series -----------------------------------------------------------
log_step("1 time series")
for (cc in city_order) {
  x <- pd[city == cc]
  long <- rbind(x[, .(start, value = pr_week, panel = paste0("Rainfall, ", RAIN_LABEL, " (mm per 7 days)"))],
                x[, .(start, value = fifelse(include, cases, NA_real_), panel = "Leptospirosis cases")])
  long[, panel := factor(panel, levels = c(paste0("Rainfall, ", RAIN_LABEL, " (mm per 7 days)"), "Leptospirosis cases"))]
  p <- ggplot(long, aes(start, value, fill = panel)) +
    geom_col(width = 7, show.legend = FALSE) +
    geom_rug(data = x[include == FALSE][, panel := factor("Leptospirosis cases", levels = levels(long$panel))],
             aes(x = start), inherit.aes = FALSE, sides = "b", colour = GREY, length = unit(0.05, "npc")) +
    facet_wrap(~panel, ncol = 1, scales = "free_y") +
    scale_fill_manual(values = c(BLUE, ORANGE)) +
    scale_x_date(date_breaks = "1 year", date_labels = "'%y", expand = c(0.005, 0)) +
    labs(x = NULL, y = NULL, title = cc)
  save_fig(p, sprintf("ts_%s.png", gsub(" ", "_", cc)), w = 9, h = 4.2)
}

# ---- 2. Seasonal timing -------------------------------------------------------
log_step("2 seasonal timing")
circ_smooth <- function(x, k = 2) { n <- length(x); sapply(seq_len(n), function(i) mean(x[((i - k):(i + k) - 1) %% n + 1])) }
seas <- d[include == TRUE, .(rain = mean(pr_week), cases = mean(cases / exp(log_offset) * 1e5)), by = .(city, mw)][order(city, mw)]
seas[, `:=`(rain_s = circ_smooth(rain), cases_s = circ_smooth(cases)), by = city]
peaks <- seas[, .(rain_peak_mw = mw[which.max(rain_s)], case_peak_mw = mw[which.max(cases_s)],
                  rain_season_ratio = round(max(rain_s) / min(rain_s), 1),
                  case_season_ratio = round(max(cases_s) / max(min(cases_s), 1e-9), 1)), by = city]
peaks[, peak_gap_weeks := ((case_peak_mw - rain_peak_mw + 26) %% 52) - 26]
peaks <- peaks[match(city_order, city)]
fwrite(peaks, file.path(OUT, "seasonal_peaks.csv"))

sl <- rbind(seas[, .(city, mw, v = rain_s / max(rain_s) * 100, s = paste0("Rainfall (", RAIN_LABEL, ")")), by = city][, -1],
            seas[, .(city, mw, v = cases_s / max(cases_s) * 100, s = "Leptospirosis cases"), by = city][, -1])
sl[, `:=`(city = factor(city, levels = city_order), s = factor(s, levels = c(paste0("Rainfall (", RAIN_LABEL, ")"), "Leptospirosis cases")))]
p <- ggplot(sl, aes(mw, v, colour = s)) + geom_line(linewidth = 0.8) +
  facet_wrap(~city, ncol = 4) + scale_colour_manual(values = c(BLUE, ORANGE), name = NULL) +
  scale_x_continuous(breaks = c(1, 13, 26, 39, 52)) +
  labs(x = "Morbidity week", y = "% of city's seasonal peak (5-week smoothed)")
save_fig(p, "seasonal_profiles.png", h = 6.5)

# ---- 3. Lag correlations ------------------------------------------------------
log_step("3 lag correlations")
lc <- lagcor(d)
fwrite(lc$per_city, file.path(OUT, "lagcor_by_city.csv")); fwrite(lc$pooled, file.path(OUT, "lagcor_pooled.csv"))

lp <- melt(lc$pooled[, .(lag, `Raw (mean of cities, Spearman)` = raw, `Adjusted (pooled)` = adj)], id.vars = "lag")
p <- ggplot() +
  geom_hline(yintercept = 0, colour = GREY, linewidth = 0.4) +
  geom_ribbon(data = lc$pooled, aes(lag, ymin = lo, ymax = hi), fill = BLUE, alpha = 0.15) +
  geom_line(data = lp, aes(lag, value, colour = variable), linewidth = 0.9) +
  geom_point(data = lp, aes(lag, value, colour = variable), size = 2.4) +
  scale_colour_manual(values = c(GREY, BLUE), name = NULL) +
  scale_x_continuous(breaks = 0:MAX_LAG) +
  labs(x = paste0("Lag (weeks after rainfall, ", RAIN_LABEL, ")"), y = "Correlation")
save_fig(p, "lagcor_pooled.png", h = 4)

hm <- copy(lc$per_city)[, city := factor(city, levels = rev(city_order))]
lim <- max(abs(hm$adj), na.rm = TRUE)
p <- ggplot(hm, aes(factor(lag), city, fill = adj)) + geom_tile(colour = "white", linewidth = 0.6) +
  geom_text(aes(label = sprintf("%.2f", adj)), size = 2.4, colour = INK) +
  scale_fill_gradient2(low = "#c2410c", mid = "#f2f1ee", high = BLUE, midpoint = 0, limits = c(-lim, lim), name = "Adjusted r") +
  labs(x = "Lag (weeks)", y = NULL) + theme(panel.grid = element_blank())
save_fig(p, "lagcor_by_city.png", h = 4.2)

# ---- 4. Heavy-rain event study ------------------------------------------------
log_step("4 event study")
thr <- pd[, .(p95 = quantile(pr_week, HEAVY_Q)), by = city]
d <- merge(d, thr, by = "city"); setorder(d, city, time)
d[, heavy := pr_week >= p95]
# declustered events: first heavy week after >= 8 non-heavy weeks; full window inside case period & included
d[, prev8 := frollsum(shift(as.integer(heavy), 1, fill = 0L), 8, fill = 0L), by = city]
ev <- d[heavy == TRUE & prev8 == 0 & in_pidsr_period == TRUE, .(city, ev_time = time, ev_start = start, ev_rain = pr_week)]
win <- ev[, .(k = EVENT_WIN), by = .(city, ev_time, ev_start, ev_rain)][, time := ev_time + k]
win <- merge(win, d[, .(city, time, cases, mu, include)], by = c("city", "time"))
win <- win[, if (all(include) && .N == length(EVENT_WIN)) .SD, by = .(city, ev_time)]
n_events <- win[, .(events = uniqueN(ev_time)), by = city]
oe <- function(w) w[, .(oe = sum(cases) / sum(mu)), by = k]
es_pooled <- oe(win)
boot <- rbindlist(lapply(1:500, function(b) {
  ids <- unique(win[, .(city, ev_time)])[sample(.N, replace = TRUE)][, rep := .I]
  oe(merge(ids, win, by = c("city", "ev_time"), allow.cartesian = TRUE))[, b := b]
}))
es_pooled <- merge(es_pooled, boot[, .(lo = quantile(oe, .025), hi = quantile(oe, .975)), by = k], by = "k")
es_city <- win[, .(oe = sum(cases) / sum(mu), cases = sum(cases), expected = sum(mu)), by = .(city, k)]
fwrite(es_pooled, file.path(OUT, "event_study_pooled.csv")); fwrite(es_city, file.path(OUT, "event_study_by_city.csv"))
fwrite(merge(thr, n_events, by = "city", all.x = TRUE)[match(city_order, city)], file.path(OUT, "heavy_rain_thresholds.csv"))

p <- ggplot(es_pooled, aes(k, oe)) +
  geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_vline(xintercept = 0, colour = GREY, linewidth = 0.4, linetype = "dashed") +
  geom_ribbon(aes(ymin = lo, ymax = hi), fill = ORANGE, alpha = 0.18) +
  geom_line(colour = ORANGE, linewidth = 0.9) + geom_point(colour = ORANGE, size = 2.4) +
  scale_x_continuous(breaks = EVENT_WIN) +
  labs(x = paste0("Weeks relative to heavy-rain week (0), ", RAIN_LABEL), y = "Observed / expected cases")
save_fig(p, "event_study_pooled.png", h = 4)

top6 <- city_order[1:6]
p <- ggplot(es_city[city %in% top6][, city := factor(city, levels = top6)], aes(k, oe)) +
  geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_vline(xintercept = 0, colour = GREY, linewidth = 0.4, linetype = "dashed") +
  geom_line(colour = ORANGE, linewidth = 0.8) + geom_point(colour = ORANGE, size = 1.6) +
  facet_wrap(~city, ncol = 3, scales = "free_y") + scale_x_continuous(breaks = c(-4, 0, 4, 8, 12)) +
  labs(x = paste0("Weeks relative to heavy-rain week, ", RAIN_LABEL), y = "Observed / expected")
save_fig(p, "event_study_by_city.png", h = 4.8)

# ---- 5. Rainfall distribution -------------------------------------------------
log_step("5 rainfall distribution")
rd <- pd[, as.list(c(round(quantile(pr_week, c(.10, .25, .50, .75, .90, .95, .99))), max = round(max(pr_week)),
                     pct_dry = round(100 * mean(pr_week < 1)))), by = city][match(city_order, city)]
setnames(rd, c("city", "p10", "p25", "p50", "p75", "p90", "p95", "p99", "max", "pct_dry"))
pool_q <- quantile(pd$pr_week, c(.05, .95))
rd[, pct_in_pooled_5_95 := round(100 * pd[city == .BY$city, mean(pr_week >= pool_q[1] & pr_week <= pool_q[2])]), by = city]
fwrite(rd, file.path(OUT, "rainfall_distribution.csv"))
p <- ggplot(pd[, city_f := factor(city, levels = rev(city_order))], aes(pr_week, city_f)) +
  geom_boxplot(fill = BLUE, alpha = 0.25, colour = BLUE, outlier.size = 0.6, outlier.alpha = 0.4, width = 0.6) +
  scale_x_continuous(trans = "log1p", breaks = c(0, 10, 30, 100, 300, 1000)) +
  labs(x = paste0("Rainfall, ", RAIN_LABEL, ", mm per 7 days (log scale)"), y = NULL)
save_fig(p, "rainfall_distribution.png", h = 4.2)

# ---- 6. Count model check -----------------------------------------------------
log_step("6 count models")
cm <- rbindlist(lapply(names(fits), function(cc) {
  f <- fits[[cc]]; sub <- d[city == cc & include == TRUE]
  disp_po <- sum(residuals(f$po, type = "pearson")^2) / df.residual(f$po)
  if (!is.null(f$nb)) {
    th <- sigma(f$nb); mu <- fitted(f$nb)
    zero_nb <- sum(dnbinom(0, mu = mu, size = th)); aic_nb <- AIC(f$nb)
  } else { th <- NA; zero_nb <- NA; aic_nb <- NA }
  data.table(city = cc, weeks = f$n, cases = sum(sub$cases), poisson_dispersion = round(disp_po, 1),
             nb_theta = round(th, 2), aic_poisson = round(AIC(f$po)), aic_nb = round(aic_nb),
             zeros_observed = sum(sub$cases == 0), zeros_expected_nb = round(zero_nb),
             zeros_expected_poisson = round(sum(dpois(0, fitted(f$po)))))
}))[match(city_order, city)]
fwrite(cm, file.path(OUT, "count_model_check.csv"))

# ---- 7. Temperature / humidity overlap ----------------------------------------
log_step("7 confounders")
an <- copy(d)[, `:=`(t_anom = residuals(lm(tave ~ s1 + c1 + s2 + c2 + s3 + c3, na.action = na.exclude)),
                     h_anom = residuals(lm(rh ~ s1 + c1 + s2 + c2 + s3 + c3, na.action = na.exclude))), by = city]
conf <- an[in_pidsr_period == TRUE, .(
  r_rain_temp_raw = cor(lr, tave), r_rain_rh_raw = cor(lr, rh),
  r_rain_temp_anom = cor(lr_anom, t_anom), r_rain_rh_anom = cor(lr_anom, h_anom)), by = city]
conf <- rbind(conf, an[in_pidsr_period == TRUE, .(city = "Pooled",
  r_rain_temp_raw = cor(lr, tave), r_rain_rh_raw = cor(lr, rh),
  r_rain_temp_anom = cor(lr_anom, t_anom), r_rain_rh_anom = cor(lr_anom, h_anom))])
conf[, (2:5) := lapply(.SD, round, 2), .SDcols = 2:5]
fwrite(conf[match(c(city_order, "Pooled"), city)], file.path(OUT, "confounder_correlations.csv"))
# does humidity carry signal beyond rain? residual-case correlation with humidity anomaly by lag
hl <- rbindlist(lapply(0:MAX_LAG, function(l) {
  an[, hx := shift(h_anom, l), by = city]; an[, tx := shift(t_anom, l), by = city]
  m <- an[include == TRUE]
  data.table(lag = l, r_humidity = cor(m$presid, m$hx, use = "complete.obs"),
             r_temperature = cor(m$presid, m$tx, use = "complete.obs"))
}))
fwrite(merge(hl, lc$pooled[, .(lag, r_rain = adj)], by = "lag"), file.path(OUT, "confounder_lagcor.csv"))

# ---- 8. Extreme weeks ---------------------------------------------------------
log_step("8 extreme weeks")
d[, rain4 := frollsum(shift(pr_week, 1), 4), by = city]            # 4 weeks before
d[, rain4_pct := round(100 * ecdf(rain4[in_pidsr_period])(rain4)), by = city]
d[, rain4_max := frollapply(shift(pr_week, 1), 4, max), by = city]
ext <- d[include == TRUE][order(-cases)][, head(.SD, 3), by = city][, .(
  city, year, mw, start, cases, expected = round(mu, 1), obs_over_exp = round(cases / mu, 1),
  share_of_city_total = round(100 * cases / pd[city == .BY$city & include == TRUE, sum(cases)], 1),
  rain_same_week = round(pr_week), rain_prev4_total = round(rain4), rain_prev4_pctile = rain4_pct,
  wettest_prev_week = round(rain4_max)), by = city][, city := NULL]
ext[, rain_preceded := rain_prev4_pctile >= 90]
ext <- ext[order(match(city, city_order), -cases)]
fwrite(ext, file.path(OUT, "extreme_weeks.csv"))

# ---- 9. Calendar-version preview ---------------------------------------------
log_step("9 calendar versions")
cal_lc <- rbindlist(lapply(c(primary = "city_week.rds", altA = "city_week_altA.rds", altB = "city_week_altB.rds"), function(f) {
  lagcor(prepare(load_week(f)))$pooled[, .(lag, adj, lo, hi)]
}), idcol = "version")
fwrite(cal_lc, file.path(OUT, "lagcor_calendar_versions.csv"))
cal_lc[, version := factor(version, levels = c("primary", "altA", "altB"),
                           labels = c("Primary", "Alternative A", "Alternative B"))]
p <- ggplot(cal_lc, aes(lag, adj, colour = version)) +
  geom_hline(yintercept = 0, colour = GREY, linewidth = 0.4) +
  geom_line(linewidth = 0.9) + geom_point(size = 2.2) +
  scale_colour_manual(values = c(BLUE, ORANGE, AQUA), name = NULL) +
  scale_x_continuous(breaks = 0:MAX_LAG) + labs(x = paste0("Lag (weeks after rainfall, ", RAIN_LABEL, ")"), y = "Adjusted correlation (pooled)")
save_fig(p, "lagcor_calendar_versions.png", h = 4)

# ---- 10. COVID shift ----------------------------------------------------------
log_step("10 COVID")
cv <- d[in_pidsr_period == TRUE & include == TRUE & year >= 2017, .(
  period = fifelse(flag_covid, "Covid (Mar 2020-2022)", "Pre (2017-Mar 2020)"),
  lepto_per_wk = cases, core_per_wk = core_cases, nondengue_per_wk = core_cases - dengue), by = city]
cvs <- cv[, .(lepto = mean(lepto_per_wk), core = mean(core_per_wk), nondengue = mean(nondengue_per_wk)), by = .(city, period)]
cvw <- dcast(cvs, city ~ period, value.var = c("lepto", "core", "nondengue"))
setnames(cvw, gsub("Covid \\(Mar 2020-2022\\)", "covid", gsub("Pre \\(2017-Mar 2020\\)", "pre", names(cvw))))
cvw[, `:=`(lepto_ratio = round(lepto_covid / lepto_pre, 2), nondengue_ratio = round(nondengue_covid / nondengue_pre, 2))]
cvw <- rbind(cvw, data.table(city = "All cities",
  lepto_ratio = round(cv[period %like% "Covid", mean(lepto_per_wk)] / cv[period %like% "Pre", mean(lepto_per_wk)] , 2),
  nondengue_ratio = round(cv[period %like% "Covid", mean(nondengue_per_wk)] / cv[period %like% "Pre", mean(nondengue_per_wk)], 2)), fill = TRUE)
fwrite(cvw[match(c(city_order, "All cities"), city)], file.path(OUT, "covid_shift.csv"))
# COVID coefficient in pooled baseline-type model
pool_cov <- glmmTMB(cases ~ city + city:(s1 + c1 + s2 + c2 + s3 + c3) + city:ns(time, df = 7) + flag_covid + offset(log_offset),
                    family = nbinom2, data = d[include == TRUE])
ci <- confint(pool_cov, parm = "flag_covidTRUE", method = "wald")
fwrite(data.table(term = "flag_covid", rr = exp(fixef(pool_cov)$cond["flag_covidTRUE"]),
                  lo = exp(ci[1, 1]), hi = exp(ci[1, 2]), pooled_theta = sigma(pool_cov)),
       file.path(OUT, "covid_pooled_rr.csv"))

log_step("Done")
print(peaks); print(lc$pooled); print(es_pooled); print(cm); print(conf); print(ext[rain_preceded == FALSE | share_of_city_total > 10])
print(cal_lc); print(cvw); print(fread(file.path(OUT, "covid_pooled_rr.csv")))
