# =============================================================================
# 07_flood.R  —  Stage 7: does flood hazard change the rain–leptospirosis relationship?
#
# Flood data: Project CCHAIN project_noah_hazards.csv (UP NOAH flood hazard maps): share of each
#   barangay's area in low / medium / high flood hazard for 5-, 25- and 100-year floods. One snapshot
#   (2015). Only the 100-year map covers all 12 cities: the 5- and 25-year maps are blank for Iloilo and
#   Mandaue and mostly blank for Tacloban, so the main measure uses the 100-year map.
# Main exposure: share of a city's residents living in medium- or high-hazard areas (100-year map),
#   population-weighted across barangays (WorldPop, mean of 2008-2020), assuming people are spread
#   evenly within each barangay.
#
# Analyses
#   1. Exposure by city and barangay.
#   2. Barangay check (Zamboanga, Muntinlupa: the cities with barangay-located cases): do barangays with
#      more flood-hazard area have higher case rates?
#   3. Effect modification in the Stage 3 model: the rain crossbasis of city c is multiplied by
#      (1 + g * E_c), E_c = city exposure minus the 12-city mean, in 10-percentage-point units. So flood
#      exposure scales the STRENGTH of the rain effect, not its timing (one extra parameter, g).
#      g by maximum likelihood (profile), 95% CI from the likelihood-ratio test; AIC vs Stage 3 main;
#      leave-one-city-out; alternative exposure measures.
#   4. Each city's own rain multiplier (rain effect from the Stage 3 model scaled freely per city),
#      plotted against flood exposure — a model-free view of the same question.
#
# Inputs : data/raw/project_noah_hazards.csv, data/raw/location.csv, data/raw/worldpop_population.csv,
#          data/raw/disease_lgu_disaggregated_totals.csv, data/processed/city_week.rds
# Outputs: output/stage7/*.csv, output/stage7/figs/*.png, output/stage7/flood_exposure_city.csv (used by 07b)
# =============================================================================

# Stage 3 helper functions and settings (prep, make_cb, predict_fit, ...) without running Stage 3
src3 <- readLines("R/03_dlnm.R"); eval(parse(text = src3[1:(grep("^d <- prep\\(\\)", src3) - 1)]))
suppressPackageStartupMessages(library(parallel))
OUT <- file.path(PATHS$out, "stage7"); FIG <- file.path(OUT, "figs")
dir.create(FIG, recursive = TRUE, showWarnings = FALSE)
CORES <- max(1L, min(2L, detectCores()))
M3 <- readRDS(file.path(PATHS$out, "stage3", "main_model.rds"))
MAIN <- M3$spec

# ---- 1. Flood exposure ---------------------------------------------------------
log_step("1 exposure")
loc <- fread(file.path(PATHS$raw, "location.csv"))[, .(adm4_pcode, adm3_pcode, adm3_en, adm4_en, brgy_area = brgy_total_area)]
loc[, city := CITY_SHORT[adm3_en]]
hz <- fread(file.path(PATHS$raw, "project_noah_hazards.csv"))
wp <- fread(file.path(PATHS$raw2, "worldpop_population.csv"), select = c("adm4_pcode", "date", "pop_count_total"))
wp <- wp[year(as.IDate(date)) %between% c(2008, 2020), .(pop = mean(pop_count_total, na.rm = TRUE)), by = adm4_pcode]
b <- merge(merge(loc, hz, by = "adm4_pcode", all.x = TRUE), wp, by = "adm4_pcode", all.x = TRUE)
b[!is.finite(pop), pop := NA_real_]
stopifnot(nrow(b) == 879, !anyNA(b$pct_area_flood_hazard_100yr_high))
b[, `:=`(mh100 = pct_area_flood_hazard_100yr_med + pct_area_flood_hazard_100yr_high,
         h100  = pct_area_flood_hazard_100yr_high,
         any100 = pct_area_flood_hazard_100yr_low + pct_area_flood_hazard_100yr_med + pct_area_flood_hazard_100yr_high,
         mh25  = pct_area_flood_hazard_25yr_med + pct_area_flood_hazard_25yr_high,
         mh5   = pct_area_flood_hazard_5yr_med + pct_area_flood_hazard_5yr_high)]
NO_25 <- c("Iloilo", "Mandaue", "Tacloban")     # 5- and 25-year maps missing or mostly missing
cov <- b[, .(barangays = .N, with_100yr_map = sum(any100 > 0), with_25yr_map = sum(pct_area_flood_hazard_25yr_low +
          pct_area_flood_hazard_25yr_med + pct_area_flood_hazard_25yr_high > 0), pop_missing = sum(is.na(pop))), by = city]
fwrite(cov[order(city)], file.path(OUT, "hazard_map_coverage.csv"))
pw <- function(x, w) { ok <- !is.na(x) & !is.na(w); sum(x[ok] * w[ok]) / sum(w[ok]) }
ex <- b[, .(pop = sum(pop, na.rm = TRUE), mh100 = pw(mh100, pop), h100 = pw(h100, pop), any100 = pw(any100, pop),
            mh25 = pw(mh25, pop), mh5 = pw(mh5, pop), area_mh100 = pw(mh100, brgy_area)), by = city]
ex[city %in% NO_25, `:=`(mh25 = NA_real_, mh5 = NA_real_)]
setorder(ex, -mh100)
fwrite(ex, file.path(OUT, "flood_exposure_city.csv"))
fwrite(b[, .(city, adm4_pcode, adm4_en, pop, brgy_area, mh100, h100, any100, mh25, mh5)], file.path(OUT, "flood_exposure_barangay.csv"))
print(ex)

# ---- 2. Barangay check ------------------------------------------------------------
log_step("2 barangay check")
lg <- fread(file.path(PATHS$raw, "disease_lgu_disaggregated_totals.csv"))[disease_common_name == "LEPTOSPIROSIS" & adm4_pcode != ""]
lg <- merge(lg, loc[, .(adm4_pcode, city)], by = "adm4_pcode")
pid <- fread(file.path(PATHS$raw, "disease_pidsr_totals.csv"))
pid <- merge(pid[grepl("LEPTO", toupper(disease_common_name))], unique(loc[, .(adm3_pcode, city)]), by = "adm3_pcode")
brgy_cov <- merge(lg[, .(brgy_cases = sum(case_total, na.rm = TRUE)), by = .(city, year = year(date))],
                  pid[, .(city_cases = sum(case_total, na.rm = TRUE)), by = .(city, year = year(date))], by = c("city", "year"), all.x = TRUE)
fwrite(brgy_cov[order(city, year)], file.path(OUT, "barangay_case_coverage.csv"))
brgy_fit <- rbindlist(lapply(c("Zamboanga", "Muntinlupa"), function(cc) {
  yrs <- lg[city == cc, uniqueN(year(date))]
  x <- merge(b[city == cc & !is.na(pop) & pop > 0], lg[city == cc, .(cases = sum(case_total, na.rm = TRUE)), by = adm4_pcode], by = "adm4_pcode", all.x = TRUE)
  x[is.na(cases), cases := 0]
  x[, `:=`(E10 = mh100 / 10, ldens = log(pop / brgy_area))]
  m1 <- tryCatch(glm.nb(cases ~ E10 + offset(log(pop * yrs)), data = x), error = function(e) glm(cases ~ E10 + offset(log(pop * yrs)), family = quasipoisson, data = x))
  m2 <- tryCatch(glm.nb(cases ~ E10 + ldens + offset(log(pop * yrs)), data = x), error = function(e) NULL)
  ci <- function(m) { if (is.null(m)) return(c(NA, NA, NA)); s <- summary(m)$coefficients["E10", ]; exp(s[1] + c(0, -1.96, 1.96) * s[2]) }
  r1 <- ci(m1); r2 <- ci(m2)
  x[, grp := cut(mh100, c(-Inf, 10, 30, 60, Inf), labels = c("under 10%", "10-30%", "30-60%", "over 60%"))]
  fwrite(x[, .(barangays = .N, pop = round(sum(pop)), cases = sum(cases), rate_per_100k_yr = 1e5 * sum(cases) / sum(pop) / yrs), by = grp][order(grp)],
         file.path(OUT, sprintf("barangay_rates_%s.csv", cc)))
  data.table(city = cc, barangays = nrow(x), barangays_with_cases = sum(x$cases > 0), cases = sum(x$cases), years = yrs,
             rr_per10 = r1[1], lo = r1[2], hi = r1[3], rr_per10_adj_density = r2[1], lo_adj = r2[2], hi_adj = r2[3])
}))
fwrite(brgy_fit, file.path(OUT, "barangay_check.csv")); print(brgy_fit)

# ---- 3. Effect modification in the Stage 3 model -------------------------------------
log_step("3 effect modification")
d <- prep()
setup_fm <- function(d, rain = MAIN_RAIN) {
  cb <- make_cb(d, rain, MAIN$L, VAR_SPECS[[MAIN$var]], MAIN$nk)
  cbn <- paste0("cb", seq_len(ncol(cb)))
  dd <- copy(d); dd[, (cbn) := as.data.table(unclass(cb)[, seq_len(ncol(cb)), drop = FALSE])]
  m <- dd[in_pidsr_period == TRUE & !is.na(y) & complete.cases(dd[, cbn, with = FALSE])]
  m[, `:=`(city = factor(city), dgrp = factor(dgrp))]
  f <- as.formula(paste("y ~", paste(c("city", paste0("city:(", paste(F3, collapse = "+"), ")"), paste0("city:(", paste(TR7, collapse = "+"), ")"),
                                         "flag_covid", cbn), collapse = " + "), "+ offset(log_offset)"))
  list(m = m, cb = cb, cbn = cbn, f = f, B0 = as.matrix(m[, cbn, with = FALSE]))
}
fit_scaled <- function(S, E, g, keep = FALSE) {
  m <- copy(S$m); s <- 1 + g * unname(E[as.character(m$city)])
  if (any(s <= 0)) return(if (keep) NULL else -Inf)
  m[, (S$cbn) := as.data.table(S$B0 * s)]
  st <- coef(suppressWarnings(glm(S$f, family = poisson, data = m)))
  fit <- tryCatch(suppressWarnings(glmmTMB(S$f, family = nbinom2, dispformula = ~ 0 + dgrp, data = m, control = CTRL,
                                           start = list(beta = unname(st)))), error = function(e) NULL)
  if (keep) return(fit)
  if (is.null(fit) || fit$fit$convergence != 0) return(-Inf)
  as.numeric(logLik(fit))
}
centre <- function(v, cities) { e <- setNames(v, ex$city)[cities]; (e - mean(e)) / 10 }
g_range <- function(E) c(-1 / max(E), -1 / min(E)) * 0.98        # keeps every city's scale factor above 0
estimate_g <- function(S, E, tol = 0.01) {
  r <- g_range(E); o <- optimize(function(g) fit_scaled(S, E, g), r, maximum = TRUE, tol = tol)
  list(g = o$maximum, ll = o$objective, ll0 = fit_scaled(S, E, 0), range = r)
}
profile_ci <- function(S, E, est, grid) {
  ll <- unlist(mclapply(grid, function(g) fit_scaled(S, E, g), mc.cores = CORES))
  pr <- data.table(g = c(grid, est$g), ll = c(ll, est$ll))[is.finite(ll)][order(g)]
  pr[, dev := 2 * (est$ll - ll)]
  root <- function(side) { q <- if (side == "lo") pr[g <= est$g] else pr[g >= est$g]; if (!any(q$dev >= 3.84)) return(NA_real_)
    q <- q[order(if (side == "lo") -g else g)]; i <- which(q$dev >= 3.84)[1]; approx(q$dev[(i - 1):i], q$g[(i - 1):i], 3.84)$y }
  list(profile = pr, lo = root("lo"), hi = root("hi"))
}

S <- setup_fm(d)
cities <- levels(S$m$city)
E_main <- centre(ex$mh100, cities)
REFIT <- Sys.getenv("STAGE7_REFIT") == "1"          # otherwise the slow steps (3, 3b, 3c) are read back from their CSVs
mean_mh100 <- mean(setNames(ex$mh100, ex$city)[cities])
if (REFIT || !file.exists(file.path(OUT, "effect_modification.csv"))) {
  est <- estimate_g(S, E_main)
  log_step(sprintf("g = %.3f, LL %.2f vs %.2f (g=0)", est$g, est$ll, est$ll0))
  grid <- sort(unique(round(c(seq(est$range[1] + 0.02, est$range[2] - 0.02, length.out = 15), est$g + c(-0.15, -0.08, 0.08, 0.15)), 3)))
  grid <- grid[grid > est$range[1] & grid < est$range[2]]
  pci <- profile_ci(S, E_main, est, grid)
  fwrite(pci$profile, file.path(OUT, "profile_likelihood.csv"))
  main_res <- data.table(measure = "mh100", g = est$g, g_lo = pci$lo, g_hi = pci$hi, lr_stat = 2 * (est$ll - est$ll0),
                         p_value = pchisq(2 * (est$ll - est$ll0), 1, lower.tail = FALSE),
                         delta_aic = -2 * (est$ll - est$ll0) + 2, mean_exposure = mean_mh100,
                         g_range_lo = est$range[1], g_range_hi = est$range[2])
  fwrite(main_res, file.path(OUT, "effect_modification.csv"))
} else {
  main_res <- fread(file.path(OUT, "effect_modification.csv"))
  est <- list(g = main_res$g, range = c(main_res$g_range_lo, main_res$g_range_hi))
  pci <- list(profile = fread(file.path(OUT, "profile_likelihood.csv")), lo = main_res$g_lo, hi = main_res$g_hi)
}
print(main_res)

# rain–risk curves at low / average / high exposure, from the fitted model at g-hat
fit_g <- fit_scaled(S, E_main, est$g, keep = TRUE)
b_all <- fixef(fit_g)$cond; V_all <- vcov(fit_g)$cond
cbc <- b_all[S$cbn]; cbV <- V_all[S$cbn, S$cbn]
cen <- median(S$m[[MAIN_RAIN]]); p95 <- unname(quantile(d[[MAIN_RAIN]][d$in_pidsr_period], .95, na.rm = TRUE))
at <- sort(unique(round(c(seq(0, ceiling(quantile(d[[MAIN_RAIN]][d$in_pidsr_period], .995, na.rm = TRUE)), by = 2), cen, p95), 1)))
ex_levels <- c(Low = min(ex$mh100), Average = mean_mh100, High = max(ex$mh100))
curves <- rbindlist(lapply(names(ex_levels), function(nm) {
  s <- 1 + est$g * (ex_levels[[nm]] - mean_mh100) / 10
  cp <- crosspred(S$cb, coef = cbc * s, vcov = cbV * s^2, model.link = "log", at = at, cen = cen, bylag = 1)
  k <- as.character(round(p95, 1))
  list(level = nm, exposure = ex_levels[[nm]], scale = s, rain = at, rr = cp$allRRfit, lo = cp$allRRlow, hi = cp$allRRhigh,
       peak_lag_rr_p95 = max(cp$matRRfit[k, ]), excess_p95 = sum(cp$matRRfit[k, ] - 1))
}))
fwrite(curves, file.path(OUT, "curves_by_exposure.csv"))
city_scale <- data.table(city = cities, exposure = setNames(ex$mh100, ex$city)[cities], scale = 1 + est$g * E_main)
fwrite(city_scale[order(-exposure)], file.path(OUT, "city_scale_factors.csv"))

# ---- 3b. Leave one city out --------------------------------------------------------------
log_step("3b leave-one-city-out")
if (!REFIT && file.exists(file.path(OUT, "leave_one_city_out.csv"))) loco <- fread(file.path(OUT, "leave_one_city_out.csv")) else
loco <- rbindlist(mclapply(cities, function(cc) {
  dsub <- d[city != cc]; Sx <- setup_fm(dsub); cx <- levels(Sx$m$city); Ex <- centre(ex$mh100, cx)
  e <- estimate_g(Sx, Ex, tol = 0.02)
  data.table(left_out = cc, g = e$g, lr_stat = 2 * (e$ll - e$ll0), mean_exposure = mean(setNames(ex$mh100, ex$city)[cx]))
}, mc.cores = CORES, mc.preschedule = FALSE))
# express each as "rain effect multiplier per 10 points more exposure, at the average city" = g (same units)
fwrite(loco, file.path(OUT, "leave_one_city_out.csv")); print(loco)

# ---- 3c. Alternative exposure measures ------------------------------------------------------
log_step("3c alternative measures")
if (!REFIT && file.exists(file.path(OUT, "alternative_measures.csv"))) alt <- fread(file.path(OUT, "alternative_measures.csv")) else
alt <- rbindlist(mclapply(list(list("h100", NULL), list("any100", NULL), list("area_mh100", NULL), list("mh25", NO_25), list("mh5", NO_25)), function(a) {
  dsub <- if (is.null(a[[2]])) d else d[!city %in% a[[2]]]
  Sx <- if (is.null(a[[2]])) S else setup_fm(dsub); cx <- levels(Sx$m$city)
  v <- setNames(ex[[a[[1]]]], ex$city)[cx]; Ex <- (v - mean(v)) / 10
  e <- estimate_g(Sx, Ex, tol = 0.02)
  data.table(measure = a[[1]], cities = length(cx), g = e$g, lr_stat = 2 * (e$ll - e$ll0),
             p_value = pchisq(2 * (e$ll - e$ll0), 1, lower.tail = FALSE), exposure_range = paste(round(range(v), 1), collapse = "-"))
}, mc.cores = CORES, mc.preschedule = FALSE))
fwrite(alt, file.path(OUT, "alternative_measures.csv")); print(alt)

# ---- 4. Each city's own rain multiplier ---------------------------------------------------
log_step("4 city multipliers")
fit0 <- fit_scaled(S, E_main, 0, keep = TRUE)
m0 <- copy(S$m); X0 <- S$B0
m0[, eta := predict(fit0, type = "link")]
m0[, rterm := as.vector(X0 %*% fixef(fit0)$cond[S$cbn])]                       # rain part of the linear predictor
th0 <- exp(fixef(fit0)$disp); names(th0) <- sub("^dgrp", "", names(th0))
mult <- rbindlist(lapply(cities, function(cc) {
  x <- m0[city == cc]; x[, base := eta - rterm]
  g1 <- tryCatch(glm(y ~ 1 + rterm + offset(base), family = negative.binomial(th0[[as.character(x$dgrp[1])]]), data = x,
                     control = glm.control(maxit = 200)), error = function(e) NULL)
  if (is.null(g1) || !g1$converged) return(data.table(city = cc, multiplier = NA_real_, lo = NA_real_, hi = NA_real_, se = NA_real_, converged = FALSE))
  s <- summary(g1)$coefficients["rterm", ]
  data.table(city = cc, multiplier = s[1], lo = s[1] - 1.96 * s[2], hi = s[1] + 1.96 * s[2], se = s[2], converged = TRUE)
}))
mult <- merge(mult, ex[, .(city, exposure = mh100)], by = "city")
mc <- mult[converged == TRUE]
wfit <- lm(multiplier ~ exposure, data = mc, weights = 1 / se^2)
mult_trend <- data.table(cities = nrow(mc), slope_per10 = 10 * coef(wfit)[2], lo = 10 * confint(wfit)[2, 1], hi = 10 * confint(wfit)[2, 2],
                         r = cor(mc$multiplier, mc$exposure), spearman = cor(mc$multiplier, mc$exposure, method = "spearman"))
fwrite(mult[order(-exposure)], file.path(OUT, "city_rain_multipliers.csv")); fwrite(mult_trend, file.path(OUT, "city_multiplier_trend.csv"))
print(mult[order(-exposure)]); print(mult_trend)

# ---- Figures -------------------------------------------------------------------------------
log_step("Figures")
exl <- melt(ex[, .(city, `High hazard` = h100, `Medium hazard` = mh100 - h100, `Low hazard` = any100 - mh100)], id.vars = "city")
exl[, city := factor(city, levels = rev(ex$city))]
exl[, variable := factor(variable, levels = c("Low hazard", "Medium hazard", "High hazard"))]
p <- ggplot(exl, aes(value, city, fill = variable)) + geom_col(width = 0.7) +
  scale_fill_manual(values = c(`Low hazard` = "#c9dcf3", `Medium hazard` = "#6fa3e3", `High hazard` = "#1d4f91"), name = NULL) +
  labs(x = "Share of residents living in flood-hazard areas (100-year flood, %)", y = NULL) + guides(fill = guide_legend(reverse = FALSE))
save_fig(p, "exposure_by_city.png", h = 4.2)

pr <- pci$profile
p <- ggplot(pr, aes(g, dev)) + geom_hline(yintercept = 3.84, linetype = "dashed", colour = GREY) + geom_line(colour = BLUE, linewidth = 0.9) +
  geom_point(colour = BLUE, size = 1.6) + geom_vline(xintercept = 0, colour = GREY) +
  annotate("text", x = min(pr$g), y = 3.84, label = "95% limit", hjust = 0, vjust = -0.5, size = 3, colour = GREY) +
  labs(x = "g: change in rain-effect strength per 10 points more flood exposure (0 = no change)", y = "Worse fit than the best g (deviance)")
save_fig(p, "profile_likelihood.png", h = 3.8)

cv <- curves[rain <= quantile(d[[MAIN_RAIN]][d$in_pidsr_period], .99, na.rm = TRUE)]
cv[, lab := factor(sprintf("%s exposure (%.0f%%)", level, exposure), levels = unique(sprintf("%s exposure (%.0f%%)", level, exposure)))]
p <- ggplot(cv, aes(rain, rr, colour = lab, fill = lab)) + geom_hline(yintercept = 1, colour = GREY) +
  geom_ribbon(aes(ymin = lo, ymax = hi), alpha = 0.12, colour = NA) + geom_line(linewidth = 0.9) +
  geom_vline(xintercept = p95, linetype = "dashed", colour = GREY) +
  scale_colour_manual(values = c(ORANGE, BLUE, INK), name = NULL) + scale_fill_manual(values = c(ORANGE, BLUE, INK), name = NULL) +
  scale_y_log10() + labs(x = "Weekly rainfall (mm, IMERG Final)", y = "Cumulative relative risk over 10 weeks (log scale)",
                         subtitle = "Dashed line: wettest 5% of weeks. Rain-effect strength scaled by flood exposure (best-fitting g)")
save_fig(p, "curves_by_exposure.png", h = 4.2)

p <- ggplot(mc, aes(exposure, multiplier)) + geom_hline(yintercept = 1, colour = GREY, linetype = "dashed") +
  geom_abline(intercept = coef(wfit)[1], slope = coef(wfit)[2], colour = ORANGE, linewidth = 0.7) +
  geom_errorbar(aes(ymin = lo, ymax = hi), width = 0, colour = BLUE, alpha = 0.6) + geom_point(colour = BLUE, size = 2.4) +
  geom_text(aes(label = city, vjust = fifelse(city == "Navotas", 1.6, -0.4)), size = 2.8, hjust = -0.12) + scale_x_continuous(expand = expansion(mult = c(0.05, 0.15))) +
  labs(x = "Residents in medium/high flood-hazard areas (100-year map, %)", y = "City's rain-effect multiplier (1 = pooled average)",
       subtitle = "Each city's rain effect relative to the pooled Stage 3 curve, with 95% CI. Orange: weighted trend")
save_fig(p, "city_multipliers.png", h = 4.8)

for (cc in c("Zamboanga", "Muntinlupa")) {
  x <- fread(file.path(OUT, sprintf("barangay_rates_%s.csv", cc)))
  x[, grp := factor(grp, levels = c("under 10%", "10-30%", "30-60%", "over 60%"))]
  p <- ggplot(x, aes(grp, rate_per_100k_yr)) + geom_col(fill = BLUE, width = 0.6) +
    geom_text(aes(label = sprintf("%d barangays\n%d cases", barangays, cases)), vjust = -0.3, size = 2.8) +
    scale_y_continuous(expand = expansion(mult = c(0, 0.25))) +
    labs(x = "Barangay area in medium/high flood hazard (100-year map)", y = "Cases per 100,000 per year", subtitle = cc)
  save_fig(p, sprintf("barangay_%s.png", cc), w = 6, h = 3.8)
}
log_step("Done")
