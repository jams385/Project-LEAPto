# =============================================================================
# 06_case_studies.R  —  Stage 6: would LeapTo have warned of three known outbreaks?
#
# Events (project document): Cagayan de Oro after Typhoon Washi (Dec 2011 - Jan 2012), Navotas July 2018,
# Iloilo 2011-2012. Final forecasting model (rain + recent level + case history, Washi set aside, "pooled_ar4_lvl_nw", IMERG Late,
# 1-week reporting delay), 1 and 2 weeks ahead; seasonal-only model for comparison.
#
# Two views:
#   strict ("as of then"): trained only on data before the forecast year, retrained each January, exactly as in the
#           Stage 5 rolling test (origins 2010, 2011, 2017).
#   today  ("today's model"): trained on all 2008-2022 data EXCEPT the event window in the event city, so the
#           model never sees the outbreak. Not fair in time; shows whether the current model would catch a similar event.
# Threshold: the DOH outbreak-excluded threshold the app uses (5-year); for 2011-12 only the 3-year version exists.
# Risk levels: Stage 5d rule, one cut-off for all cities from the training forecasts (top 5% Warning, next 15%
#   Watch). Strict 2011-12 fits: training weeks have no threshold yet, so their outbreak chance uses the forecast
#   year's threshold for the same city and week (known at forecast time).
# Lead time: a forecast for week t at horizon h is issued at the end of week t-h. Without the app, the health office
#   learns of an outbreak starting in week t at the end of week t + 1 (1-week reporting delay). If the episode's first
#   week was at Watch or Warning at horizon h, the app's lead over the health office is h + 1 weeks.
# Outputs: output/stage6/*.csv, output/stage6/figs/*.png
# =============================================================================
src5 <- readLines("R/05_validation.R")
eval(parse(text = src5[1:(grep("^# ---- Run \\(or reuse\\)", src5) - 1)]))
suppressPackageStartupMessages(library(patchwork))
OUT6 <- file.path(PATHS$out, "stage6"); FIG6 <- file.path(OUT6, "figs"); dir.create(FIG6, recursive = TRUE, showWarnings = FALSE)
FINAL <- "pooled_ar4_lvl_nw"; MODELS <- c(FINAL, "seasonal"); H6 <- 1:2

EV <- data.table(
  event = c("washi", "navotas", "iloilo"),
  label = c("Cagayan de Oro after Typhoon Washi", "Navotas, July 2018", "Iloilo, 2011–2012"),
  city  = c("Cagayan de Oro", "Navotas", "Iloilo"),
  from  = as.IDate(c("2011-10-01", "2018-04-01", "2011-01-01")),
  to    = as.IDate(c("2012-03-31", "2018-10-31", "2012-12-31")),
  thr   = c("exc3", "exc5", "exc3"))
th4 <- fread(file.path(PATHS$out, "stage4", "thresholds_weekly.csv"))[, .(city, year, mw, thr_exc3, above_exc3)]
eps <- fread(file.path(PATHS$out, "stage4", "outbreak_episodes.csv"))[, `:=`(start = as.IDate(start), end = as.IDate(end))]

# ---- fits ---------------------------------------------------------------------------------------------
strict_jobs <- CJ(origin = c(2010L, 2011L, 2017L), h = H6, model = MODELS)[, view := "strict"]
today_jobs <- CJ(event = EV$event, h = H6, model = MODELS)[, view := "today"]
jobs <- rbind(strict_jobs, today_jobs, fill = TRUE)
FC6 <- file.path(OUT6, "forecasts_case_studies.csv.gz")
if (!file.exists(FC6) || Sys.getenv("STAGE6_REFIT") == "1") {
  log_step("Stage 6:", nrow(jobs), "fits on", CORES, "cores")
  res <- mclapply(seq_len(nrow(jobs)), function(i) {
    j <- jobs[i]; t0 <- Sys.time()
    r <- tryCatch({
      if (j$view == "strict") fit_forecast(j$origin, j$h, j$model) else {
        e <- EV[event == j$event]
        win_e <- d$city == e$city & d$start >= e$from & d$start <= e$to
        fit_forecast(2021L, j$h, j$model, tr_mask = !win_e, te_mask = win_e)
      } }, error = function(err) { message("FAIL ", paste(j, collapse = " "), ": ", conditionMessage(err)); NULL })
    message(sprintf("%s | %-6s %-7s h%d %-15s %.0fs %s", format(Sys.time(), "%H:%M:%S"), j$view, if (is.na(j$event)) j$origin else j$event,
                    j$h, j$model, as.numeric(difftime(Sys.time(), t0, units = "secs")),
                    if (is.null(r)) "FAILED" else if (!r$converged[1]) "(not converged)" else ""))
    if (is.null(r)) NULL else r[, `:=`(view = j$view, event = if (is.na(j$event)) NA_character_ else j$event, model = j$model)]
  }, mc.cores = CORES, mc.preschedule = FALSE)
  fc6 <- rbindlist(res); fwrite(fc6, FC6)
} else fc6 <- fread(FC6)
fc6[, start := as.IDate(start)]
fc6 <- merge(fc6, th4, by = c("city", "year", "mw"), all.x = TRUE)
fwrite(unique(fc6[, .(view, origin, event, h, model, converged, optimiser)]), file.path(OUT6, "fit_status.csv"))

# ---- outbreak chance, risk-level cut-offs -------------------------------------------------------------
pex <- function(mu, theta, thr, days) 1 - pnbinom(floor(thr * days / 7), size = theta, mu = mu)
fc6[, grp := fifelse(view == "strict", paste0("o", origin), event)]
# strict 2011-12: training-week chance against the forecast year's threshold (same city and week)
fy <- th4[year %in% 2011:2012, .(city, fyear = year, mw, thr_fy = thr_exc3)]
fc6[, fyear := origin + 1L]
fc6 <- merge(fc6, fy, by = c("city", "fyear", "mw"), all.x = TRUE)
fc6[, thr_use := fcase(
  view == "strict" & origin == 2017L, thr_exc5,
  view == "strict" & set == "train", thr_fy,
  view == "strict", thr_exc3,
  set == "train", thr_exc5,
  event == "navotas", thr_exc5,
  rep(TRUE, .N), thr_exc3)]
fc6[, above := fcase(view == "strict" & origin == 2017L, above_exc5, view == "today" & (set == "train" | event == "navotas"), above_exc5, rep(TRUE, .N), above_exc3)]
fc6[, p := pex(mu, theta, thr_use, days)]
cuts <- fc6[set == "train" & !is.na(p), .(watch = quantile(p, 0.80), warn = quantile(p, 0.95)), by = .(grp, view, h, model)]
fwrite(cuts, file.path(OUT6, "risk_cutoffs.csv"))
fc6 <- merge(fc6, cuts, by = c("grp", "view", "h", "model"))
fc6[, level := factor(fifelse(p >= warn, "Warning", fifelse(p >= watch, "Watch", "Normal")), levels = c("Normal", "Watch", "Warning"))]

# event rows: event city, inside the window, forecast rows only
evf <- rbindlist(lapply(seq_len(nrow(EV)), function(i) { e <- EV[i]
  fc6[set == "test" & city == e$city & start >= e$from & start <= e$to & (view == "today" & event == e$event | view == "strict")][, event := e$event] }))
evf[, lo80 := qnbinom(0.10, size = theta, mu = mu)][, hi80 := qnbinom(0.90, size = theta, mu = mu)]
evf[, issued := start - 7L * (h - 1L) - 1L]
evf <- merge(evf, d[, .(city, start, rain = pr_week_iml)], by = c("city", "start"))
fwrite(evf[order(event, view, model, h, start), .(event, view, model, h, city, year, mw, start, issued, cases, mu, lo80, hi80, threshold = thr_use, above, p, level, rain)],
       file.path(OUT6, "case_study_weekly.csv"))

# ---- episodes (Stage 4 definition, 2+ weeks) -------------------------------------------------------------
ep <- rbindlist(lapply(seq_len(nrow(EV)), function(i) { e <- EV[i]
  eps[city == e$city & version == e$thr & start >= e$from & start <= e$to & weeks >= 2][, event := e$event] }))
ep[, known_without_app := start + 13L]   # end of week t + 1 (1-week reporting delay)
epi <- rbindlist(lapply(seq_len(nrow(ep)), function(i) { x <- ep[i]
  w <- evf[event == x$event & start >= x$start - 28L & start <= x$end]
  w[, {
    f <- .SD[start == x$start]; if (!nrow(f)) f <- data.table(level = factor(NA, levels = c("Normal", "Watch", "Warning")), p = NA_real_); run <- .SD[start >= x$start - 28L & start < x$start]; inn <- .SD[start >= x$start & start <= x$end]
    .(event = x$event, episode_start = x$start, episode_end = x$end, weeks = x$weeks, cases = x$total_cases, peak = x$peak_cases,
      first_week_level = as.character(f$level), first_week_chance = f$p,
      lead_weeks = fifelse(f$level != "Normal", as.integer(h + DELAY), 0L),
      runup_watch_or_warning = sum(run$level != "Normal"), runup_weeks = nrow(run),
      episode_weeks_flagged = sum(inn$level != "Normal"), episode_weeks_warning = sum(inn$level == "Warning"),
      forecast_cases = sum(inn$mu), forecast_peak = max(inn$mu))
  }, by = .(view, model, h)] }))
fwrite(epi[order(event, episode_start, view, model, h)], file.path(OUT6, "case_study_episodes.csv"))

# whole-window summary: how the levels sorted outbreak and normal weeks
win_s <- evf[!is.na(above), .(weeks = .N, outbreak_weeks = sum(above), caught = mean(level[above] != "Normal"), warning_caught = mean(level[above] == "Warning"),
                              false_alarm_weeks = sum(level != "Normal" & !above, na.rm = TRUE), observed = sum(cases), forecast = sum(mu)), by = .(event, view, model, h)]
fwrite(win_s[order(event, view, model, h)], file.path(OUT6, "case_study_summary.csv"))

# check: strict Navotas forecasts match the Stage 5 rolling test
st5 <- fread(file.path(OUT, "forecasts_washi.csv.gz"))[variant == FINAL & origin == 2017 & city == "Navotas" & set == "test", .(h, start = as.IDate(start), mu5 = mu)]
chk <- merge(evf[event == "navotas" & view == "strict" & model == FINAL, .(h, start, mu)], st5, by = c("h", "start"))
cat("Navotas strict vs Stage 5: max abs difference in forecast mean =", signif(max(abs(chk$mu - chk$mu5)), 3), "over", nrow(chk), "weeks\n")

# ---- figures --------------------------------------------------------------------------------------------------
LVL_COL <- c(Normal = "#ffffff", Watch = "#f6d58e", Warning = "#eb6834")
INK <- "#0b0b0b"; GREY <- "#8a8984"; BLUE <- "#2a78d6"
VIEW_LAB <- c(strict = "As of then (trained only on earlier years)", today = "Today's model (trained on all years except this event)")
for (i in seq_len(nrow(EV))) { e <- EV[i]
  x <- evf[event == e$event & model == FINAL & h == 1]
  rn <- unique(x[, .(start, rain)])
  pr <- ggplot(rn, aes(start + 3, rain)) + geom_col(fill = BLUE, width = 6) +
    labs(x = NULL, y = "Rain (mm/week)", title = sprintf("%s — 1 week ahead", e$label)) +
    theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), axis.text.x = element_blank(), plot.title.position = "plot")
  pp <- lapply(c("strict", "today"), function(v) { z <- x[view == v]
    ggplot(z, aes(start + 3)) +
      geom_rect(aes(xmin = start, xmax = start + 7, ymin = -Inf, ymax = Inf, fill = level), alpha = 0.55) +
      geom_col(aes(y = cases), fill = "#c9c8c2", width = 5) +
      geom_ribbon(aes(ymin = lo80, ymax = hi80), fill = INK, alpha = 0.12) +
      geom_line(aes(y = mu), colour = INK, linewidth = 0.7) +
      geom_step(aes(x = start, y = thr_use * days / 7), colour = "#d03b3b", linetype = "dashed", linewidth = 0.5, direction = "hv") +
      scale_fill_manual(values = LVL_COL, name = "Risk level", drop = FALSE, na.value = "white", na.translate = FALSE) +
      scale_y_continuous(trans = if (e$event == "washi") "sqrt" else "identity") +
      labs(x = NULL, y = if (e$event == "washi") "Cases per week (square-root scale)" else "Cases per week", subtitle = VIEW_LAB[v]) +
      theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top") })
  g <- (pr / pp[[1]] / pp[[2]]) + plot_layout(heights = c(1, 2.2, 2.2), guides = "collect") +
    plot_annotation(caption = "Grey bars: reported cases. Black line and band: forecast and 80% range. Red dashed: DOH epidemic threshold. Shading: risk level for that week.") &
    theme(legend.position = "bottom")
  ggsave(file.path(FIG6, sprintf("case_%s.png", e$event)), g, width = 10, height = 8.5, dpi = 150, bg = "white")
}

options(width = 220)
print(fread(file.path(OUT6, "fit_status.csv")))
print(epi[model == FINAL][order(event, episode_start, view, h), .(event, episode_start, weeks, cases, view, h, first_week_level, chance = round(first_week_chance, 2),
        lead_weeks, runup = paste0(runup_watch_or_warning, "/", runup_weeks), flagged = paste0(episode_weeks_flagged, "/", weeks), fc_cases = round(forecast_cases), fc_peak = round(forecast_peak, 1), peak)])
print(epi[model == "seasonal" & h == 1][order(event, episode_start, view), .(event, episode_start, view, first_week_level, chance = round(first_week_chance, 2), flagged = paste0(episode_weeks_flagged, "/", weeks), fc_cases = round(forecast_cases))])
print(win_s[, lapply(.SD, function(v) if (is.numeric(v)) round(v, 2) else v)])
log_step("Done")
