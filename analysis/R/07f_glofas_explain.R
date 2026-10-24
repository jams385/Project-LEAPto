# =============================================================================
# 07f_glofas_explain.R  —  Stage 7c, step 3: does river flow explain cases beyond rain?
#
# Stage 3 main model (all years, IMERG Final rain crossbasis, lags 0-10) plus the weekly GloFAS river signal:
#   M0  rain only (= Stage 3 main)
#   M1  + river signal crossbasis, lags 0-10 (like rain), river cities only        <- main
#   M2  + mean river signal over lags 1-4, 3-df spline, river cities only
#   M3  + river-flood-week flag (peak >= 2-year flood flow), lags 0-10, river cities only
#   M4  + river crossbasis in all 12 cities (check)
# Likelihood-ratio tests and AIC against M0 on identical rows; the river lag-response (risk after a high-river
# week vs a typical one); whether the rain effect shrinks once river flow is included; and the Typhoon Washi
# weeks in Cagayan de Oro (expected vs observed cases, with and without river flow).
# Outputs: output/stage7/river_explain_*.csv, output/stage7/figs/river_*.png
# =============================================================================
src3 <- readLines("R/03_dlnm.R"); eval(parse(text = src3[1:(grep("^d <- prep\\(\\)", src3) - 1)]))
OUT <- file.path(PATHS$out, "stage7"); FIG <- file.path(OUT, "figs")
M3S <- readRDS(file.path(PATHS$out, "stage3", "main_model.rds"))$spec
L <- M3S$L

d <- prep()
riv <- fread(file.path(PATHS$processed, "glofas_city_week.csv"))[, .(city, year, mw, river_z, river_flood, river_used)]
d <- merge(d, riv, by = c("city", "year", "mw"), all.x = TRUE)[order(city, start)]
d[, rs := frollmean(shift(river_z, 1), 4), by = city]                       # mean of lags 1-4
pin <- d$in_pidsr_period
used <- as.numeric(d$river_used %in% TRUE)

cb_rain <- make_cb(d, MAIN_RAIN, L, VAR_SPECS[[M3S$var]], M3S$nk)
q_riv <- quantile(d$river_z[pin & used == 1], c(.25, .5, .75), na.rm = TRUE)
mk_riv <- function(ind) unclass(crossbasis(d$river_z, lag = L, group = d$city,
  argvar = list(fun = "ns", knots = q_riv, Boundary.knots = range(d$river_z, na.rm = TRUE)),
  arglag = list(fun = "ns", knots = logknots(L, M3S$nk))))[, , drop = FALSE] * ind
cb_riv <- crossbasis(d$river_z, lag = L, group = d$city,
  argvar = list(fun = "ns", knots = q_riv, Boundary.knots = range(d$river_z, na.rm = TRUE)), arglag = list(fun = "ns", knots = logknots(L, M3S$nk)))
cb_fl <- crossbasis(d$river_flood, lag = L, group = d$city, argvar = list(fun = "lin"), arglag = list(fun = "ns", knots = logknots(L, M3S$nk)))
rs_basis <- { ok <- !is.na(d$rs); nb <- ns(d$rs[ok & pin & used == 1], df = 3); B <- matrix(NA_real_, nrow(d), 3)
  B[ok, ] <- predict(nb, newx = pmin(pmax(d$rs[ok], min(d$rs[ok & pin & used == 1])), max(d$rs[ok & pin & used == 1]))); B }

add_cols <- function(dd, M, prefix) { nm <- paste0(prefix, seq_len(ncol(M))); dd[, (nm) := as.data.table(M[, seq_len(ncol(M)), drop = FALSE])]; nm }
dd <- copy(d)
cbn <- add_cols(dd, unclass(cb_rain), "cb")
r1 <- add_cols(dd, mk_riv(used), "rv")
r2 <- add_cols(dd, rs_basis * used, "rs")
r3 <- add_cols(dd, unclass(cb_fl)[, , drop = FALSE] * used, "fl")
r4 <- add_cols(dd, mk_riv(rep(1, nrow(dd))), "ra")
m <- dd[pin & !is.na(y) & complete.cases(dd[, c(cbn, r1, r2, r3, r4), with = FALSE])]
m[, `:=`(city = factor(city), dgrp = factor(dgrp))]
base_rhs <- c("city", paste0("city:(", paste(F3, collapse = "+"), ")"), paste0("city:(", paste(TR7, collapse = "+"), ")"), "flag_covid", cbn)
fitm <- function(extra) {
  f <- as.formula(paste("y ~", paste(c(base_rhs, extra), collapse = " + "), "+ offset(log_offset)"))
  st <- coef(suppressWarnings(glm(f, family = poisson, data = m)))
  fit <- glmmTMB(f, family = nbinom2, dispformula = ~ 0 + dgrp, data = m, control = CTRL, start = list(beta = unname(st)))
  stopifnot(fit$fit$convergence == 0); fit
}
log_step("Fitting 5 models on", nrow(m), "rows")
fits <- list(M0 = fitm(NULL), M1 = fitm(r1), M2 = fitm(r2), M3 = fitm(r3), M4 = fitm(r4))
ll <- sapply(fits, function(f) as.numeric(logLik(f))); k <- sapply(fits, function(f) attr(logLik(f), "df"))
lab <- c(M0 = "Rain only (Stage 3 main)", M1 = "+ river, like rain (river cities)", M2 = "+ river, simple (river cities)",
         M3 = "+ river-flood-week flag (river cities)", M4 = "+ river, like rain (all 12 cities)")
tab <- data.table(model = names(fits), label = lab[names(fits)], rows = nrow(m), params = k, aic = -2 * ll + 2 * k)
tab[, `:=`(delta_aic = aic - aic[1], lr_stat = 2 * (ll - ll[1]), extra_params = k - k[1])]
tab[model != "M0", p_value := pchisq(lr_stat, extra_params, lower.tail = FALSE)]
fwrite(tab, file.path(OUT, "river_explain_models.csv")); print(tab)

# ---- river lag-response (M1) ------------------------------------------------------------------------
b1 <- fixef(fits$M1)$cond; V1 <- vcov(fits$M1)$cond
zz <- d$river_z[pin & used == 1]; cen_r <- median(zz, na.rm = TRUE); p95_r <- unname(quantile(zz, .95, na.rm = TRUE))
cpr <- crosspred(cb_riv, coef = b1[r1], vcov = V1[r1, r1], model.link = "log", at = round(c(seq(-2, 3, 0.1), p95_r), 2), cen = cen_r, bylag = 1)
k95 <- as.character(round(p95_r, 2))
rlag <- data.table(lag = 0:L, rr = cpr$matRRfit[k95, ], lo = cpr$matRRlow[k95, ], hi = cpr$matRRhigh[k95, ])
fwrite(rlag, file.path(OUT, "river_explain_lag_response.csv"))
rcum <- data.table(river_z = as.numeric(rownames(cpr$matRRfit)), rr = cpr$allRRfit, lo = cpr$allRRlow, hi = cpr$allRRhigh)
fwrite(rcum, file.path(OUT, "river_explain_cumulative.csv"))
cat("river P95 =", round(p95_r, 2), "SD; median", round(cen_r, 2), "\n"); print(rlag[, lapply(.SD, round, 3)])

# ---- does the rain effect shrink once river flow is in? ------------------------------------------------
cen_rain <- median(m[[MAIN_RAIN]]); p95_rain <- unname(quantile(d[[MAIN_RAIN]][pin], .95, na.rm = TRUE))
rain_summ <- rbindlist(lapply(c("M0", "M1"), function(mm) { b <- fixef(fits[[mm]])$cond; V <- vcov(fits[[mm]])$cond
  cp <- crosspred(cb_rain, coef = b[cbn], vcov = V[cbn, cbn], model.link = "log", at = round(p95_rain, 1), cen = cen_rain, bylag = 1)
  data.table(model = mm, peak_week_rr = max(cp$matRRfit), peak_lag = which.max(cp$matRRfit) - 1, extra_cases = sum(cp$matRRfit - 1), cumulative_rr = cp$allRRfit) }))
fwrite(rain_summ, file.path(OUT, "river_explain_rain_effect.csv")); print(rain_summ)

# ---- Typhoon Washi weeks, Cagayan de Oro ------------------------------------------------------------------
m[, `:=`(mu0 = predict(fits$M0, type = "response"), mu1 = predict(fits$M1, type = "response"))]
wa <- m[city == "Cagayan de Oro" & start >= as.IDate("2011-11-27") & start <= as.IDate("2012-02-04"),
        .(year, mw, start, rain_mm = round(get(MAIN_RAIN)), river_z = round(river_z, 2), observed = y, expected_rain_only = round(mu0, 1), expected_with_river = round(mu1, 1))]
fwrite(wa, file.path(OUT, "river_explain_washi.csv")); print(wa)
cat("Washi outbreak weeks (MW51 2011 - MW3 2012) totals: observed", wa[start >= as.IDate("2011-12-18") & start <= as.IDate("2012-01-21"), sum(observed)],
    "rain only", wa[start >= as.IDate("2011-12-18") & start <= as.IDate("2012-01-21"), round(sum(expected_rain_only))],
    "with river", wa[start >= as.IDate("2011-12-18") & start <= as.IDate("2012-01-21"), round(sum(expected_with_river))], "\n")

# ---- figures ------------------------------------------------------------------------------------------------
BLUE <- "#2a78d6"; GREY <- "#8a8984"; INK <- "#0b0b0b"
p <- ggplot(rlag, aes(lag, rr)) + geom_hline(yintercept = 1, linetype = "dashed", colour = GREY) +
  geom_errorbar(aes(ymin = lo, ymax = hi), width = 0, colour = BLUE, linewidth = 0.8) + geom_point(colour = BLUE, size = 2.6) +
  scale_x_continuous(breaks = 0:L) +
  labs(x = "Weeks after a high-river week", y = "Relative risk vs a typical river week",
       subtitle = sprintf("Risk in each week after one week with river flow in the top 5%% for that river (%.1f SD above normal), on top of rain.\nModel with rain + river, river cities, 2008–2022", p95_r))
ggsave(file.path(FIG, "river_lag_response.png"), p, width = 9, height = 4, dpi = 150, bg = "white")
log_step("Done")
