# =============================================================================
# 04_thresholds.R  —  Stage 4: DOH epidemic thresholds per city
#
# Rule (project document): average of the past 3 or 5 years + 2 standard deviations, per city.
# Implementation:
#   * weekly, by DOH morbidity week; counts per 7 days (MW1/MW52 can be 4-12 days long)
#   * baseline for week t = the same week +/- 2 weeks in each of the previous N years
#     (5 x N values); each year has exactly 52 MWs, so "k years ago" = t - 52k in the city's
#     consecutive week index, which also handles the year boundary
#   * threshold = max(mean + 2 SD, 1 case); a week is above threshold if cases > threshold
#   * N = 5 years (main; thresholds from 2013) and N = 3 years (from 2011)
#   * STANDARD: all past weeks in the baseline (flagged non-reporting weeks excluded)
#   * OUTBREAK-EXCLUDED: past weeks that were themselves above the outbreak-excluded threshold
#     in force at the time are dropped from the baseline. For weeks before a full N-year history
#     exists, "in force" means the threshold built from the longest history then available
#     (minimum 3 years), so 2011-2012 outbreaks are flagged and excluded; 2008-2010 weeks have no
#     threshold of their own and stay in the baseline.
#   * outbreak = any week above threshold; consecutive weeks above threshold form one episode
#
# Inputs  : data/processed/city_week.rds
#   * low-case cities (threshold at the 1-case minimum in >= 70% of weeks) get a "confirmed unusual
#     week" signal; cases_needed_* = smallest weekly count above each threshold
# Outputs : output/stage4/*.csv, output/stage4/figs/*.png
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages(library(ggplot2))
OUT <- file.path(PATHS$out, "stage4"); FIG <- file.path(OUT, "figs")
dir.create(FIG, recursive = TRUE, showWarnings = FALSE)

WIN <- 2L; FLOOR <- 1; MIN_VALUES <- 10L; MIN_YEARS <- 3L
BLUE <- "#2a78d6"; ORANGE <- "#eb6834"; GREY <- "#8a8984"; INK <- "#0b0b0b"
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top",
          strip.text = element_text(face = "bold", hjust = 0), plot.title.position = "plot"))
save_fig <- function(p, name, w = 9, h = 4.2) ggsave(file.path(FIG, name), p, width = w, height = h, dpi = 150, bg = "white")

d <- readRDS(file.path(PATHS$processed, "city_week.rds"))[in_pidsr_period == TRUE][order(city, start)]
d[, t := seq_len(.N), by = city]                         # 52 weeks per year -> t - 52k = same MW k years ago
stopifnot(d[, .N, by = .(city, year)][, all(N == 52)])
d[, c7 := fifelse(include, cases / days * 7, NA_real_)]  # flagged non-reporting weeks excluded from baselines

offsets <- function(nyr) as.vector(outer(-WIN:WIN, 52L * seq_len(nyr), function(j, k) k - j))   # t - offset

# Threshold for every week of one city; `keep` marks which past weeks may enter the baseline.
thr_from <- function(c7, keep, nyr) {
  n <- length(c7); out <- rep(NA_real_, n); off <- offsets(nyr)
  for (i in seq_len(n)) {
    if (i - 52L * nyr - WIN < 1L) next
    v <- c7[i - off]; v <- v[keep[i - off] & !is.na(v)]
    if (length(v) >= MIN_VALUES) out[i] <- max(mean(v) + 2 * sd(v), FLOOR)
  }
  out
}
# Outbreak-excluded: recursive, chronological. A week's own threshold uses the longest history
# available (MIN_YEARS..nyr years); it is flagged if above it, and flagged weeks are excluded later.
thr_excl <- function(c7, nyr) {
  n <- length(c7); flag <- rep(FALSE, n); thr_n <- rep(NA_real_, n); thr_any <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    yrs <- min(nyr, (i - WIN - 1L) %/% 52L)
    if (yrs < MIN_YEARS) next
    off <- offsets(yrs); v <- c7[i - off]; v <- v[!flag[i - off] & !is.na(v)]
    if (length(v) < MIN_VALUES) next
    thr_any[i] <- max(mean(v) + 2 * sd(v), FLOOR)
    if (yrs == nyr) thr_n[i] <- thr_any[i]
    flag[i] <- !is.na(c7[i]) && c7[i] > thr_any[i]
  }
  list(thr = thr_n, flag_used = flag)
}

log_step("Computing thresholds")
for (ny in c(5L, 3L)) {
  d[, (paste0("thr_std", ny)) := thr_from(c7, rep(TRUE, .N), ny), by = city]
  d[, c(paste0("thr_exc", ny), paste0("excluded_from_baseline", ny)) := thr_excl(c7, ny), by = city]
}
for (v in c("std5", "exc5", "std3", "exc3")) d[, (paste0("above_", v)) := !is.na(c7) & !is.na(get(paste0("thr_", v))) & c7 > get(paste0("thr_", v))]

wk <- d[, .(city, year, mw, start, end, days, cases, cases_per7 = round(c7, 2), include,
            thr_std5 = round(thr_std5, 2), thr_exc5 = round(thr_exc5, 2), thr_std3 = round(thr_std3, 2), thr_exc3 = round(thr_exc3, 2),
            above_std5, above_exc5, above_std3, above_exc3)]
fwrite(wk, file.path(OUT, "thresholds_weekly.csv"))

# ---- Outbreak episodes ---------------------------------------------------------
episodes <- rbindlist(lapply(c("std5", "exc5", "std3", "exc3"), function(v) {
  a <- d[, .(city, t, start, end, cases, c7, thr = get(paste0("thr_", v)), above = get(paste0("above_", v)))]
  a[, run := rleid(above), by = city]
  a[above == TRUE, .(version = v, start = min(start), end = max(end), weeks = .N, total_cases = sum(cases),
                     peak_cases = max(cases), peak_over_threshold = round(max(c7 / thr), 1)), by = .(city, run)][, run := NULL]
}))
episodes[, `:=`(baseline = fifelse(grepl("5", version), "5-year", "3-year"),
                type = fifelse(grepl("std", version), "Standard", "Outbreak-excluded"))]
fwrite(episodes[order(version, city, start)], file.path(OUT, "outbreak_episodes.csv"))

# ---- Summaries --------------------------------------------------------------------
summ <- rbindlist(lapply(c("std5", "exc5", "std3", "exc3"), function(v) {
  first_year <- if (grepl("5", v)) 2013L else 2011L
  d[year >= first_year, .(version = v, weeks_assessed = sum(!is.na(get(paste0("thr_", v))) & !is.na(c7)),
                          weeks_above = sum(get(paste0("above_", v))),
                          median_threshold = round(median(get(paste0("thr_", v)), na.rm = TRUE), 2),
                          share_at_floor = round(100 * mean(get(paste0("thr_", v)) <= FLOOR + 1e-9, na.rm = TRUE))), by = city]
}))
summ <- merge(summ, episodes[, .(episodes = .N, episode_weeks_max = max(weeks)), by = .(city, version)], by = c("city", "version"), all.x = TRUE)
summ[is.na(episodes), `:=`(episodes = 0L, episode_weeks_max = 0L)]
summ[, pct_weeks_above := round(100 * weeks_above / weeks_assessed, 1)]
city_order <- d[include == TRUE, .(n = sum(cases)), by = city][order(-n), city]
fwrite(summ[order(version, match(city, city_order))], file.path(OUT, "summary_by_city.csv"))

# ---- Low-case cities and the "confirmed unusual week" signal -------------------------
# A city is "low-case" when its 5-year outbreak-excluded threshold sat at the 1-case minimum in
# >= 70% of weeks (2013-2022): there the threshold mostly means "2 or more cases is unusual", and it
# is shown as a "confirmed unusual week" signal rather than as an early warning.
LOWCASE_SHARE <- 70
city_type <- summ[version == "exc5", .(city, share_at_floor_exc5 = share_at_floor,
                                       city_type = fifelse(share_at_floor >= LOWCASE_SHARE, "low-case", "standard"))]
fwrite(city_type[order(match(city, city_order))], file.path(OUT, "city_type.csv"))
cases_needed <- function(thr) fifelse(is.na(thr), NA_integer_, as.integer(floor(thr) + 1L))   # smallest weekly count above thr
wk <- merge(wk, city_type[, .(city, city_type)], by = "city")
for (v in c("std5", "exc5", "std3", "exc3")) wk[, (paste0("cases_needed_", v)) := cases_needed(get(paste0("thr_", v)))]
wk[, signal_label := fifelse(city_type == "low-case", "Confirmed unusual week", "Above epidemic threshold")]
setorder(wk, city, start)
fwrite(wk, file.path(OUT, "thresholds_weekly.csv"))
by_year <- rbindlist(lapply(c("std5", "exc5"), function(v)
  d[year >= 2013, .(version = v, weeks_above = sum(get(paste0("above_", v))), mean_threshold = round(mean(get(paste0("thr_", v)), na.rm = TRUE), 2)), by = .(city, year)]))
fwrite(by_year, file.path(OUT, "by_city_year_5yr.csv"))

# ---- Case-study events -------------------------------------------------------------
EVENTS <- data.table(
  event = c("Cagayan de Oro after Typhoon Washi", "Navotas July 2018", "Iloilo 2011-2012 outbreak"),
  city = c("Cagayan de Oro", "Navotas", "Iloilo"),
  from = as.IDate(c("2011-12-11", "2018-06-17", "2011-01-01")), to = as.IDate(c("2012-02-04", "2018-09-01", "2012-12-31")))
cs <- rbindlist(lapply(seq_len(nrow(EVENTS)), function(i) {
  e <- EVENTS[i]; x <- d[city == e$city & start >= e$from & start <= e$to]
  rbindlist(lapply(c("std5", "exc5", "std3", "exc3"), function(v) {
    th <- x[[paste0("thr_", v)]]; ab <- x[[paste0("above_", v)]]
    data.table(event = e$event, city = e$city, version = v, weeks_in_window = nrow(x), cases = sum(x$cases),
               threshold_available = any(!is.na(th)),
               first_week_above = if (any(ab)) as.character(x$start[which(ab)[1]]) else NA_character_,
               first_above_mw = if (any(ab)) sprintf("%d MW%d", x$year[which(ab)[1]], x$mw[which(ab)[1]]) else NA_character_,
               weeks_above = sum(ab), cases_in_weeks_above = sum(x$cases[ab]),
               median_threshold = round(median(th, na.rm = TRUE), 1))
  }))
}))
fwrite(cs, file.path(OUT, "case_study_events.csv"))

# ---- Thresholds for 2023 (for the app): baseline 2018-2022 (5-yr) and 2020-2022 (3-yr) ---------
# The 2023 baseline includes the COVID years 2020-22, when reporting was low.
fut <- rbindlist(lapply(unique(d$city), function(cc) {
  x <- d[city == cc]; n <- nrow(x)
  rbindlist(lapply(1:52, function(m) {
    i <- n + m                                     # position of 2023 MW m
    res <- list(city = cc, year = 2023L, mw = m)
    for (ny in c(5L, 3L)) {
      off <- offsets(ny); idx <- i - off; idx <- idx[idx >= 1 & idx <= n]
      v <- x$c7[idx]; ve <- v[!x[[paste0("excluded_from_baseline", ny)]][idx]]
      v <- v[!is.na(v)]; ve <- ve[!is.na(ve)]
      res[[paste0("thr_std", ny)]] <- if (length(v) >= MIN_VALUES) round(max(mean(v) + 2 * sd(v), FLOOR), 2) else NA_real_
      res[[paste0("thr_exc", ny)]] <- if (length(ve) >= MIN_VALUES) round(max(mean(ve) + 2 * sd(ve), FLOOR), 2) else NA_real_
    }
    as.data.table(res)
  }))
}))
# app column: 5-year outbreak-excluded threshold, falling back to the 5-year standard one where the
# excluded baseline has too few usable weeks (< MIN_VALUES)
fut[, `:=`(thr_app = fifelse(is.na(thr_exc5), thr_std5, thr_exc5), thr_app_source = fifelse(is.na(thr_exc5), "standard 5-year (fallback)", "outbreak-excluded 5-year"))]
fut <- merge(fut, city_type[, .(city, city_type)], by = "city")
for (v in c("std5", "exc5", "std3", "exc3", "app")) fut[, (paste0("cases_needed_", v)) := cases_needed(get(paste0("thr_", v)))]
fut[, signal_label := fifelse(city_type == "low-case", "Confirmed unusual week", "Above epidemic threshold")]
fut[, signal_text := fifelse(city_type == "low-case",
  sprintf("%d or more cases in a week is unusual here (confirmed unusual week)", cases_needed_app),
  sprintf("Epidemic threshold: more than %.1f cases in a week (%d or more)", thr_app, cases_needed_app))]
setorder(fut, city, mw)
fwrite(fut, file.path(OUT, "thresholds_2023_for_app.csv"))

# ---- Figures --------------------------------------------------------------------------
log_step("Figures")
for (cc in city_order) {
  x <- d[city == cc & year >= 2013]
  lines <- rbind(x[, .(start, thr = thr_std5, version = "Standard (5-year)")], x[, .(start, thr = thr_exc5, version = "Outbreak-excluded (5-year)")])
  lines[, version := factor(version, levels = c("Standard (5-year)", "Outbreak-excluded (5-year)"))]
  p <- ggplot(x, aes(start)) +
    geom_col(aes(y = c7, fill = above_exc5), width = 7, show.legend = FALSE) +
    scale_fill_manual(values = c(`FALSE` = "#c9c8c2", `TRUE` = ORANGE)) +
    geom_step(data = lines, aes(y = thr, colour = version), linewidth = 0.6, direction = "mid") +
    scale_colour_manual(values = c(INK, BLUE), name = NULL) +
    scale_x_date(date_breaks = "1 year", date_labels = "'%y", expand = c(0.005, 0)) +
    labs(x = NULL, y = "Cases per 7 days", title = cc,
         subtitle = "Bars: weekly cases (orange = above the outbreak-excluded threshold). Lines: epidemic thresholds.")
  save_fig(p, sprintf("thr_%s.png", gsub(" ", "_", cc)), h = 3.8)
}
# case-study zooms with both baselines
for (i in seq_len(nrow(EVENTS))) {
  e <- EVENTS[i]; x <- d[city == e$city & start >= e$from - 70 & start <= e$to + 70]
  lines <- rbind(x[, .(start, thr = thr_std5, version = "Standard, 5-year")], x[, .(start, thr = thr_exc5, version = "Outbreak-excluded, 5-year")],
                 x[, .(start, thr = thr_std3, version = "Standard, 3-year")], x[, .(start, thr = thr_exc3, version = "Outbreak-excluded, 3-year")])[!is.na(thr)]
  lines[, version := factor(version, levels = c("Standard, 5-year", "Outbreak-excluded, 5-year", "Standard, 3-year", "Outbreak-excluded, 3-year"))]
  p <- ggplot(x, aes(start)) + geom_col(aes(y = c7), fill = "#c9c8c2", width = 7) +
    annotate("rect", xmin = e$from, xmax = e$to, ymin = -Inf, ymax = Inf, alpha = 0.06, fill = ORANGE) +
    geom_step(data = lines, aes(y = thr, colour = version, linetype = version), linewidth = 0.6, direction = "mid") +
    scale_colour_manual(values = c(INK, BLUE, INK, BLUE), name = NULL, drop = FALSE) +
    scale_linetype_manual(values = c("solid", "solid", "22", "22"), name = NULL, drop = FALSE) +
    guides(colour = guide_legend(nrow = 2), linetype = guide_legend(nrow = 2)) +
    labs(x = NULL, y = "Cases per 7 days", title = e$event, subtitle = "Shaded: event window. Solid lines 5-year baseline, dashed 3-year.")
  if (e$city == "Cagayan de Oro") p <- p + scale_y_sqrt() + labs(y = "Cases per 7 days (square-root scale)")
  save_fig(p, sprintf("case_%s.png", gsub(" ", "_", e$city)), h = 4)
}
sb <- summ[version %in% c("std5", "exc5")][, version := factor(version, levels = c("std5", "exc5"), labels = c("Standard", "Outbreak-excluded"))]
sb[, city := factor(city, levels = rev(city_order))]
p <- ggplot(sb, aes(pct_weeks_above, city, fill = version)) + geom_col(position = position_dodge(width = 0.75), width = 0.7) +
  scale_fill_manual(values = c(GREY, BLUE), name = NULL) +
  labs(x = "% of weeks above the epidemic threshold (5-year baseline, 2013-2022)", y = NULL)
save_fig(p, "weeks_above_by_city.png", h = 4.5)

log_step("Done")
print(summ[order(version, match(city, city_order))]); print(cs); print(episodes[, .N, by = version])
print(by_year[city == "Iloilo"])
