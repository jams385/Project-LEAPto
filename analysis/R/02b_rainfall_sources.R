# =============================================================================
# 02b_rainfall_sources.R  —  Compare CHIRPS with NASA IMERG (Final, Late)
#
# Inputs  : data/processed/city_week.rds (with IMERG columns from 01b_add_imerg.R)
# Outputs : output/stage2b/*.csv, output/stage2b/figs/*.png
#
#   A  agreement: annual totals, weekly correlation, overlap of heavy-rain weeks
#   B  biggest disagreements between sources (and what followed in cases)
#   C  adjusted lag correlations by source (as Stage 2 §3.4)
#   D  heavy-rain event study by source (as Stage 2 §3.5), with and without CDO
#   E  model-fit preview: pooled NB baseline + 4-week rainfall term, AIC by source
#   F  Cagayan de Oro and Typhoon Washi: city vs upstream-basin rainfall
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages({ library(ggplot2); library(splines); library(glmmTMB) })
OUT <- file.path(PATHS$out, "stage2b"); FIG <- file.path(OUT, "figs")
dir.create(FIG, showWarnings = FALSE, recursive = TRUE)
MAX_LAG <- 12L; HEAVY_Q <- 0.95; EVENT_WIN <- -4:12; set.seed(20261021)
SOURCES <- c(CHIRPS = "pr_week", `IMERG Final` = "pr_week_imf", `IMERG Late` = "pr_week_iml")
COLS <- c(CHIRPS = "#8a8984", `IMERG Final` = "#2a78d6", `IMERG Late` = "#eb6834")
GREY <- "#8a8984"
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top",
          strip.text = element_text(face = "bold", hjust = 0), plot.title.position = "plot"))
save_fig <- function(p, name, w = 9, h = 4.2) ggsave(file.path(FIG, name), p, width = w, height = h, dpi = 150, bg = "white")

d0 <- readRDS(file.path(PATHS$processed, "city_week.rds"))
stopifnot(all(SOURCES %in% names(d0)))
city_order <- d0[include == TRUE, .(n = sum(cases)), by = city][order(-n), city]
pd <- d0[in_pidsr_period == TRUE]

# ---- Baseline model (does not depend on rainfall; fitted once) --------------
log_step("Baseline models")
F_cols <- c("s1", "c1", "s2", "c2", "s3", "c3")
d0[, (F_cols) := list(sin(2*pi*mw/52), cos(2*pi*mw/52), sin(4*pi*mw/52), cos(4*pi*mw/52), sin(6*pi*mw/52), cos(6*pi*mw/52))]
d0[, `:=`(mu = NA_real_, presid = NA_real_)]
for (cc in unique(d0$city)) {
  idx <- which(d0$city == cc & d0$include); sub <- d0[idx]
  B <- ns(sub$time, df = max(2, round(uniqueN(sub$year) / 2))); colnames(B) <- paste0("t", seq_len(ncol(B)))
  sub <- cbind(sub, B)
  rhs <- paste(c(F_cols, colnames(B), if (uniqueN(sub$flag_covid) > 1) "flag_covid"), collapse = " + ")
  fit <- glmmTMB(as.formula(paste("cases ~", rhs, "+ offset(log_offset)")), family = nbinom2, data = sub)
  d0[idx, `:=`(mu = fitted(fit), presid = residuals(fit, type = "pearson"))]
}

with_source <- function(col) {
  d <- copy(d0)[order(city, time)][, rain := get(col)]
  d[, lr := log1p(rain)]
  d[, lr_anom := residuals(lm(lr ~ s1 + c1 + s2 + c2 + s3 + c3)), by = city]
  for (l in 0:MAX_LAG) d[, (paste0("an_l", l)) := shift(lr_anom, l), by = city]
  d
}

# ---- A. Agreement -----------------------------------------------------------
log_step("A agreement")
agree <- pd[, {
  q <- function(x) x >= quantile(x, HEAVY_Q)
  hc <- q(pr_week); hf <- q(pr_week_imf); hl <- q(pr_week_iml)
  .(rain_yr_chirps = round(sum(pr_total) / 15), rain_yr_imf = round(sum(pr_total_imf) / 15), rain_yr_iml = round(sum(pr_total_iml) / 15),
    r_chirps_imf = round(cor(log1p(pr_week), log1p(pr_week_imf)), 2), r_imf_iml = round(cor(log1p(pr_week_imf), log1p(pr_week_iml)), 2),
    heavy_overlap_chirps_imf = round(100 * sum(hc & hf) / sum(hc)), heavy_overlap_imf_iml = round(100 * sum(hf & hl) / sum(hf)),
    p95_chirps = round(quantile(pr_week, HEAVY_Q)), p95_imf = round(quantile(pr_week_imf, HEAVY_Q)), p95_iml = round(quantile(pr_week_iml, HEAVY_Q)))
}, by = city][match(city_order, city)]
fwrite(agree, file.path(OUT, "agreement_by_city.csv"))

# ---- B. Biggest disagreements ------------------------------------------------
log_step("B disagreements")
setorder(d0, city, time)
d0[, cases_next4 := shift(cases, -1) + shift(cases, -2) + shift(cases, -3) + shift(cases, -4), by = city]
d0[, `:=`(p95_c = quantile(pr_week[in_pidsr_period], HEAVY_Q), p95_f = quantile(pr_week_imf[in_pidsr_period], HEAVY_Q)), by = city]
dis <- d0[in_pidsr_period == TRUE, .(city, year, mw, start, chirps = round(pr_week), imerg_final = round(pr_week_imf),
                                     ratio = round((pr_week_imf + 10) / (pr_week + 10), 1),
                                     heavy_in = fcase(pr_week_imf >= p95_f & pr_week < p95_c, "IMERG only",
                                                      pr_week >= p95_c & pr_week_imf < p95_f, "CHIRPS only",
                                                      pr_week >= p95_c & pr_week_imf >= p95_f, "both", default = "neither"),
                                     cases_next4)]
top_dis <- rbind(dis[heavy_in == "IMERG only"][order(-ratio)][1:15], dis[heavy_in == "CHIRPS only"][order(ratio)][1:10])
fwrite(top_dis, file.path(OUT, "biggest_disagreements.csv"))
heavy_tab <- dis[, .N, by = .(city, heavy_in)]
fwrite(dcast(heavy_tab, city ~ heavy_in, value.var = "N", fill = 0)[match(city_order, city)], file.path(OUT, "heavy_week_classification.csv"))
# cases following heavy weeks, by which source flagged them
foll <- merge(dis, d0[in_pidsr_period == TRUE, .(city, start, mu_next4 = shift(mu, -1) + shift(mu, -2) + shift(mu, -3) + shift(mu, -4))],
              by = c("city", "start"))
foll_sum <- foll[heavy_in != "neither" & !is.na(cases_next4) & !is.na(mu_next4),
                 .(weeks = .N, cases_next4 = sum(cases_next4), expected_next4 = round(sum(mu_next4)),
                   obs_over_exp = round(sum(cases_next4) / sum(mu_next4), 2)), by = heavy_in]
foll_sum_noCDO <- foll[heavy_in != "neither" & city != "Cagayan de Oro" & !is.na(cases_next4) & !is.na(mu_next4),
                 .(weeks = .N, obs_over_exp = round(sum(cases_next4) / sum(mu_next4), 2)), by = heavy_in]
fwrite(merge(foll_sum, foll_sum_noCDO, by = "heavy_in", suffixes = c("", "_without_CDO")), file.path(OUT, "cases_after_heavy_weeks_by_source.csv"))

# ---- C. Lag correlations by source ------------------------------------------
log_step("C lag correlations")
lagcor_src <- rbindlist(lapply(names(SOURCES), function(s) {
  d <- with_source(SOURCES[[s]]); m <- d[include == TRUE]
  rbindlist(lapply(0:MAX_LAG, function(l) {
    x <- m$presid; y <- m[[paste0("an_l", l)]]; ok <- complete.cases(x, y)
    r <- cor(x[ok], y[ok]); se <- 1 / sqrt(sum(ok) - 3)
    m2 <- m[city != "Cagayan de Oro"]; x2 <- m2$presid; y2 <- m2[[paste0("an_l", l)]]; ok2 <- complete.cases(x2, y2)
    data.table(source = s, lag = l, r = r, lo = tanh(atanh(r) - 1.96 * se), hi = tanh(atanh(r) + 1.96 * se),
               r_without_CDO = cor(x2[ok2], y2[ok2]))
  }))
}))
fwrite(lagcor_src, file.path(OUT, "lagcor_by_source.csv"))
lc_city <- rbindlist(lapply(names(SOURCES), function(s) {
  d <- with_source(SOURCES[[s]]); m <- d[include == TRUE]
  m[, .(source = s, r_lag2 = cor(presid, an_l2, use = "complete.obs"), r_lag3 = cor(presid, an_l3, use = "complete.obs")), by = city]
}))
fwrite(dcast(lc_city, city ~ source, value.var = c("r_lag2", "r_lag3"))[match(city_order, city)], file.path(OUT, "lagcor_lag2_3_by_city_source.csv"))
lagcor_src[, source := factor(source, levels = names(SOURCES))]
p <- ggplot(lagcor_src, aes(lag, r, colour = source)) +
  geom_hline(yintercept = 0, colour = GREY, linewidth = 0.4) +
  geom_line(linewidth = 0.9) + geom_point(size = 2.2) +
  scale_colour_manual(values = COLS, name = NULL) + scale_x_continuous(breaks = 0:MAX_LAG) +
  labs(x = "Lag (weeks after rainfall)", y = "Adjusted correlation (pooled)")
save_fig(p, "lagcor_by_source.png")

# ---- D. Event study by source -----------------------------------------------
log_step("D event study")
event_study <- function(col, drop_cdo = FALSE) {
  d <- copy(d0)[order(city, time)][, rain := get(col)]
  d[, p95 := quantile(rain[in_pidsr_period], HEAVY_Q), by = city]
  d[, heavy := rain >= p95]
  d[, prev8 := frollsum(shift(as.integer(heavy), 1, fill = 0L), 8, fill = 0L), by = city]
  ev <- d[heavy == TRUE & prev8 == 0 & in_pidsr_period == TRUE, .(city, ev_time = time)]
  win <- ev[, .(k = EVENT_WIN), by = .(city, ev_time)][, time := ev_time + k]
  win <- merge(win, d[, .(city, time, cases, mu, include)], by = c("city", "time"))
  win <- win[, if (all(include) && .N == length(EVENT_WIN)) .SD, by = .(city, ev_time)]
  if (drop_cdo) win <- win[city != "Cagayan de Oro"]
  est <- win[, .(oe = sum(cases) / sum(mu)), by = k]
  ids <- unique(win[, .(city, ev_time)])
  boot <- rbindlist(lapply(1:400, function(b) merge(ids[sample(.N, replace = TRUE)][, r := .I], win, by = c("city", "ev_time"),
                                                     allow.cartesian = TRUE)[, .(oe = sum(cases) / sum(mu)), by = k]))
  merge(est, boot[, .(lo = quantile(oe, .025), hi = quantile(oe, .975)), by = k], by = "k")[, events := nrow(ids)]
}
es <- rbindlist(lapply(names(SOURCES), function(s) rbind(
  event_study(SOURCES[[s]])[, `:=`(source = s, sample = "All cities")],
  event_study(SOURCES[[s]], TRUE)[, `:=`(source = s, sample = "Without Cagayan de Oro")])))
fwrite(es, file.path(OUT, "event_study_by_source.csv"))
es[, source := factor(source, levels = names(SOURCES))]
p <- ggplot(es, aes(k, oe, colour = source, fill = source)) +
  geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) + geom_vline(xintercept = 0, colour = GREY, linetype = "dashed", linewidth = 0.4) +
  geom_ribbon(aes(ymin = lo, ymax = hi), alpha = 0.10, colour = NA) +
  geom_line(linewidth = 0.9) + geom_point(size = 1.8) +
  facet_wrap(~sample, ncol = 2, scales = "free_y") +
  scale_colour_manual(values = COLS, name = NULL) + scale_fill_manual(values = COLS, name = NULL) +
  scale_x_continuous(breaks = c(-4, 0, 2, 4, 6, 8, 12)) +
  labs(x = "Weeks relative to heavy-rain week (0)", y = "Observed / expected cases")
save_fig(p, "event_study_by_source.png", h = 4.4)

# ---- E. Model-fit preview -----------------------------------------------------
# Two-step screening model: each city's baseline (seasonality + trend + COVID + population, fitted
# above) enters as a fixed offset log(mu); a pooled NB model then adds a natural spline (3 df) of
# log(1 + mean rainfall over lags 1-4), with city-specific dispersion. Identical rows for every source,
# so AIC differences show which rainfall series explains the extra variation in cases best.
# (A one-step model with all city terms is left to Stage 3; it is too large to converge as a quick check.)
log_step("E model-fit preview")
setorder(d0, city, time)
for (s in names(SOURCES)) {
  col <- SOURCES[[s]]; nm <- paste0("x_", make.names(s))
  d0[, (nm) := log1p((shift(get(col), 1) + shift(get(col), 2) + shift(get(col), 3) + shift(get(col), 4)) / 4), by = city]
}
fitdat <- d0[include == TRUE & !is.na(mu)][, `:=`(city = factor(city), mu = pmax(mu, 1e-6))]
CTRL <- glmmTMBControl(optCtrl = list(iter.max = 1e4, eval.max = 1e4))
# Per-city dispersion estimated once on the baseline (all cities), then held fixed in every
# comparison model, so models differ only in the rainfall term.
b_all <- glmmTMB(cases ~ 1 + offset(log(mu)), family = nbinom2, dispformula = ~ 0 + city, data = fitdat, control = CTRL)
disp_name <- grep("^betad", unique(names(b_all$fit$par)), value = TRUE)[1]
log_theta <- setNames(fixef(b_all)$disp, sub("^city", "", names(fixef(b_all)$disp)))
fwrite(data.table(city = names(log_theta), theta = round(exp(log_theta), 3)), file.path(OUT, "baseline_dispersion_by_city.csv"))
fit_one <- function(xvar, data) {
  f <- if (is.null(xvar)) cases ~ 1 + offset(log(mu)) else as.formula(paste("cases ~ ns(", xvar, ", df = 3) + offset(log(mu))"))
  lv <- levels(data$city)
  st <- setNames(list(unname(log_theta[lv])), disp_name)
  mp <- setNames(list(factor(rep(NA, length(lv)))), disp_name)
  glmmTMB(f, family = nbinom2, dispformula = ~ 0 + city, data = data, start = st, map = mp, control = CTRL)
}
mfit <- rbindlist(lapply(c(FALSE, TRUE), function(drop) {
  dat <- if (drop) fitdat[city != "Cagayan de Oro"][, city := droplevels(city)] else fitdat
  ms <- c(list(`No rainfall (baseline only)` = fit_one(NULL, dat)),
          setNames(lapply(names(SOURCES), function(s) fit_one(paste0("x_", make.names(s)), dat)), names(SOURCES)))
  data.table(source = names(ms), loglik = sapply(ms, function(m) as.numeric(logLik(m))),
             aic = sapply(ms, AIC), converged = sapply(ms, function(m) m$fit$convergence == 0))[
    , `:=`(delta_aic_vs_baseline = round(aic - aic[1], 1), aic = round(aic, 1), loglik = round(loglik, 1),
           sample = if (drop) "Without Cagayan de Oro" else "All cities", rows = nrow(dat))]
}))
fwrite(mfit, file.path(OUT, "model_fit_by_source.csv"))

# ---- F. Cagayan de Oro and Washi ---------------------------------------------
log_step("F CDO / Washi")
cdo <- d0[city == "Cagayan de Oro" & start >= as.IDate("2011-11-20") & start <= as.IDate("2012-01-22"),
          .(year, mw, start, end, cases, chirps = round(pr_week), imerg_final = round(pr_week_imf), imerg_late = round(pr_week_iml),
            basin_final = round(pr_basin_imf), basin_late = round(pr_basin_iml))]
fwrite(cdo, file.path(OUT, "cdo_washi_weeks.csv"))
cdo_rank <- d0[city == "Cagayan de Oro" & in_pidsr_period == TRUE, .(start,
  pct_chirps = round(100 * frank(pr_week) / .N, 1), pct_imf = round(100 * frank(pr_week_imf) / .N, 1),
  pct_basin_imf = round(100 * frank(pr_basin_imf) / .N, 1))][start == as.IDate("2011-12-11")]
fwrite(cdo_rank, file.path(OUT, "cdo_washi_week_percentiles.csv"))
bc <- rbindlist(lapply(c(city_final = "pr_week_imf", basin_final = "pr_basin_imf", chirps = "pr_week"), function(col) {
  x <- copy(d0[city == "Cagayan de Oro"])[order(time)][, a := residuals(lm(log1p(get(col)) ~ s1 + c1 + s2 + c2 + s3 + c3))]
  for (l in 0:6) x[, (paste0("l", l)) := shift(a, l)]
  x <- x[include == TRUE]
  data.table(lag = 0:6, r = sapply(0:6, function(l) cor(x$presid, x[[paste0("l", l)]], use = "complete.obs")))
}), idcol = "series")
fwrite(dcast(bc, lag ~ series, value.var = "r")[, lapply(.SD, round, 3)], file.path(OUT, "cdo_city_vs_basin_lagcor.csv"))

log_step("Done")
print(agree); print(top_dis[1:12]); print(fread(file.path(OUT, "cases_after_heavy_weeks_by_source.csv")))
print(dcast(lagcor_src, lag ~ source, value.var = "r")); print(dcast(lagcor_src, lag ~ source, value.var = "r_without_CDO"))
print(es[k %in% c(0, 2, 3, 4, 5, 7), .(source, sample, k, oe = round(oe, 2), events)][order(sample, source, k)])
print(mfit); print(cdo); print(cdo_rank); print(fread(file.path(OUT, "cdo_city_vs_basin_lagcor.csv")))
