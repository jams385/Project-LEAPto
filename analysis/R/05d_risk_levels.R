# =============================================================================
# 05d_risk_levels.R  —  Stage 5d: risk levels for the app (Normal / Watch / Warning)
#
# Final forecasting model (pooled rain + recent level + case history, Typhoon Washi set aside, "pooled_ar4_lvl_nw"), 1 and 2 weeks
# ahead, outbreak = above the 5-year outbreak-excluded DOH threshold. For each test year (2014-2022) the
# cut-offs are set from that origin's TRAINING years only, then applied to the test year.
#
# Cut-off rule (ranking): Warning = forecast chance at or above the 95th percentile of the training-year
# forecasts, Watch = at or above the 80th (i.e. the next 15%). Three versions, compared side by side:
#   V1 one for all       : percentiles over all cities' training weeks
#   V2 per city          : percentiles over each city's own training weeks
#   V3 per city + minimum: V2, but a week is Watch only if its chance is also >= 10%, Warning only if >= 25%
#                          (minimums fixed in advance)
# Low-case cities (Stage 4 city_type) are reported separately; in the app they also show the Stage 4
# "confirmed unusual week" signal.
#
# Inputs : output/stage5/forecasts_washi.csv.gz (final model, from 05e_washi_setaside.R), output/stage4/{outbreak_episodes,city_type}.csv
# Outputs: output/stage5/risk_levels_*.csv, output/stage5/figs/risk_levels_*.png
# =============================================================================

source("R/_common.R")
suppressPackageStartupMessages({ library(ggplot2) })
OUT <- file.path(PATHS$out, "stage5"); FIG <- file.path(OUT, "figs")
VARIANT <- "pooled_ar4_lvl_nw"; HS <- 1:2; Q_WATCH <- 0.80; Q_WARN <- 0.95; MIN_WATCH <- 0.10; MIN_WARN <- 0.25
VERS <- c(V1 = "One cut-off for all cities", V2 = "Per city", V3 = "Per city + minimum")
LEVELS <- c("Normal", "Watch", "Warning")
BLUE <- "#2a78d6"; ORANGE <- "#eb6834"; YELLOW <- "#eda100"; GREY <- "#8a8984"; INK <- "#0b0b0b"; LIGHT <- "#c9c8c2"
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(), legend.position = "top",
          strip.text = element_text(face = "bold", hjust = 0), plot.title.position = "plot"))
save_fig <- function(p, name, w = 9, h = 4.5) ggsave(file.path(FIG, name), p, width = w, height = h, dpi = 150, bg = "white")

f <- fread(file.path(OUT, "forecasts_washi.csv.gz"))[variant == VARIANT & h %in% HS & !is.na(thr_exc5)]
f[, start := as.IDate(start)]
f[, p := 1 - pnbinom(floor(thr_exc5 * days / 7), size = theta, mu = mu)]
f <- f[!is.na(p)]
ctype <- fread(file.path(PATHS$out, "stage4", "city_type.csv"))[, .(city, low_case = city_type == "low-case")]
f <- merge(f, ctype, by = "city")
tr <- f[set == "train"]; te <- f[set == "test" & include == TRUE & !is.na(y) & !is.na(above_exc5)]

# ---- cut-offs from training years ---------------------------------------------------------------
cut_all <- tr[, .(watch = quantile(p, Q_WATCH), warn = quantile(p, Q_WARN)), by = .(origin, h)]
cut_city <- tr[, .(watch = quantile(p, Q_WATCH), warn = quantile(p, Q_WARN)), by = .(origin, h, city)]
cuts <- rbind(merge(CJ(origin = unique(te$origin), h = HS, city = unique(te$city)), cut_all, by = c("origin", "h"))[, version := "V1"],
              copy(cut_city)[, version := "V2"],
              copy(cut_city)[, `:=`(version = "V3", watch = pmax(watch, MIN_WATCH), warn = pmax(warn, MIN_WARN))])
fwrite(cuts[order(version, h, city, origin)], file.path(OUT, "risk_levels_cutoffs.csv"))

lv <- merge(te[, .(origin, h, city, low_case, year, mw, start, days, y, mu, p, thr_exc5, above = above_exc5)],
            cuts, by = c("origin", "h", "city"), allow.cartesian = TRUE)
lv[, level := factor(fifelse(p >= warn, "Warning", fifelse(p >= watch, "Watch", "Normal")), levels = LEVELS)]
lv[, group := fifelse(low_case, "Low-case cities", "Other cities")]
fwrite(lv, file.path(OUT, "risk_levels_weekly.csv.gz"))

# ---- scoring ------------------------------------------------------------------------------------------
wilson <- function(k, n) { if (n == 0) return(c(NA, NA)); z <- 1.96; ph <- k / n; d <- 1 + z^2 / n
  c((ph + z^2 / (2 * n) - z * sqrt(ph * (1 - ph) / n + z^2 / (4 * n^2))) / d, (ph + z^2 / (2 * n) + z * sqrt(ph * (1 - ph) / n + z^2 / (4 * n^2))) / d) }
by_level <- function(x, by) x[, { ncy <- uniqueN(paste(city, year)); tot <- sum(above)
  .SD[, { ci <- wilson(sum(above), .N)
    .(weeks = .N, weeks_per_city_year = .N / ncy, outbreak_rate = mean(above), lo = ci[1], hi = ci[2],
      share_of_outbreak_weeks = sum(above) / tot, false_alarms_per_city_year = sum(!above) / ncy) }, by = level] }, by = by]
summ <- rbind(by_level(lv, c("version", "h"))[, group := "All cities"], by_level(lv, c("version", "h", "group")))
summ[, base_rate := lv[, mean(above), by = .(version, h)][summ, on = .(version, h), V1]]
fwrite(summ[order(version, h, group, level)], file.path(OUT, "risk_levels_summary.csv"))

overall <- lv[, .(caught_watch_or_warning = mean(level[above] != "Normal"), caught_warning = mean(level[above] == "Warning"),
                  flagged_weeks_per_city_year = sum(level != "Normal") / uniqueN(paste(city, year)),
                  false_alarms_per_city_year = sum(level != "Normal" & !above) / uniqueN(paste(city, year)),
                  precision_watch_or_warning = mean(above[level != "Normal"]), precision_warning = mean(above[level == "Warning"]),
                  max_flagged_weeks_one_city_year = max(.SD[, sum(level != "Normal"), by = .(city, year)]$V1)),
              by = .(version, h, group = fifelse(low_case, "Low-case cities", "Other cities"))]
overall <- rbind(overall, lv[, .(group = "All cities", caught_watch_or_warning = mean(level[above] != "Normal"), caught_warning = mean(level[above] == "Warning"),
                  flagged_weeks_per_city_year = sum(level != "Normal") / uniqueN(paste(city, year)),
                  false_alarms_per_city_year = sum(level != "Normal" & !above) / uniqueN(paste(city, year)),
                  precision_watch_or_warning = mean(above[level != "Normal"]), precision_warning = mean(above[level == "Warning"]),
                  max_flagged_weeks_one_city_year = max(.SD[, sum(level != "Normal"), by = .(city, year)]$V1)), by = .(version, h)])
fwrite(overall[order(version, h, group)], file.path(OUT, "risk_levels_overall.csv"))

city_tab <- lv[h == 1, .(outbreak_weeks = sum(above), watch_per_yr = sum(level == "Watch") / uniqueN(year), warning_per_yr = sum(level == "Warning") / uniqueN(year),
                         caught = if (sum(above)) mean(level[above] != "Normal") else NA_real_,
                         precision_warning = if (sum(level == "Warning")) mean(above[level == "Warning"]) else NA_real_,
                         precision_flagged = if (sum(level != "Normal")) mean(above[level != "Normal"]) else NA_real_), by = .(version, city, low_case)]
fwrite(city_tab[order(version, -outbreak_weeks)], file.path(OUT, "risk_levels_by_city.csv"))

ep <- fread(file.path(PATHS$out, "stage4", "outbreak_episodes.csv"))[version == "exc5"][, start := as.IDate(start)][year(start) >= 2014]
epw <- merge(ep[, .(city, start, weeks)], lv[, .(version, h, city, start, level)], by = c("city", "start"))
epw <- epw[, .N, by = .(version, h, episode = fifelse(weeks > 1, "2+ weeks", "single week"), level)][, share := N / sum(N), by = .(version, h, episode)]
fwrite(epw[order(version, h, episode, level)], file.path(OUT, "risk_levels_episodes.csv"))
pre <- by_level(lv[year <= 2019], c("version", "h"))
fwrite(pre[order(version, h, level)], file.path(OUT, "risk_levels_summary_2014_2019.csv"))

options(width = 200)
print(summ[group == "All cities" & h == 1][order(version, level), .(version, level, weeks, wpy = round(weeks_per_city_year, 1), rate = round(100 * outbreak_rate, 1), lo = round(100 * lo, 1), hi = round(100 * hi, 1), share = round(100 * share_of_outbreak_weeks, 1), fa = round(false_alarms_per_city_year, 1))])
print(overall[h == 1][order(version, group)][, lapply(.SD, function(v) if (is.numeric(v)) round(v, 3) else v)])
print(dcast(city_tab, city + low_case ~ version, value.var = c("warning_per_yr", "watch_per_yr", "caught"))[, lapply(.SD, function(v) if (is.numeric(v)) round(v, 2) else v)])
print(epw[h == 1 & level != "Normal", .(share = sum(share)), by = .(version, episode)])
print(summ[h == 1 & group != "All cities" & level != "Normal"][order(group, version, level), .(group, version, level, weeks, rate = round(100 * outbreak_rate, 1), share = round(100 * share_of_outbreak_weeks, 1))])

# ---- figures ------------------------------------------------------------------------------------------
LCOL <- c(Normal = LIGHT, Watch = YELLOW, Warning = ORANGE)
pd <- summ[group == "All cities"][, `:=`(vlab = factor(VERS[version], levels = VERS), hz = paste0(h, " week", fifelse(h > 1, "s", ""), " ahead"))]
p <- ggplot(pd, aes(level, outbreak_rate, fill = level)) + geom_col(width = 0.65) +
  geom_errorbar(aes(ymin = lo, ymax = hi), width = 0.15, colour = INK, linewidth = 0.4) +
  geom_hline(aes(yintercept = base_rate), linetype = "dashed", colour = GREY) +
  geom_text(aes(label = sprintf("%.0f%%", 100 * outbreak_rate), y = hi), vjust = -0.5, size = 3) +
  facet_grid(hz ~ vlab) + scale_fill_manual(values = LCOL, guide = "none") +
  scale_y_continuous(labels = scales::percent, expand = expansion(mult = c(0, 0.15))) +
  labs(x = NULL, y = "Share of weeks that became outbreak weeks", subtitle = "Test years 2014–2022, 95% intervals. Dashed: usual rate across all weeks")
save_fig(p, "risk_levels_outbreak_rate.png", h = 5.5)

cw <- melt(city_tab[, .(version, city, low_case, Watch = watch_per_yr, Warning = warning_per_yr)], id.vars = c("version", "city", "low_case"), variable.name = "level")
ord <- city_tab[version == "V1"][order(-(watch_per_yr + warning_per_yr)), city]
cw[, `:=`(city = factor(city, levels = rev(ord)), vlab = factor(VERS[version], levels = VERS))]
p <- ggplot(cw, aes(value, city, fill = level)) + geom_col(width = 0.7) + facet_wrap(~vlab) +
  scale_fill_manual(values = LCOL, name = NULL) +
  labs(x = "Weeks per year at Watch or Warning (1 week ahead)", y = NULL, subtitle = "Low-case cities: Muntinlupa, Mandaluyong, Tacloban, Palayan, Legazpi, Mandaue")
save_fig(p, "risk_levels_by_city.png", h = 4.8)

tl <- lv[version == "V1" & h == 1 & ((city == "Iloilo") | (city == "Navotas" & year == 2018))]
tl[, panel := fifelse(city == "Iloilo", "Iloilo, 2014–2022", "Navotas, 2018")]
for (pp in unique(tl$panel)) {
  x <- tl[panel == pp]
  g <- ggplot(x, aes(start, y, fill = level)) + geom_col(width = 7) +
    geom_step(data = x, mapping = aes(x = start, y = floor(thr_exc5 * days / 7) + 0.5), direction = "mid", colour = INK, linewidth = 0.3, inherit.aes = FALSE) +
    scale_fill_manual(values = LCOL, name = "Level forecast 1 week ahead") +
    scale_x_date(date_breaks = if (pp %like% "Iloilo") "1 year" else "1 month", date_labels = if (pp %like% "Iloilo") "%Y" else "%b") +
    labs(x = NULL, y = "Cases per week", title = pp, subtitle = "Bars: observed cases, coloured by the level forecast a week earlier. Line: epidemic threshold (cases above it = outbreak week)")
  save_fig(g, sprintf("risk_levels_timeline_%s.png", if (pp %like% "Iloilo") "Iloilo" else "Navotas_2018"), h = 3.8)
}
log_step("Done")
