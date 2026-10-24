# =============================================================================
# 05_validation.R  —  Stage 5: rolling-origin validation of the forecasting model
#
# For each origin year Y = 2013..2021: fit on 2008..Y, forecast every week of Y+1 at horizons
# h = 1..4 weeks ahead, using only information available at forecast time.
#
# Forecasting model (direct, one model per horizon h), negative binomial, city-specific dispersion
# (three smallest cities share one, as in Stage 3):
#   cases ~ city + city x seasonality (3 Fourier pairs) + city x trend (natural spline, ~1 df per 2
#           training years; held at its last training value in the forecast year) + COVID indicator
#           [+ log(1 + cases h+1 weeks earlier)]          <- "last week's cases", 1-week reporting delay
#           [+ crossbasis(rain, lags h..10)]               <- rain known at forecast time only
#           + offset(log(pop * days/7))
#   Rain crossbasis as Stage 3 (rain knots P25/P50/P75 from training years, 3 log-scale lag knots);
#   "regional" variants give Luzon and Visayas/Mindanao separate rain curves.
# Variants: seasonal (baseline A), pooled, pooled_ar, regional, regional_ar; baseline B = persistence.
# Main rainfall: IMERG Late for training and forecasting. Checks for the best variant:
#   Final/Final, Final->Late, and no reporting delay.
# Alerts: P(cases > threshold) >= cut-off; cut-off chosen on the training years (Youden's J, main;
#   smallest cut-off reaching 70% sensitivity, check). Thresholds from Stage 4 (5-year, standard and
#   outbreak-excluded).
#
# Inputs  : data/processed/city_week.rds, output/stage4/{thresholds_weekly, outbreak_episodes, city_type}.csv
# Outputs : output/stage5/forecasts.csv.gz (all forecasts), *.csv metrics, figs/*.png
# Set Sys.setenv(STAGE5_REFIT = "1") to refit even if forecasts.csv.gz exists.
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages({ library(dlnm); library(splines); library(glmmTMB); library(ggplot2); library(parallel) })
OUT <- file.path(PATHS$out, "stage5"); FIG <- file.path(OUT, "figs")
dir.create(FIG, recursive = TRUE, showWarnings = FALSE)

ORIGINS <- 2013:2021; HORIZONS <- 1:4; L <- 10L; VAR_Q <- c(.25, .50, .75); NK <- 3L; DELAY <- 1L
VARIANTS <- c("seasonal", "pooled", "pooled_ar", "regional", "regional_ar")
MAIN_RAIN <- "pr_week_iml"
LUZON <- c("Dagupan", "Palayan", "Navotas", "Mandaluyong", "Muntinlupa", "Legazpi")
SMALL <- c("Legazpi", "Mandaue", "Palayan")
SEAS_MIN <- 100L; TREND_PER_DF <- 50L
CORES <- max(1L, min(2L, parallel::detectCores()))
CTRL <- glmmTMBControl(optCtrl = list(iter.max = 1e4, eval.max = 1e4))
F3 <- c("s1", "c1", "s2", "c2", "s3", "c3")
VERSIONS <- c(std5 = "Standard", exc5 = "Outbreak-excluded")

# ---- Data ----------------------------------------------------------------------
d <- readRDS(file.path(PATHS$processed, "city_week.rds"))[order(city, start)]
d[, time := seq_len(.N), by = city]
d[, (F3) := list(sin(2*pi*mw/52), cos(2*pi*mw/52), sin(4*pi*mw/52), cos(4*pi*mw/52), sin(6*pi*mw/52), cos(6*pi*mw/52))]
d[, `:=`(region = fifelse(city %in% LUZON, "Luzon", "VisMin"), dgrp = fifelse(city %in% SMALL, "small cities", city))]
d[, y := fifelse(include, cases, NA_integer_)]
thr <- fread(file.path(PATHS$out, "stage4", "thresholds_weekly.csv"))[, .(city, year, mw, thr_std5, thr_exc5, above_std5, above_exc5)]
d <- merge(d, thr, by = c("city", "year", "mw"), all.x = TRUE)[order(city, start)]
ctype <- fread(file.path(PATHS$out, "stage4", "city_type.csv"))
d <- merge(d, ctype[, .(city, city_type)], by = "city")[order(city, start)]
# Stage 7c: weekly river-flow signal (GloFAS), used only by "_riv"/"_rivs" variants
RIV <- file.path(PATHS$processed, "glofas_city_week.csv")
if (file.exists(RIV)) d <- merge(d, fread(RIV)[, .(city, year, mw, river_z, river_flood, river_used)], by = c("city", "year", "mw"), all.x = TRUE)[order(city, start)]
setkey(d, city, start)

# ---- One model: fit on 2008..origin, forecast origin+1 at horizon h ------------------
# flood_e / g (Stage 7): optional named vector of centred city flood exposure; the rain crossbasis of city c is
# multiplied by (1 + g * flood_e[c]), so flood exposure scales the strength of the rain effect (not its timing).
# ll_only = TRUE returns the training log-likelihood only (used to estimate g on training years).
fit_forecast <- function(origin, h, variant, rain_train = MAIN_RAIN, rain_test = rain_train, delay = DELAY,
                         flood_e = NULL, g = 0, ll_only = FALSE, tr_mask = NULL, te_mask = NULL) {
  # tr_mask / te_mask (Stage 6): optional logical vectors over the rows of d giving a custom training window and
  # forecast set (e.g. all years except one event); by default training = 2008..origin, forecast = origin + 1
  dd <- copy(d)
  pin <- dd$in_pidsr_period
  win <- if (is.null(tr_mask)) dd$year <= origin else tr_mask
  tr <- pin & win & !is.na(dd$y)
  #  "_nw": set Typhoon Washi's outbreak weeks in Cagayan de Oro (18 Dec 2011 - 21 Jan 2012) aside as training
  #         outcomes (they still count as recent case history); one event = 73% of the city's cases, and no input
  #         (rain or river flow) represents it, so it otherwise teaches the model a false yearly Dec-Jan peak
  if (grepl("_nw", variant)) tr <- tr & !(dd$city == "Cagayan de Oro" & dd$start >= as.IDate("2011-12-18") & dd$start <= as.IDate("2012-01-21"))
  te <- pin & (if (is.null(te_mask)) dd$year == origin + 1L else te_mask)
  dd[, is_te := te]
  use_rain <- grepl("^(pooled|regional)", variant)
  use_ar <- grepl("_ar", variant)
  # Stage 5c options, set by the variant name:
  #  "_ar4": also the mean of the 3 weeks of cases before the last known week (case history)
  #  "_lvl": replace the per-city spline trend with each city's recent level: log case rate over the last 52 known weeks
  use_ar4 <- grepl("_ar4", variant); use_lvl <- grepl("_lvl", variant)
  #  "_riv":  river-flow signal as a crossbasis over lags h..10 (like rain); "_rivs": mean river signal over lags
  #           h..h+3 as a 3-df spline; a trailing "12" = all 12 cities, otherwise only the river cities (river_used)
  use_riv <- grepl("_riv(12)?$", variant); use_rivs <- grepl("_rivs(12)?$", variant); riv_all <- grepl("_rivs?12$", variant)
  # Baseline sized to the data each city has in the training years (no look-ahead):
  #  - seasonality: own 3 Fourier pairs if >= SEAS_MIN training cases, otherwise one pattern shared by those cities
  #  - trend: natural spline with df = min(~1 per 2 years, cases / TREND_PER_DF); 0 = no trend; held at its last
  #    training value in the forecast year
  tc <- dd[tr, .(n = sum(y)), by = city]; setkey(tc, city)
  k <- max(2L, round((origin - 2008L + 1L) / 2))
  dd[, sgrp := fifelse(tc[city, n] >= SEAS_MIN, city, "shared")]
  rhs <- "city"
  for (sg in unique(dd$sgrp)) for (v in F3) {
    nm <- paste0("S_", make.names(sg), "_", v); dd[, (nm) := get(v) * (sgrp == sg)]; rhs <- c(rhs, nm)
  }
  trend_df <- pmin(k, floor(tc$n / TREND_PER_DF)); names(trend_df) <- tc$city
  if (use_lvl) trend_df[] <- 0L
  for (cc in names(trend_df)[trend_df > 0]) {
    kk <- trend_df[[cc]]; i <- dd$city == cc
    tt <- dd$time[i & pin & win]; b <- ns(tt, df = kk)
    B <- predict(b, newx = pmin(pmax(dd$time[i], min(tt)), max(tt)))
    for (j in seq_len(kk)) { nm <- paste0("T_", make.names(cc), "_", j); dd[, (nm) := 0]; set(dd, which(i), nm, B[, j]); rhs <- c(rhs, nm) }
  }
  if (uniqueN(dd$flag_covid[tr]) > 1) rhs <- c(rhs, "flag_covid")
  if (use_ar) { dd[, ar := log1p(shift(cases, h + delay)), by = city]; rhs <- c(rhs, "ar") }
  if (use_ar4) { dd[, ar_prev3 := log1p(frollmean(shift(cases, h + delay + 1), 3)), by = city]; rhs <- c(rhs, "ar_prev3") }
  if (use_lvl) { dd[, lvl := log((frollsum(shift(cases, h + delay), 52) + 0.5) / (pop / 1e5)), by = city]; rhs <- c(rhs, "lvl") }
  cbn <- character(0)
  if (use_rain) {
    kn <- quantile(dd[[rain_train]][pin & win], VAR_Q)
    bd <- range(c(dd[[rain_train]], dd[[rain_test]]), na.rm = TRUE)
    mk <- function(x) crossbasis(x, lag = c(h, L), group = dd$city,
                                 argvar = list(fun = "ns", knots = kn, Boundary.knots = bd),
                                 arglag = list(fun = "ns", knots = logknots(c(h, L), NK)))
    B <- unclass(mk(dd[[rain_train]]))[, , drop = FALSE]
    if (rain_test != rain_train) { Bt <- unclass(mk(dd[[rain_test]])); B[te, ] <- Bt[te, ] }   # forecast with the test source
    B <- B[, seq_len(ncol(B)), drop = FALSE]
    if (!is.null(flood_e)) B <- B * (1 + g * unname(flood_e[dd$city]))
    if (grepl("^regional", variant)) {
      lz <- dd$region == "Luzon"
      cbn <- c(paste0("cbL", seq_len(ncol(B))), paste0("cbV", seq_len(ncol(B))))
      dd[, (cbn) := as.data.table(cbind(B * lz, B * !lz))]
    } else { cbn <- paste0("cb", seq_len(ncol(B))); dd[, (cbn) := as.data.table(B)] }
    rhs <- c(rhs, cbn)
  }
  rvn <- character(0)
  if (use_riv || use_rivs) {
    ind <- if (riv_all) rep(1, nrow(dd)) else as.numeric(dd$river_used %in% TRUE)
    trn <- pin & win & ind == 1
    if (use_riv) {
      rk <- quantile(dd$river_z[trn], VAR_Q, na.rm = TRUE); rb <- range(dd$river_z, na.rm = TRUE)
      R <- unclass(crossbasis(dd$river_z, lag = c(h, L), group = dd$city, argvar = list(fun = "ns", knots = rk, Boundary.knots = rb),
                              arglag = list(fun = "ns", knots = logknots(c(h, L), NK))))
      R <- R[, seq_len(ncol(R)), drop = FALSE] * ind
    } else {
      dd[, rs := frollmean(shift(river_z, h), 4), by = city]                       # mean of lags h..h+3
      tr_rs <- dd$rs[trn & !is.na(dd$rs)]; nb <- ns(tr_rs, df = 3)
      R <- matrix(NA_real_, nrow(dd), 3); okr <- !is.na(dd$rs)
      R[okr, ] <- predict(nb, newx = pmin(pmax(dd$rs[okr], min(tr_rs)), max(tr_rs))); R <- R * ind
    }
    rvn <- paste0("rv", seq_len(ncol(R))); dd[, (rvn) := as.data.table(R)]; rhs <- c(rhs, rvn)
  }
  f <- as.formula(paste("y ~", paste(rhs, collapse = " + "), "+ offset(log_offset)"))
  need <- c(cbn, rvn, if (use_ar) "ar", if (use_ar4) "ar_prev3", if (use_lvl) "lvl")
  okrow <- if (length(need)) complete.cases(dd[, need, with = FALSE]) else rep(TRUE, nrow(dd))
  m <- dd[tr & okrow]
  m[, `:=`(city = factor(city), dgrp = factor(dgrp))]
  st <- tryCatch(coef(suppressWarnings(glm(f, family = poisson, data = m))), error = function(e) NA)
  fit1 <- function(ctrl, start) tryCatch(suppressWarnings(glmmTMB(f, family = nbinom2, dispformula = ~ 0 + dgrp, data = m,
                                         control = ctrl, start = start)), error = function(e) NULL)
  good <- function(x) !is.null(x) && x$fit$convergence == 0 && isTRUE(x$sdr$pdHess)
  # fallback order: nlminb with Poisson starts -> nlminb, no starts -> BFGS with Poisson starts
  sv <- if (anyNA(st)) list() else list(beta = unname(st))
  fit <- fit1(CTRL, sv); how <- "nlminb"
  if (!good(fit)) { f2 <- fit1(CTRL, list()); if (good(f2) || is.null(fit)) { fit <- f2; how <- "nlminb, no starts" } }
  if (!good(fit)) { f3 <- fit1(glmmTMBControl(optimizer = optim, optArgs = list(method = "BFGS", maxit = 5000)), sv)
                    if (good(f3) || is.null(fit)) { fit <- f3; how <- "BFGS" } }
  if (is.null(fit)) return(if (ll_only) -Inf else NULL)
  ok <- good(fit)
  if (ll_only) return(as.numeric(logLik(fit)))
  nd <- dd[(tr | te) & okrow]
  nd[, `:=`(city = factor(city, levels = levels(m$city)), dgrp = factor(dgrp, levels = levels(m$dgrp)))]
  if (!"flag_covid" %in% rhs) nd[, flag_covid := FALSE]
  nd[, eta := predict(fit, newdata = nd, type = "link", allow.new.levels = FALSE)]
  th <- exp(fixef(fit)$disp); names(th) <- sub("^dgrp", "", names(th))
  nd[, theta := th[as.character(dgrp)]]
  nd[, .(origin, h, variant, rain_train, rain_test, delay, converged = ok, optimiser = how,
         set = fifelse(is_te, "test", "train"), city = as.character(city), city_type, year, mw, start, days,
         include, cases, y, mu = exp(eta), theta, thr_std5, thr_exc5, above_std5, above_exc5)]
}

# ---- Run (or reuse) all forecasts --------------------------------------------------------
FC <- file.path(OUT, "forecasts.csv.gz")
run_jobs <- function(jobs) {
  res <- mclapply(seq_len(nrow(jobs)), function(i) {
    j <- jobs[i]; t0 <- Sys.time()
    r <- tryCatch(fit_forecast(j$origin, j$h, j$variant, j$rain_train, j$rain_test, j$delay), error = function(e) { message("FAIL ", paste(j, collapse = " "), ": ", conditionMessage(e)); NULL })
    message(sprintf("%s | origin %d h %d %-12s %s->%s delay %d  %.0fs %s", format(Sys.time(), "%H:%M:%S"), j$origin, j$h, j$variant,
                    j$rain_train, j$rain_test, j$delay, as.numeric(difftime(Sys.time(), t0, units = "secs")),
                    if (is.null(r)) "FAILED" else if (!r$converged[1]) "(not converged)" else ""))
    # keep test rows + training rows with a threshold (used to choose alert cut-offs)
    if (is.null(r)) NULL else r[set == "test" | !is.na(thr_std5) | !is.na(thr_exc5)]
  }, mc.cores = CORES, mc.preschedule = FALSE)
  rbindlist(res)
}
if (!file.exists(FC) || Sys.getenv("STAGE5_REFIT") == "1") {
  log_step("Main runs:", length(ORIGINS) * length(HORIZONS) * length(VARIANTS), "fits on", CORES, "cores")
  main_jobs <- CJ(origin = ORIGINS, h = HORIZONS, variant = VARIANTS)[, `:=`(rain_train = MAIN_RAIN, rain_test = MAIN_RAIN, delay = DELAY)]
  fc <- run_jobs(main_jobs)
  fwrite(fc, FC)
} else fc <- fread(FC)
fc[, start := as.IDate(start)]

# ---- Scoring helpers ------------------------------------------------------------------------
p_exceed <- function(mu, theta, thr, days) 1 - pnbinom(floor(thr * days / 7), size = theta, mu = mu)
pick_cut <- function(p, a, rule = c("youden", "sens70")) {
  rule <- match.arg(rule); ok <- !is.na(p) & !is.na(a); p <- p[ok]; a <- a[ok]
  if (sum(a) < 3) return(NA_real_)
  grid <- seq(0.01, 0.95, by = 0.01)
  sens <- sapply(grid, function(c) mean(p[a] >= c)); spec <- sapply(grid, function(c) mean(p[!a] < c))
  if (rule == "youden") grid[which.max(sens + spec - 1)] else { g <- grid[sens >= 0.70]; if (length(g)) max(g) else min(grid) }
}
add_alerts <- function(x) {
  for (v in names(VERSIONS)) x[, (paste0("p_", v)) := p_exceed(mu, theta, get(paste0("thr_", v)), days)]
  cuts <- x[set == "train", {
    r <- list()
    for (v in names(VERSIONS)) { r[[paste0("cut_", v)]] <- pick_cut(get(paste0("p_", v)), get(paste0("above_", v)), "youden")
                                 r[[paste0("cut70_", v)]] <- pick_cut(get(paste0("p_", v)), get(paste0("above_", v)), "sens70") }
    r
  }, by = .(origin, h, variant, rain_train, rain_test, delay)]
  x <- merge(x[set == "test"], cuts, by = c("origin", "h", "variant", "rain_train", "rain_test", "delay"))
  for (v in names(VERSIONS)) {
    x[, (paste0("alert_", v)) := get(paste0("p_", v)) >= get(paste0("cut_", v))]
    x[, (paste0("alert70_", v)) := get(paste0("p_", v)) >= get(paste0("cut70_", v))]
  }
  list(test = x, cuts = cuts)
}
score_counts <- function(x, by) x[include == TRUE & !is.na(y), .(weeks = .N, mae = mean(abs(y - mu)),
  mae_median = mean(abs(y - qnbinom(0.5, size = theta, mu = mu))),
  log_score = -mean(dnbinom(y, size = theta, mu = mu, log = TRUE))), by = by]
score_alerts <- function(x, by, prefix = "alert_") {
  rbindlist(lapply(names(VERSIONS), function(v) {
    x[include == TRUE & !is.na(get(paste0("above_", v))) & !is.na(get(paste0(prefix, v))), {
      a <- get(paste0("above_", v)); al <- get(paste0(prefix, v))
      .(threshold = VERSIONS[[v]], weeks = .N, outbreak_weeks = sum(a), alerts = sum(al),
        sensitivity = if (sum(a)) sum(al & a) / sum(a) else NA_real_,
        specificity = sum(!al & !a) / sum(!a),
        precision = if (sum(al)) sum(al & a) / sum(al) else NA_real_,
        false_alarms_per_city_year = sum(al & !a) / (uniqueN(paste(city, year))))
    }, by = by]
  }))
}
groups <- function(x) rbind(copy(x)[, grp := fifelse(city_type == "low-case", "Low-case cities (pooled)", city)],
                            copy(x)[, grp := "All cities"])

al <- add_alerts(fc); te <- al$test
fwrite(al$cuts, file.path(OUT, "alert_cutoffs.csv"))

# ---- Persistence baseline (B): next week = last known week ------------------------------------
pers <- d[in_pidsr_period == TRUE & year >= min(ORIGINS) + 1L]
pers_all <- rbindlist(lapply(HORIZONS, function(h) {
  x <- copy(d)[, `:=`(pc = shift(cases, h + DELAY), pa_std5 = shift(above_std5, h + DELAY), pa_exc5 = shift(above_exc5, h + DELAY)), by = city]
  x[in_pidsr_period == TRUE & year >= min(ORIGINS) + 1L, .(h, variant = "persistence", city, city_type, year, mw, start, include, y, mu = pc,
                                                         above_std5, above_exc5, alert_std5 = pa_std5 %in% TRUE, alert_exc5 = pa_exc5 %in% TRUE)]
}))

# ---- Metrics -----------------------------------------------------------------------------------
log_step("Scoring")
cnt <- score_counts(groups(te), c("variant", "h", "grp"))
cnt_p <- pers_all[include == TRUE & !is.na(y) & !is.na(mu), .(grp = "All cities", weeks = .N, mae = mean(abs(y - mu)), mae_median = mean(abs(y - mu)), log_score = NA_real_), by = .(variant, h)]
cnt <- rbind(cnt, cnt_p, fill = TRUE)
base_mae <- cnt[variant == "seasonal", .(h, grp, mae_seasonal = mae)]
cnt <- merge(cnt, base_mae, by = c("h", "grp"), all.x = TRUE)[, mae_skill_vs_seasonal := round(1 - mae / mae_seasonal, 3)]
fwrite(cnt[order(grp, h, variant)], file.path(OUT, "count_scores.csv"))
cnt_nocovid <- score_counts(groups(te[year <= 2019]), c("variant", "h", "grp"))
fwrite(cnt_nocovid[order(grp, h, variant)], file.path(OUT, "count_scores_2014_2019.csv"))

alr <- rbind(score_alerts(groups(te), c("variant", "h", "grp")),
             score_alerts(pers_all[, grp := "All cities"], c("variant", "h", "grp")))
fwrite(alr[order(threshold, grp, h, variant)], file.path(OUT, "alert_scores.csv"))
alr70 <- score_alerts(groups(te), c("variant", "h", "grp"), prefix = "alert70_")
fwrite(alr70[order(threshold, grp, h, variant)], file.path(OUT, "alert_scores_sens70.csv"))
fwrite(score_alerts(groups(te[year <= 2019]), c("variant", "h", "grp"))[order(threshold, grp, h, variant)], file.path(OUT, "alert_scores_2014_2019.csv"))

# threshold-free alert measures: AUC (ranking) and Brier score
auc <- function(p, a) { ok <- !is.na(p) & !is.na(a); p <- p[ok]; a <- a[ok]; n1 <- sum(a); n0 <- sum(!a)
  if (!n1 || !n0) return(NA_real_); (sum(rank(p)[a]) - n1 * (n1 + 1) / 2) / (n1 * n0) }
prob <- rbindlist(lapply(names(VERSIONS), function(v) groups(te)[include == TRUE & !is.na(get(paste0("above_", v))),
  .(threshold = VERSIONS[[v]], auc = auc(get(paste0("p_", v)), get(paste0("above_", v))),
    brier = mean((get(paste0("p_", v)) - get(paste0("above_", v)))^2, na.rm = TRUE)), by = .(variant, h, grp)]))
bs0 <- prob[variant == "seasonal", .(h, grp, threshold, brier_seasonal = brier)]
prob <- merge(prob, bs0, by = c("h", "grp", "threshold"))[, brier_skill_vs_seasonal := round(1 - brier / brier_seasonal, 3)]
fwrite(prob[order(threshold, grp, h, variant)], file.path(OUT, "probability_scores.csv"))

# paired comparisons of log score: block bootstrap over city-years (2,000 resamples)
set.seed(2024)
ls_cy <- te[include == TRUE & !is.na(y), .(ls = -sum(dnbinom(y, size = theta, mu = mu, log = TRUE)), n = .N), by = .(variant, h, city, year)]
PAIRS <- list(c("pooled", "seasonal", "Rain vs no rain"), c("pooled_ar", "pooled", "Adding last week's cases (pooled)"),
              c("regional_ar", "regional", "Adding last week's cases (regional)"), c("regional", "pooled", "Regional vs pooled rain curve"),
              c("regional_ar", "pooled_ar", "Regional vs pooled (with last week's cases)"), c("pooled_ar", "seasonal", "Pooled rain + cases vs seasonal only"))
cmp <- rbindlist(lapply(PAIRS, function(pr) rbindlist(lapply(HORIZONS, function(hh) {
  w <- dcast(ls_cy[h == hh & variant %in% pr[1:2]], city + year + n ~ variant, value.var = "ls")
  w <- w[complete.cases(w)]; dd_ <- w[[pr[2]]] - w[[pr[1]]]
  bt <- replicate(2000, { i <- sample(nrow(w), replace = TRUE); sum(dd_[i]) / sum(w$n[i]) })
  data.table(comparison = pr[3], better = pr[1], than = pr[2], h = hh, gain_per_week = sum(dd_) / sum(w$n),
             lo = quantile(bt, .025), hi = quantile(bt, .975), city_years_better = sum(dd_ > 0), city_years = nrow(w))
}))))
fwrite(cmp, file.path(OUT, "paired_comparisons.csv"))

# best variant: lowest mean log score at horizons 1-2, all cities
best <- cnt[grp == "All cities" & h %in% 1:2 & variant != "persistence" & variant != "seasonal", .(ls = mean(log_score)), by = variant][order(ls)][1, variant]
log_step("Best variant by log score (h 1-2):", best)

# ---- Episodes: warned in advance? ------------------------------------------------------------
ep <- fread(file.path(PATHS$out, "stage4", "outbreak_episodes.csv"))[version %in% names(VERSIONS)][, start := as.IDate(start)][year(start) >= min(ORIGINS) + 1L]
ep_warn <- rbindlist(lapply(names(VERSIONS), function(v) {
  e <- ep[version == v]
  rbindlist(lapply(c(VARIANTS, "persistence"), function(vr) {
    src <- if (vr == "persistence") pers_all else te[variant == vr]
    a <- src[, .(city, start, h, alert = get(paste0("alert_", v)))]
    w <- merge(e[, .(city, start, weeks)], a, by = c("city", "start"), all.x = TRUE)
    w[, .(threshold = VERSIONS[[v]], variant = vr, episodes = uniqueN(paste(city, start)),
          warned = sum(alert %in% TRUE)), by = .(h, episode_length = fifelse(weeks == 1, "single week", "2+ weeks"))]
  }))
}))
ep_warn[, pct_warned := round(100 * warned / episodes, 1)]
fwrite(ep_warn[order(threshold, episode_length, variant, h)], file.path(OUT, "episodes_warned.csv"))

# ---- Calibration (best variant, h = 1 and 2) ----------------------------------------------------
cal <- rbindlist(lapply(names(VERSIONS), function(v) {
  te[variant == best & h %in% 1:2 & include == TRUE & !is.na(get(paste0("above_", v))),
     .(p = get(paste0("p_", v)), a = get(paste0("above_", v)), h)][
    , bin := cut(p, c(0, .02, .05, .1, .2, .3, .5, 1), include.lowest = TRUE)][
    , .(threshold = VERSIONS[[v]], weeks = .N, mean_forecast = mean(p), observed = mean(a)), by = .(h, bin)]
}))
fwrite(cal[order(threshold, h, bin)], file.path(OUT, "calibration.csv"))

# ---- Checks for the best variant: rainfall source and reporting delay ----------------------------
CK <- file.path(OUT, "forecasts_checks.csv.gz")
if (!file.exists(CK) || Sys.getenv("STAGE5_REFIT") == "1") {
  log_step("Checks for", best)
  ck_jobs <- rbind(CJ(origin = ORIGINS, h = HORIZONS, variant = best)[, `:=`(rain_train = "pr_week_imf", rain_test = "pr_week_imf", delay = DELAY)],
                   CJ(origin = ORIGINS, h = HORIZONS, variant = best)[, `:=`(rain_train = "pr_week_imf", rain_test = "pr_week_iml", delay = DELAY)],
                   CJ(origin = ORIGINS, h = HORIZONS, variant = best)[, `:=`(rain_train = MAIN_RAIN, rain_test = MAIN_RAIN, delay = 0L)])
  ck <- run_jobs(ck_jobs); fwrite(ck, CK)
} else ck <- fread(CK)
ck[, start := as.IDate(start)]
ck_te <- add_alerts(ck)$test
lab <- function(x) x[, check := fcase(rain_train == "pr_week_imf" & rain_test == "pr_week_imf", "Final -> Final",
                                       rain_train == "pr_week_imf" & rain_test == "pr_week_iml", "Final -> Late",
                                       delay == 0L, "Late -> Late, no reporting delay",
                                       default = "Late -> Late (main)")]
main_best <- lab(te[variant == best]); ck_te <- lab(ck_te)
both <- rbind(main_best, ck_te, fill = TRUE)
ck_cnt <- both[include == TRUE & !is.na(y), .(mae = mean(abs(y - mu)), log_score = -mean(dnbinom(y, size = theta, mu = mu, log = TRUE))), by = .(check, h)]
ck_alr <- score_alerts(copy(both)[, grp := "All cities"], c("check", "h", "grp"))
fwrite(ck_cnt[order(h, check)], file.path(OUT, "checks_counts.csv")); fwrite(ck_alr[order(threshold, h, check)], file.path(OUT, "checks_alerts.csv"))

# ---- Figures ---------------------------------------------------------------------------------------
log_step("Figures")
BLUE <- "#2a78d6"; ORANGE <- "#eb6834"; AQUA <- "#1baf7a"; YELLOW <- "#eda100"; GREY <- "#8a8984"; INK <- "#0b0b0b"; VIOLET <- "#6250d6"
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top",
          strip.text = element_text(face = "bold", hjust = 0), plot.title.position = "plot"))
save_fig <- function(p, name, w = 9, h = 4.5) ggsave(file.path(FIG, name), p, width = w, height = h, dpi = 150, bg = "white")
VCOL <- c(seasonal = GREY, pooled = BLUE, pooled_ar = AQUA, regional = ORANGE, regional_ar = VIOLET, persistence = YELLOW)
VLAB <- c(seasonal = "Seasonal only (baseline A)", pooled = "Pooled rain", pooled_ar = "Pooled rain + last week's cases",
          regional = "Regional rain", regional_ar = "Regional rain + last week's cases", persistence = "Persistence (baseline B)")

sk <- cnt[grp == "All cities"]
sk <- merge(sk, sk[variant == "seasonal", .(h, ls0 = log_score, mm0 = mae_median)], by = "h")
sk <- rbind(sk[variant != "seasonal" & variant != "persistence", .(variant, h, panel = "Log score: gain per week vs seasonal only", value = ls0 - log_score)],
            sk[variant != "seasonal", .(variant, h, panel = "Typical error (MAE of median forecast): % better than seasonal only", value = 100 * (1 - mae_median / mm0))])
p <- ggplot(sk, aes(h, value, colour = variant)) +
  geom_hline(yintercept = 0, colour = GREY, linewidth = 0.4) + geom_line(linewidth = 0.9) + geom_point(size = 2.2) +
  facet_wrap(~panel, scales = "free_y") +
  scale_colour_manual(values = VCOL, labels = VLAB, name = NULL) + scale_x_continuous(breaks = HORIZONS) +
  guides(colour = guide_legend(nrow = 2)) +
  labs(x = "Forecast horizon (weeks ahead)", y = "Higher is better")
save_fig(p, "count_skill_by_horizon.png")

ap <- alr[grp == "All cities"]
apl <- melt(ap, id.vars = c("variant", "h", "threshold"), measure.vars = c("sensitivity", "precision"), variable.name = "metric")
apl[, metric := factor(metric, levels = c("sensitivity", "precision"), labels = c("Outbreak weeks caught (sensitivity)", "Alerts that were real (precision)"))]
p <- ggplot(apl, aes(h, value, colour = variant)) + geom_line(linewidth = 0.8) + geom_point(size = 1.8) +
  facet_grid(metric ~ threshold) + scale_colour_manual(values = VCOL, labels = VLAB, name = NULL) +
  scale_y_continuous(labels = scales::percent, limits = c(0, 1)) + scale_x_continuous(breaks = HORIZONS) +
  guides(colour = guide_legend(nrow = 2)) + labs(x = "Forecast horizon (weeks ahead)", y = NULL)
save_fig(p, "alert_performance.png", h = 6)

cl <- copy(cal)
p <- ggplot(cl, aes(mean_forecast, observed, colour = threshold)) + geom_abline(slope = 1, intercept = 0, colour = GREY, linetype = "dashed") +
  geom_line(linewidth = 0.8) + geom_point(aes(size = weeks)) + facet_wrap(~ paste0(h, " week", fifelse(h > 1, "s", ""), " ahead")) +
  scale_colour_manual(values = c(Standard = INK, `Outbreak-excluded` = BLUE), name = NULL) + scale_size_area(max_size = 5, guide = "none") +
  scale_x_continuous(labels = scales::percent) + scale_y_continuous(labels = scales::percent) +
  labs(x = "Forecast chance of crossing the threshold", y = "How often it was crossed")
save_fig(p, "calibration.png", h = 4.2)

# trade-off between outbreak weeks caught and false alarms as the cut-off moves (test years; descriptive only,
# the cut-offs actually used are chosen on training years)
grid <- c(seq(0.02, 0.2, 0.01), seq(0.25, 0.6, 0.05))
to <- rbindlist(lapply(c("seasonal", "pooled_ar", "regional_ar"), function(vr) rbindlist(lapply(1:2, function(hh) rbindlist(lapply(names(VERSIONS), function(v) {
  x <- te[variant == vr & h == hh & include == TRUE & !is.na(get(paste0("above_", v)))]
  a <- x[[paste0("above_", v)]]; pp <- x[[paste0("p_", v)]]; ncy <- uniqueN(paste(x$city, x$year))
  data.table(variant = vr, h = hh, threshold = VERSIONS[[v]], cut = grid,
             sensitivity = sapply(grid, function(c) mean(pp[a] >= c, na.rm = TRUE)), fa = sapply(grid, function(c) sum(pp[!a] >= c, na.rm = TRUE) / ncy))
}))))))
fwrite(to, file.path(OUT, "tradeoff_curve.csv"))
used <- rbind(alr[grp == "All cities" & variant %in% unique(to$variant) & h <= 2, .(variant, h, threshold, sensitivity, fa = false_alarms_per_city_year, rule = "Youden (main)")],
              alr70[grp == "All cities" & variant %in% unique(to$variant) & h <= 2, .(variant, h, threshold, sensitivity, fa = false_alarms_per_city_year, rule = "70% sensitivity (check)")])
p <- ggplot(to, aes(fa, sensitivity, colour = variant)) + geom_path(linewidth = 0.8) +
  geom_point(data = used, aes(shape = rule), size = 2.6) +
  facet_grid(paste0(h, " week", fifelse(h > 1, "s", ""), " ahead") ~ threshold) +
  scale_colour_manual(values = VCOL, labels = VLAB, name = NULL) + scale_shape_manual(values = c(16, 17), name = "Cut-off rule") +
  scale_y_continuous(labels = scales::percent, limits = c(0, 1)) + guides(colour = guide_legend(nrow = 1), shape = guide_legend(nrow = 1)) +
  theme(legend.box = "vertical") +
  labs(x = "False alarms per city per year", y = "Outbreak weeks caught")
save_fig(p, "tradeoff.png", h = 6)

city_order <- d[include == TRUE, .(n = sum(cases)), by = city][order(-n), city]
for (cc in city_order) {
  x <- te[variant == best & city == cc & h %in% 1:2][order(start)]
  x[, `:=`(lo = qnbinom(.1, size = theta, mu = mu), hi = qnbinom(.9, size = theta, mu = mu))]
  x[, hz := factor(paste0(h, " week", fifelse(h > 1, "s", ""), " ahead"))]
  p <- ggplot(x, aes(start)) + geom_ribbon(aes(ymin = lo, ymax = hi), fill = BLUE, alpha = 0.15) +
    geom_col(aes(y = cases), fill = "#c9c8c2", width = 7) + geom_line(aes(y = mu), colour = BLUE, linewidth = 0.5) +
    geom_point(data = x[alert_exc5 == TRUE], aes(y = -0.03 * max(x$cases, na.rm = TRUE)), colour = ORANGE, shape = 17, size = 1.2) +
    facet_wrap(~hz, ncol = 1) + scale_x_date(date_breaks = "1 year", date_labels = "'%y", expand = c(0.005, 0)) +
    labs(x = NULL, y = "Cases per week", title = cc,
         subtitle = "Bars observed; line forecast with 80% interval; triangles = alerts (outbreak-excluded threshold)")
  save_fig(p, sprintf("forecast_%s.png", gsub(" ", "_", cc)), h = 5)
}
# Navotas 2018 timeline
nv <- te[variant == best & city == "Navotas" & start >= as.IDate("2018-05-01") & start <= as.IDate("2018-10-31")]
nv_obs <- d[city == "Navotas" & start >= as.IDate("2018-05-01") & start <= as.IDate("2018-10-31"), .(start, cases, above_exc5)]
p <- ggplot(nv, aes(start, p_exc5, colour = factor(h))) +
  geom_col(data = nv_obs, aes(start, cases / max(nv_obs$cases), fill = above_exc5), inherit.aes = FALSE, width = 7, alpha = 0.5) +
  geom_line(linewidth = 0.8) + geom_point(size = 1.4) +
  geom_hline(data = unique(nv[, .(h, cut_exc5)]), aes(yintercept = cut_exc5, colour = factor(h)), linetype = "dashed", linewidth = 0.3) +
  scale_fill_manual(values = c(`FALSE` = "#c9c8c2", `TRUE` = ORANGE), guide = "none") +
  scale_colour_manual(values = c(`1` = BLUE, `2` = AQUA, `3` = ORANGE, `4` = VIOLET), name = "Weeks ahead") +
  scale_y_continuous(labels = scales::percent, sec.axis = sec_axis(~ . * max(nv_obs$cases), name = "Cases (bars)")) +
  labs(x = NULL, y = "Forecast chance of crossing the threshold", subtitle = "Navotas, May-Oct 2018. Bars: cases (orange = above outbreak-excluded threshold). Dashed: alert cut-offs.")
save_fig(p, "navotas_2018.png", h = 4.2)

log_step("Done")
print(cnt[grp == "All cities"][order(h, variant)]); print(alr[grp == "All cities"][order(threshold, h, variant)])
print(ep_warn[variant %in% c(best, "seasonal", "persistence")][order(threshold, episode_length, variant, h)]); print(ck_cnt); print(ck_alr)
