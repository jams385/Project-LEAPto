# =============================================================================
# 03_dlnm.R  —  Stage 3: pooled distributed lag non-linear model (DLNM)
#
# Inputs  : data/processed/city_week{,_altA,_altB}.rds  (from 01_build_dataset.R incl. IMERG)
# Outputs : output/stage3/*.csv, output/stage3/figs/*.png, output/stage3/main_model.rds
#
# Main model:
#   cases ~ city + city x seasonality (3 Fourier pairs) + city x trend (natural spline, 7 df)
#           + COVID indicator + crossbasis(IMERG Final weekly rain, lags 0..L) + offset(log(pop * days/7))
#   negative binomial, city-specific dispersion (glmmTMB), default data-quality exclusions.
#   Crossbasis: natural spline in rainfall (knots at pooled percentiles), natural spline in lag
#   (knots equally spaced on the log scale), lags computed within each city.
#   Relative risks are against a TYPICAL WEEK (pooled median weekly rainfall); a dry-week (0 mm)
#   column is also reported.
# Dispersion: one parameter per city, except the three smallest cities (Legazpi, Mandaue, Palayan;
#   39-62 cases each), which share one. Fallback step (b) was needed by about half the models in the
#   first run, so it is applied to every model to keep AIC comparisons like-for-like.
# Convergence fallback (in order, recorded per model): a) Poisson starting values + more
#   iterations (with the grouped dispersion above); c) simpler baseline (2 Fourier pairs, 5-df trend);
#   d) two-step model with each city's baseline fixed as an offset.
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages({ library(dlnm); library(splines); library(glmmTMB); library(ggplot2); library(MASS) })
OUT <- file.path(PATHS$out, "stage3"); FIG <- file.path(OUT, "figs")
dir.create(FIG, recursive = TRUE, showWarnings = FALSE)
set.seed(20261021)

MAIN_RAIN <- "pr_week_imf"
LAGS      <- c(4L, 6L, 8L, 10L)
VAR_SPECS <- list(`knots P50` = c(.50), `knots P50, P90` = c(.50, .90), `knots P25, P50, P75` = c(.25, .50, .75))
LAG_NK    <- c(1L, 2L, 3L)       # number of internal lag knots (log scale) -> 3, 4, 5 lag df
DEFAULT   <- list(L = 8L, var = "knots P50, P90", nk = 2L)
N_SIM     <- 1000L
LUZON     <- c("Dagupan", "Palayan", "Navotas", "Mandaluyong", "Muntinlupa", "Legazpi")
SMALL     <- c("Legazpi", "Mandaue", "Palayan")   # share one dispersion parameter
CTRL      <- glmmTMBControl(optCtrl = list(iter.max = 1e4, eval.max = 1e4))
F3 <- c("s1", "c1", "s2", "c2", "s3", "c3"); TR7 <- paste0("t", 1:7)

BLUE <- "#2a78d6"; ORANGE <- "#eb6834"; AQUA <- "#1baf7a"; YELLOW <- "#eda100"; GREY <- "#8a8984"; INK <- "#0b0b0b"
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top",
          strip.text = element_text(face = "bold", hjust = 0), plot.title.position = "plot"))
save_fig <- function(p, name, w = 9, h = 4.5) ggsave(file.path(FIG, name), p, width = w, height = h, dpi = 150, bg = "white")

# ---- Data preparation -------------------------------------------------------
prep <- function(file = "city_week.rds") {
  d <- readRDS(file.path(PATHS$processed, file))[order(city, start)]
  d[, time := seq_len(.N), by = city]
  d[, (F3) := list(sin(2*pi*mw/52), cos(2*pi*mw/52), sin(4*pi*mw/52), cos(4*pi*mw/52), sin(6*pi*mw/52), cos(6*pi*mw/52))]
  d[in_pidsr_period == TRUE, (TR7) := as.data.table(ns(time, df = 7)), by = city]
  d[in_pidsr_period == TRUE, paste0("u", 1:5) := as.data.table(ns(time, df = 5)), by = city]
  d[, y := fifelse(include, cases, NA_integer_)]
  d[, region := fifelse(city %in% LUZON, "Luzon", "Visayas/Mindanao")]
  d[, dgrp := fifelse(city %in% SMALL, "small cities", city)]
  d[, ar1 := log1p(shift(cases, 1)), by = city]
  d[, tave4 := frollmean(tave, 4), by = city]          # mean temperature over lags 0-3
  d[, rain_avg := (pr_week + pr_week_imf) / 2]
  d[]
}

# ---- Model fitting with fallback --------------------------------------------
make_cb <- function(d, rain, L, var_q, nk) {
  x <- d[[rain]]; pin <- d$in_pidsr_period & !is.na(x)
  crossbasis(x, lag = L, group = d$city,
             argvar = list(fun = "ns", knots = quantile(x[pin], var_q), Boundary.knots = range(x, na.rm = TRUE)),
             arglag = list(fun = "ns", knots = logknots(L, nk)))
}

fit_dlnm <- function(d, rain = MAIN_RAIN, L = DEFAULT$L, var_q = VAR_SPECS[[DEFAULT$var]], nk = DEFAULT$nk,
                     extra = NULL, offset_col = "log_offset", label = "") {
  cb <- make_cb(d, rain, L, var_q, nk)
  cbn <- paste0("cb", seq_len(ncol(cb)))
  dd <- copy(d); dd[, (cbn) := as.data.table(unclass(cb)[, seq_len(ncol(cb)), drop = FALSE])]
  dd[, off := get(offset_col)]
  m <- dd[in_pidsr_period == TRUE & !is.na(y) & complete.cases(dd[, c(cbn, extra), with = FALSE])]
  m[, `:=`(city = factor(city), dgrp = factor(dgrp))]
  covid <- if (uniqueN(m$flag_covid) > 1) "flag_covid" else NULL
  rhs_full <- paste(c("city", paste0("city:(", paste(F3, collapse = "+"), ")"), paste0("city:(", paste(TR7, collapse = "+"), ")"), covid, extra, cbn), collapse = " + ")
  rhs_simple <- paste(c("city", paste0("city:(", paste(F3[1:4], collapse = "+"), ")"), "city:(u1+u2+u3+u4+u5)", covid, extra, cbn), collapse = " + ")
  try_fit <- function(rhs, disp, data) {
    f <- as.formula(paste("y ~", rhs, "+ offset(off)"))
    po <- suppressWarnings(glm(f, family = poisson, data = data))
    st <- coef(po); if (anyNA(st)) return(NULL)
    fit <- tryCatch(suppressWarnings(glmmTMB(f, family = nbinom2, dispformula = disp, data = data, control = CTRL,
                                             start = list(beta = unname(st)))), error = function(e) NULL)
    if (!is.null(fit) && fit$fit$convergence == 0 && isTRUE(fit$sdr$pdHess)) fit else NULL
  }
  step <- "a"; fit <- try_fit(rhs_full, ~ 0 + dgrp, m)
  if (is.null(fit)) { step <- "c"; fit <- try_fit(rhs_simple, ~ 0 + dgrp, m) }
  if (is.null(fit)) {
    step <- "d"   # two-step: per-city baseline as fixed offset
    m[, base_off := NA_real_]
    for (cc in levels(m$city)) {
      sub <- m[city == cc]
      rb <- paste(c(F3, TR7, if (uniqueN(sub$flag_covid) > 1) "flag_covid"), collapse = " + ")
      bf <- glmmTMB(as.formula(paste("y ~", rb, "+ offset(off)")), family = nbinom2, data = sub, control = CTRL)
      m[city == cc, base_off := log(pmax(fitted(bf), 1e-6))]
    }
    fit <- glmmTMB(as.formula(paste("y ~", paste(c(extra, cbn), collapse = " + "), "+ offset(base_off)")),
                   family = nbinom2, dispformula = ~ 0 + dgrp, data = m, control = CTRL)
  }
  b <- fixef(fit)$cond; V <- vcov(fit)$cond
  list(model = fit, cb = cb, cbn = cbn, coef = b[cbn], vcov = V[cbn, cbn], data = m, rain = rain, L = L,
       var_q = var_q, nk = nk, step = step, aic = AIC(fit), n = nrow(m), label = label,
       x_all = d[[rain]][d$in_pidsr_period], cen = median(m[[rain]]))
}

pct <- function(fit, p) unname(quantile(fit$x_all, p, na.rm = TRUE))
predict_fit <- function(fit, cen = fit$cen, coef = fit$coef, vcov = fit$vcov) {
  marks <- round(c(0, cen, pct(fit, c(.75, .90, .95, .99))), 1)
  at <- sort(unique(c(seq(0, ceiling(pct(fit, .995)), by = 1), marks)))
  crosspred(fit$cb, coef = coef, vcov = vcov, model.link = "log", at = at, cen = cen, bylag = 0.1)
}
rr_at <- function(cp, x) {
  k <- as.character(round(x, 1))
  data.table(rr = cp$allRRfit[k], lo = cp$allRRlow[k], hi = cp$allRRhigh[k])
}
lag_profile <- function(cp, x) {
  k <- as.character(round(x, 1))
  data.table(lag = as.numeric(sub("lag", "", colnames(cp$matRRfit))), rr = cp$matRRfit[k, ], lo = cp$matRRlow[k, ], hi = cp$matRRhigh[k, ])
}
# Single heavy-rain week: extra cases it causes over the following L weeks, in units of a typical
# week's expected cases = sum over lags of (lag-specific RR - 1). 95% interval by simulating coefficients.
single_event <- function(fit, x, nsim = 500L) {
  f1 <- function(b) sum(crosspred(fit$cb, coef = b, vcov = fit$vcov, model.link = "log", at = round(x, 1),
                                  cen = fit$cen, bylag = 1)$matRRfit - 1)
  sims <- vapply(seq_len(nsim), function(i) f1(mvrnorm(1, fit$coef, fit$vcov)), 0)
  data.table(excess = f1(fit$coef), excess_lo = unname(quantile(sims, .025)), excess_hi = unname(quantile(sims, .975)))
}
summarise_fit <- function(fit, scenario) {
  cp <- predict_fit(fit); p95 <- pct(fit, .95)
  lp <- lag_profile(cp, p95)[lag %% 1 == 0]
  sig <- lp[lo > 1, lag]
  cbind(data.table(scenario = scenario, rain = fit$rain, step = fit$step, n = fit$n,
                   typical_mm = round(fit$cen, 1), p95_mm = round(p95, 1)),
        rr_at(cp, p95)[, .(rr_p95 = rr, lo_p95 = lo, hi_p95 = hi)],
        data.table(peak_lag = lp[which.max(rr), lag], rr_peak_lag = lp[which.max(rr), rr],
                   lags_signif = if (length(sig)) paste(range(sig), collapse = "-") else "none"),
        single_event(fit, p95, nsim = 200L)[, .(excess_p95 = excess, excess_lo_p95 = excess_lo, excess_hi_p95 = excess_hi)])
}

d <- prep()

# ---- 1. Maximum lag and spline choice ----------------------------------------
log_step("1 model selection")
sel_L <- rbindlist(lapply(LAGS, function(L) {
  f <- fit_dlnm(d, L = L); log_step(sprintf("  L=%d AIC %.1f (step %s, n %d)", L, f$aic, f$step, f$n))
  data.table(L = L, var = DEFAULT$var, nk = DEFAULT$nk, aic = f$aic, step = f$step, n = f$n, n_par = length(f$coef))
}))
stopifnot(uniqueN(sel_L$n) == 1)                          # identical rows for every lag
best_L <- sel_L[aic <= min(aic) + 2][order(L)][1, L]       # within 2 AIC of best -> shortest lag
grid <- CJ(var = names(VAR_SPECS), nk = LAG_NK)
sel_S <- rbindlist(lapply(seq_len(nrow(grid)), function(i) {
  f <- fit_dlnm(d, L = best_L, var_q = VAR_SPECS[[grid$var[i]]], nk = grid$nk[i])
  log_step(sprintf("  L=%d %s nk=%d AIC %.1f (step %s)", best_L, grid$var[i], grid$nk[i], f$aic, f$step))
  data.table(L = best_L, var = grid$var[i], nk = grid$nk[i], aic = f$aic, step = f$step, n = f$n, n_par = length(f$coef))
}))
sel <- unique(rbind(sel_L, sel_S), by = c("L", "var", "nk"))[, delta_aic := round(aic - min(aic), 1)][order(aic)]
best_S <- sel_S[aic <= min(aic) + 2][order(n_par, aic)][1]
fwrite(sel, file.path(OUT, "model_selection.csv"))
MAIN <- list(L = best_L, var = best_S$var, nk = best_S$nk)
log_step(sprintf("Main model: L=%d, %s, %d lag knots", MAIN$L, MAIN$var, MAIN$nk))

# ---- 2. Main model ------------------------------------------------------------
log_step("2 main model")
fm <- fit_dlnm(d, L = MAIN$L, var_q = VAR_SPECS[[MAIN$var]], nk = MAIN$nk, label = "main")
# slim copy (coefficients + settings; the fitted object itself is > 30 MB and is refitted in Stage 5)
saveRDS(list(fixef = fixef(fm$model), vcov_cond = vcov(fm$model)$cond, cb_coef = fm$coef, cb_vcov = fm$vcov,
             cen = fm$cen, spec = MAIN, rain = fm$rain, L = fm$L, argvar = attr(fm$cb, "argvar"), arglag = attr(fm$cb, "arglag"),
             formula = paste(deparse(formula(fm$model)), collapse = ""), n = fm$n, aic = fm$aic),
        file.path(OUT, "main_model.rds"))
cp  <- predict_fit(fm)
cp0 <- predict_fit(fm, cen = 0)
P <- c(`P75` = .75, `P90` = .90, `P95` = .95, `P99` = .99)
head_tab <- rbindlist(lapply(names(P), function(nm) {
  x <- pct(fm, P[[nm]])
  cbind(data.table(level = nm, rain_mm = round(x, 1)),
        rr_at(cp, x)[, .(rr_vs_typical = rr, lo_typical = lo, hi_typical = hi)],
        rr_at(cp0, x)[, .(rr_vs_dry = rr, lo_dry = lo, hi_dry = hi)],
        single_event(fm, x),
        lag_profile(cp, x)[lag %% 1 == 0][which.max(rr), .(peak_lag = lag, rr_peak = rr, lo_peak = lo, hi_peak = hi)])
}))
head_tab[, typical_mm := round(fm$cen, 1)]
fwrite(head_tab, file.path(OUT, "headline_rr.csv"))
lag95 <- lag_profile(cp, pct(fm, .95)); lag99 <- lag_profile(cp, pct(fm, .99))
fwrite(rbind(lag95[lag %% 1 == 0][, level := "P95"], lag99[lag %% 1 == 0][, level := "P99"]), file.path(OUT, "lag_response.csv"))
overall <- data.table(rain = as.numeric(names(cp$allRRfit)), rr = cp$allRRfit, lo = cp$allRRlow, hi = cp$allRRhigh)
fwrite(overall, file.path(OUT, "overall_curve.csv"))
main_summary <- summarise_fit(fm, "Main model")
fwrite(data.table(step = fm$step, n = fm$n, aic = fm$aic, typical_mm = fm$cen, L = MAIN$L, var = MAIN$var, nk = MAIN$nk,
                  theta = paste(sprintf("%s=%.2f", levels(fm$data$dgrp), exp(fixef(fm$model)$disp)), collapse = "; ")),
       file.path(OUT, "main_model_info.csv"))

# figures: lag response, overall curve, contour
lp <- rbind(lag95[, level := sprintf("Heavy rain, P95 (%.0f mm)", pct(fm, .95))],
            lag99[, level := sprintf("Very heavy rain, P99 (%.0f mm)", pct(fm, .99))])
p <- ggplot(lp, aes(lag, rr, colour = level, fill = level)) +
  geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_ribbon(aes(ymin = lo, ymax = hi), alpha = 0.15, colour = NA) + geom_line(linewidth = 0.9) +
  scale_colour_manual(values = c(BLUE, ORANGE), name = NULL) + scale_fill_manual(values = c(BLUE, ORANGE), name = NULL) +
  scale_x_continuous(breaks = 0:MAIN$L) +
  labs(x = "Weeks after the rainfall", y = sprintf("Relative risk vs a typical week (%.0f mm)", fm$cen))
save_fig(p, "lag_response.png")
marks <- data.table(x = c(fm$cen, pct(fm, c(.90, .95, .99))), lab = c("typical", "P90", "P95", "P99"))
p <- ggplot(overall, aes(rain, rr)) +
  geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_vline(data = marks, aes(xintercept = x), colour = GREY, linetype = "dashed", linewidth = 0.3) +
  geom_text(data = marks, aes(x = x, y = Inf, label = lab), vjust = 1.5, hjust = -0.1, size = 3, colour = "#52514e") +
  geom_ribbon(aes(ymin = lo, ymax = hi), fill = BLUE, alpha = 0.15) + geom_line(colour = BLUE, linewidth = 0.9) +
  geom_rug(data = data.table(x = fm$x_all), aes(x = x), inherit.aes = FALSE, alpha = 0.05, colour = BLUE, length = unit(0.02, "npc")) +
  scale_y_log10(breaks = c(0.125, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128), labels = c("0.125", "0.25", "0.5", "1", "2", "4", "8", "16", "32", "64", "128")) +
  coord_cartesian(xlim = c(0, max(overall$rain))) +
  labs(x = "Weekly rainfall, IMERG Final (mm per 7 days)", y = sprintf("Cumulative relative risk over %d weeks (log scale)", MAIN$L))
save_fig(p, "overall_curve.png")
cps <- crosspred(fm$cb, coef = fm$coef, vcov = fm$vcov, model.link = "log", cen = fm$cen, bylag = 0.2,
                 at = seq(0, ceiling(pct(fm, .99) / 5) * 5, by = 5))
surf <- as.data.table(as.table(cps$matRRfit)); setnames(surf, c("rain", "lag", "rr"))
surf[, `:=`(rain = as.numeric(as.character(rain)), lag = as.numeric(sub("lag", "", lag)))]
brk <- c(0, 0.8, 0.9, 1.1, 1.25, 1.5, 2, 3, Inf)
surf[, band := cut(rr, brk, labels = c("< 0.8", "0.8-0.9", "0.9-1.1", "1.1-1.25", "1.25-1.5", "1.5-2", "2-3", "> 3"))]
band_cols <- c("< 0.8" = "#e9a07a", "0.8-0.9" = "#f4cdb8", "0.9-1.1" = "#f2f1ee", "1.1-1.25" = "#d6e4f7",
               "1.25-1.5" = "#a9c8ef", "1.5-2" = "#6fa3e4", "2-3" = "#2a78d6", "> 3" = "#174a8c")
p <- ggplot(surf, aes(lag, rain, fill = band)) + geom_tile(width = 0.2, height = 5) +
  scale_fill_manual(values = band_cols, name = "Relative risk vs typical week", drop = FALSE) +
  scale_x_continuous(breaks = 0:MAIN$L, expand = c(0, 0)) + scale_y_continuous(expand = c(0, 0)) +
  guides(fill = guide_legend(nrow = 1, reverse = FALSE)) +
  labs(x = "Weeks after the rainfall", y = "Weekly rainfall, IMERG Final (mm per 7 days)")
save_fig(p, "risk_surface.png", h = 5)

# ---- 3. Diagnostics ----------------------------------------------------------
log_step("3 diagnostics")
m <- fm$data[, `:=`(fit = fitted(fm$model), pres = residuals(fm$model, type = "pearson"))]
m[!is.finite(pres), pres := 0]   # weeks with fitted ~0 and 0 cases (Mandaue 2008-10 had no cases) give 0/0
diag_city <- m[order(city, time), .(cases = sum(y), fitted = round(sum(fit), 1),
                 acf1 = round(cor(pres[-1], pres[-.N]), 3),
                 acf2 = round(cor(pres[-(1:2)], pres[-((.N - 1):.N)]), 3),
                 pearson_disp = round(sum(pres^2) / .N, 2)), by = city]
fwrite(diag_city, file.path(OUT, "diagnostics_by_city.csv"))
fwrite(data.table(overall_pearson_dispersion = round(sum(m$pres^2) / df.residual(fm$model), 3),
                  mean_acf1 = round(mean(diag_city$acf1), 3), max_acf1 = max(diag_city$acf1)), file.path(OUT, "diagnostics_overall.csv"))
city_order <- m[, .(n = sum(y)), by = city][order(-n), as.character(city)]
p <- ggplot(m[, city := factor(city, levels = city_order)], aes(start)) +
  geom_col(aes(y = y), fill = ORANGE, width = 7, alpha = 0.7) + geom_line(aes(y = fit), colour = INK, linewidth = 0.3) +
  facet_wrap(~city, ncol = 3, scales = "free_y") + scale_x_date(date_breaks = "2 years", date_labels = "'%y") +
  labs(x = NULL, y = "Cases per week (bars observed, line fitted)")
save_fig(p, "observed_vs_fitted.png", h = 8)

# ---- 4. Attributable cases ---------------------------------------------------
log_step("4 attributable cases")
attributable <- function(fit, thr_q = NULL) {
  d0 <- d[order(city, start)]; x <- d0[[fit$rain]]
  ax <- attributes(fit$cb)
  # threshold: typical week (pooled median) for "any rain above typical", or each city's own
  # quantile thr_q (e.g. its wettest 5% of weeks) for "heavy rain only"
  thr <- if (is.null(thr_q)) rep(fit$cen, length(x)) else
    d0[, .(t = quantile(get(fit$rain)[in_pidsr_period], thr_q)), by = city][match(d0$city, city), t]
  xmod <- ifelse(x >= pmax(thr, fit$cen), x, fit$cen)           # only rain at/above the threshold counts
  cbm <- crossbasis(xmod, lag = fit$L, group = d0$city, argvar = ax$argvar[c("fun", "knots", "Boundary.knots")], arglag = ax$arglag[c("fun", "knots")])
  cbc <- crossbasis(rep(fit$cen, length(x)), lag = fit$L, group = d0$city, argvar = ax$argvar[c("fun", "knots", "Boundary.knots")], arglag = ax$arglag[c("fun", "knots")])
  key <- d0[, .(city, start)]; Bm <- unclass(cbm)[, seq_len(ncol(cbm))]; Bc <- unclass(cbc)[, seq_len(ncol(cbc))]
  idx <- match(paste(fit$data$city, fit$data$start), paste(key$city, key$start))
  D <- (Bm - Bc)[idx, , drop = FALSE]; yv <- fit$data$y; cty <- as.character(fit$data$city)
  an <- function(b) { lrr <- pmax(drop(D %*% b), 0); yv * (1 - exp(-lrr)) }
  est <- an(fit$coef)
  sims <- sapply(seq_len(N_SIM), function(i) { a <- an(mvrnorm(1, fit$coef, fit$vcov)); c(tapply(a, cty, sum), total = sum(a)) })
  tot <- c(tapply(est, cty, sum), total = sum(est)); cases <- c(tapply(yv, cty, sum), total = sum(yv))
  data.table(city = names(tot), cases = cases[names(tot)], attributable = round(tot, 1),
             lo = round(apply(sims, 1, quantile, .025)[names(tot)], 1), hi = round(apply(sims, 1, quantile, .975)[names(tot)], 1))[
    , `:=`(pct = round(100 * attributable / cases, 1), pct_lo = round(100 * lo / cases, 1), pct_hi = round(100 * hi / cases, 1))]
}
att <- rbind(attributable(fm)[, rain_counted := "Any rain above a typical week"],
             attributable(fm, .95)[, rain_counted := "Heavy rain only (city's wettest 5% of weeks)"])
fwrite(att, file.path(OUT, "attributable_cases.csv"))
pa <- att[city != "total"][, city := factor(city, levels = rev(city_order))]
p <- ggplot(pa, aes(pct, city, colour = rain_counted)) +
  geom_errorbarh(aes(xmin = pct_lo, xmax = pct_hi), height = 0, linewidth = 0.6, position = position_dodge(width = 0.6)) +
  geom_point(size = 2.4, position = position_dodge(width = 0.6)) +
  scale_colour_manual(values = c(BLUE, ORANGE), name = NULL) +
  labs(x = "% of the city's cases (2008-2022) attributable to rainfall", y = NULL)
save_fig(p, "attributable_by_city.png", h = 5)

# ---- 5. Luzon vs Visayas/Mindanao ------------------------------------------------
log_step("5 regional check")
reg <- local({
  f0 <- fm; dd <- copy(f0$data)
  B <- as.matrix(dd[, f0$cbn, with = FALSE])
  L1 <- B * (dd$region == "Luzon"); V1 <- B * (dd$region != "Luzon")
  nL <- paste0("cbL", seq_len(ncol(B))); nV <- paste0("cbV", seq_len(ncol(B)))
  dd[, (nL) := as.data.table(L1)]; dd[, (nV) := as.data.table(V1)]
  rhs <- paste(c("city", paste0("city:(", paste(F3, collapse = "+"), ")"), paste0("city:(", paste(TR7, collapse = "+"), ")"), "flag_covid", nL, nV), collapse = " + ")
  f <- as.formula(paste("y ~", rhs, "+ offset(off)"))
  st <- coef(suppressWarnings(glm(f, family = poisson, data = dd)))
  mr <- glmmTMB(f, family = nbinom2, dispformula = ~ 0 + dgrp, data = dd, control = CTRL, start = list(beta = unname(st)))
  b <- fixef(mr)$cond; V <- vcov(mr)$cond
  lr <- 2 * (as.numeric(logLik(mr)) - as.numeric(logLik(f0$model))); dfd <- length(nL)
  list(model = mr, conv = mr$fit$convergence == 0 && isTRUE(mr$sdr$pdHess), lr = lr, df = dfd, p = pchisq(lr, dfd, lower.tail = FALSE),
       aic_pooled = AIC(f0$model), aic_regional = AIC(mr),
       cpL = predict_fit(f0, coef = b[nL], vcov = V[nL, nL]), cpV = predict_fit(f0, coef = b[nV], vcov = V[nV, nV]))
})
p95 <- pct(fm, .95)
reg_tab <- rbind(cbind(data.table(region = "Pooled (main)"), rr_at(cp, p95)),
                 cbind(data.table(region = "Luzon"), rr_at(reg$cpL, p95)),
                 cbind(data.table(region = "Visayas/Mindanao"), rr_at(reg$cpV, p95)))
reg_tab[, `:=`(lr_stat = round(reg$lr, 2), df = reg$df, p_value = signif(reg$p, 3), aic_pooled = round(reg$aic_pooled, 1),
               aic_regional = round(reg$aic_regional, 1), converged = reg$conv)]
fwrite(reg_tab, file.path(OUT, "regional_check.csv"))
rl <- rbind(lag_profile(reg$cpL, p95)[, region := "Luzon"], lag_profile(reg$cpV, p95)[, region := "Visayas/Mindanao"])
ro <- rbind(data.table(rain = as.numeric(names(reg$cpL$allRRfit)), rr = reg$cpL$allRRfit, lo = reg$cpL$allRRlow, hi = reg$cpL$allRRhigh, region = "Luzon"),
            data.table(rain = as.numeric(names(reg$cpV$allRRfit)), rr = reg$cpV$allRRfit, lo = reg$cpV$allRRlow, hi = reg$cpV$allRRhigh, region = "Visayas/Mindanao"))
fwrite(rl, file.path(OUT, "regional_lag_p95.csv")); fwrite(ro, file.path(OUT, "regional_overall.csv"))
p1 <- ggplot(rl, aes(lag, rr, colour = region, fill = region)) + geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_ribbon(aes(ymin = lo, ymax = hi), alpha = 0.12, colour = NA) + geom_line(linewidth = 0.9) +
  scale_colour_manual(values = c(BLUE, ORANGE), name = NULL) + scale_fill_manual(values = c(BLUE, ORANGE), name = NULL) +
  scale_x_continuous(breaks = 0:MAIN$L) + labs(x = "Weeks after heavy rain (P95)", y = "Relative risk vs typical week")
p2 <- ggplot(ro[rain <= pct(fm, .99)], aes(rain, rr, colour = region, fill = region)) + geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_ribbon(aes(ymin = lo, ymax = hi), alpha = 0.12, colour = NA) + geom_line(linewidth = 0.9) +
  scale_colour_manual(values = c(BLUE, ORANGE), name = NULL) + scale_fill_manual(values = c(BLUE, ORANGE), name = NULL) +
  scale_y_log10(breaks = c(0.125, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64), labels = c("0.125", "0.25", "0.5", "1", "2", "4", "8", "16", "32", "64")) +
  labs(x = "Weekly rainfall, IMERG Final (mm per 7 days)", y = "Cumulative relative risk (log scale)")
if (requireNamespace("patchwork", quietly = TRUE)) save_fig(patchwork::wrap_plots(p1, p2, guides = "collect") & theme(legend.position = "top"), "regional_curves.png") else save_fig(p1, "regional_curves.png")

# ---- 6. Sensitivity analyses ----------------------------------------------------
log_step("6 sensitivity analyses")
spec <- function(dat, ...) fit_dlnm(dat, L = MAIN$L, var_q = VAR_SPECS[[MAIN$var]], nk = MAIN$nk, ...)
mod <- function(expr) { dd <- copy(d); expr(dd); dd }
scen <- list(
  `Rainfall: CHIRPS`                 = function() spec(d, rain = "pr_week"),
  `Rainfall: CHIRPS-IMERG average`   = function() spec(d, rain = "rain_avg"),
  `Rainfall: IMERG Late`             = function() spec(d, rain = "pr_week_iml"),
  `Calendar: Alternative A`          = function() spec(prep("city_week_altA.rds")),
  `Calendar: Alternative B`          = function() spec(prep("city_week_altB.rds")),
  `Without CDO Washi weeks`          = function() spec(mod(function(dd) dd[city == "Cagayan de Oro" & ((year == 2011 & mw == 52) | (year == 2012 & mw %in% 1:2)), y := NA])),
  `Without Cagayan de Oro`           = function() spec(mod(function(dd) dd[city == "Cagayan de Oro", y := NA])),
  `Keep all weeks (no exclusions)`   = function() spec(mod(function(dd) dd[, y := fifelse(in_pidsr_period & !is.na(cases), cases, NA_integer_)])),
  `Adjust for temperature`           = function() spec(mod(function(dd) dd[, paste0("tv", 1:3) := as.data.table(ns(tave4, df = 3))]), extra = paste0("tv", 1:3)),
  `Exclude 2020-2022 (COVID)`        = function() spec(mod(function(dd) dd[year >= 2020, y := NA])),
  `Wettest day instead of weekly total` = function() spec(d, rain = "pr_day_max_imf"),
  `Population held at 2020`          = function() spec(mod(function(dd) dd[, log_offset_carry := log(pop_carry * days / 7)]), offset_col = "log_offset_carry"),
  `Add last week's cases`            = function() spec(d, extra = "ar1")
)
sens <- rbind(main_summary, rbindlist(lapply(names(scen), function(s) {
  f <- scen[[s]](); log_step(sprintf("  %s: step %s, n %d", s, f$step, f$n))
  r <- summarise_fit(f, s)
  r[, lag_curve := list(list(lag_profile(predict_fit(f), pct(f, .95))[lag %% 1 == 0]))]
  r
}), fill = TRUE), fill = TRUE)
sens_out <- copy(sens)[, lag_curve := NULL]
num <- names(sens_out)[vapply(sens_out, is.double, TRUE)]; sens_out[, (num) := lapply(.SD, round, 3), .SDcols = num]
fwrite(sens_out, file.path(OUT, "sensitivity.csv"))
lc <- rbind(lag95[lag %% 1 == 0, .(lag, rr, lo, hi)][, scenario := "Main model"],
            rbindlist(lapply(seq_len(nrow(sens))[-1], function(i) sens$lag_curve[[i]][, .(lag, rr, lo, hi)][, scenario := sens$scenario[i]])))
fwrite(lc, file.path(OUT, "sensitivity_lag_curves.csv"))

fp <- copy(sens_out)[, scenario := factor(scenario, levels = rev(scenario))]
p <- ggplot(fp, aes(rr_p95, scenario)) + geom_vline(xintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_vline(xintercept = sens_out[scenario == "Main model", rr_p95], colour = BLUE, linewidth = 0.3, linetype = "dashed") +
  geom_errorbarh(aes(xmin = lo_p95, xmax = hi_p95), height = 0, colour = BLUE, linewidth = 0.7) +
  geom_point(colour = BLUE, size = 2.6) +
  geom_text(aes(x = hi_p95, label = sprintf("peak lag %d", peak_lag)), hjust = -0.15, size = 2.8, colour = "#52514e") +
  scale_x_continuous(expand = expansion(mult = c(0.05, 0.25))) +
  labs(x = "Cumulative relative risk at the 95th-percentile rainfall week vs a typical week", y = NULL)
save_fig(p, "sensitivity_forest.png", h = 5.5)
grp <- list(`Rainfall source` = c("Main model", "Rainfall: CHIRPS", "Rainfall: CHIRPS-IMERG average", "Rainfall: IMERG Late"),
            `Calendar` = c("Main model", "Calendar: Alternative A", "Calendar: Alternative B"))
lcg <- rbindlist(lapply(names(grp), function(g) lc[scenario %in% grp[[g]]][, panel := g]))
lcg[, scenario := factor(sub("^(Rainfall|Calendar): ", "", scenario), levels = c("Main model", "CHIRPS", "CHIRPS-IMERG average", "IMERG Late", "Alternative A", "Alternative B"))]
p <- ggplot(lcg, aes(lag, rr, colour = scenario)) + geom_hline(yintercept = 1, colour = GREY, linewidth = 0.4) +
  geom_line(linewidth = 0.9) + geom_point(size = 1.6) + facet_wrap(~panel) +
  scale_colour_manual(values = c(`Main model` = BLUE, CHIRPS = GREY, `CHIRPS-IMERG average` = AQUA, `IMERG Late` = ORANGE,
                                 `Alternative A` = YELLOW, `Alternative B` = "#6250d6"), name = NULL) +
  guides(colour = guide_legend(nrow = 1)) +
  scale_x_continuous(breaks = 0:MAIN$L) + labs(x = "Weeks after heavy rain (each source's P95)", y = "Relative risk vs typical week")
save_fig(p, "sensitivity_lag_curves.png")

log_step("Done")
print(sel); print(head_tab); print(lag95[lag %% 1 == 0]); print(fread(file.path(OUT, "main_model_info.csv")))
print(diag_city); print(fread(file.path(OUT, "diagnostics_overall.csv"))); print(att); print(reg_tab); print(sens_out)
