# =============================================================================
# 07e_glofas_signal.R  —  Stage 7c, step 2: weekly river-flow signal on DOH morbidity weeks
#
# For each city and morbidity week (same rows as data/processed/city_week.rds):
#   river_peak   = highest daily flow in the week (m3/s) at the city's chosen GloFAS cell
#   river_z      = log(river_peak) compared with that river's normal: (log peak - mean) / SD, where mean and
#                  SD come from 2003-2007 weeks only. Those years precede all case data, so the scaling never
#                  uses information from the analysis or test years.
#   river_flood  = 1 if the peak reached that river's 2-year flood flow (median annual maximum, 2003-2007)
# Cities not used in the main analysis (river_choice.csv) keep the columns, flagged by river_used = FALSE.
# Also reports how much of the river signal is already explained by the city's own rainfall.
# Inputs : data/processed/glofas_city_day.csv, data/processed/city_week.rds
# Outputs: data/processed/glofas_city_week.csv, output/stage7/glofas_signal_*.csv, figs/glofas_signal_*.png
# =============================================================================
source("R/_common.R")
suppressPackageStartupMessages(library(ggplot2))
OUT <- file.path(PATHS$out, "stage7"); FIG <- file.path(OUT, "figs")

gd <- fread(file.path(PATHS$processed, "glofas_city_day.csv"))[, date := as.IDate(date)]
cw <- readRDS(file.path(PATHS$processed, "city_week.rds"))[, .(city, year, mw, start, end, pr_week_imf, cases, in_pidsr_period)]
days <- cw[, .(date = seq(start, end, by = 1)), by = .(city, year, mw, start)]
days <- merge(days, gd, by = c("city", "date"))
wk <- days[, .(river_peak = max(flow_m3s), river_mean = mean(flow_m3s), river_used = use_in_main_analysis[1]), by = .(city, year, mw, start)]
ref <- wk[year <= 2007, .(mu = mean(log1p(river_peak)), sd = sd(log1p(river_peak))), by = city]
fl2 <- days[year(date) <= 2007, .(amax = max(flow_m3s)), by = .(city, y = year(date))][, .(q2 = median(amax)), by = city]
wk <- merge(merge(wk, ref, by = "city"), fl2, by = "city")
wk[, `:=`(river_z = (log1p(river_peak) - mu) / sd, river_flood = as.integer(river_peak >= q2))]
wk <- merge(cw, wk[, .(city, year, mw, river_peak, river_mean, river_z, river_flood, river_used, q2)], by = c("city", "year", "mw"))
setorder(wk, city, start)
fwrite(wk[, .(city, year, mw, start, river_peak, river_mean, river_z, river_flood, river_used)], file.path(PATHS$processed, "glofas_city_week.csv"))

# ---- how much of the river signal does city rainfall already explain? -----------------------------
wk[, `:=`(lr0 = log1p(pr_week_imf), lr1 = shift(log1p(pr_week_imf), 1), lr2 = shift(log1p(pr_week_imf), 2), lr3 = shift(log1p(pr_week_imf), 3)), by = city]
ov <- wk[!is.na(lr3), {
  f <- lm(river_z ~ lr0 + lr1 + lr2 + lr3); .(weeks = .N, r2_rain_lags_0_3 = summary(f)$r.squared,
  cor_same_week = cor(river_z, lr0), flood_weeks_per_year = sum(river_flood) / uniqueN(year), q2_flow = q2[1], river_used = river_used[1]) }, by = city]
fwrite(ov[order(-river_used, city)], file.path(OUT, "glofas_signal_overlap_with_rain.csv"))
print(ov[order(-river_used, city), lapply(.SD, function(v) if (is.numeric(v)) round(v, 2) else v)])

# ---- figure: river signal and cases, river cities, PIDSR years --------------------------------------
pl <- wk[river_used == TRUE & in_pidsr_period == TRUE]
pl[, cases_scaled := cases / max(cases, na.rm = TRUE) * max(river_z, na.rm = TRUE), by = city]
p <- ggplot(pl, aes(start)) + geom_col(aes(y = cases_scaled), fill = "#c9c8c2", width = 7) +
  geom_line(aes(y = river_z), colour = "#2a78d6", linewidth = 0.3) + facet_wrap(~city, ncol = 1, scales = "free_y") +
  scale_x_date(date_breaks = "1 year", date_labels = "'%y", expand = c(0.005, 0)) +
  theme_minimal(base_size = 9) + theme(panel.grid.minor = element_blank(), strip.text = element_text(face = "bold", hjust = 0)) +
  labs(x = NULL, y = NULL, subtitle = "Blue: weekly river-flow signal (peak flow vs the river's 2003–2007 normal, SD units). Grey bars: leptospirosis cases (rescaled)")
ggsave(file.path(FIG, "glofas_signal_vs_cases.png"), p, width = 10, height = 11, dpi = 140, bg = "white")
log_step("Done")
