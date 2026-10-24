# =============================================================================
# 03c_washi_check.R  —  do the Stage 3 findings depend on Typhoon Washi?
# Refits the Stage 3 main model with Washi's 5 outbreak weeks in Cagayan de Oro (18 Dec 2011 - 21 Jan 2012) set
# aside, and compares the headline results: risk after a heavy-rain week, peak lag, extra cases from one heavy-rain
# week, and the share of cases attributable to heavy rain.
# Output: output/stage3/washi_check.csv
# =============================================================================
src3 <- readLines("R/03_dlnm.R")
eval(parse(text = src3[1:(grep("^d <- prep\\(\\)", src3) - 1)]))
eval(parse(text = src3[grep("^attributable <- function", src3):(grep("^attributable <- function", src3) + 20)]))
M3S <- readRDS(file.path(PATHS$out, "stage3", "main_model.rds"))$spec
d <- prep()
spec <- function(dat) fit_dlnm(dat, L = M3S$L, var_q = VAR_SPECS[[M3S$var]], nk = M3S$nk)
dw <- copy(d)[city == "Cagayan de Oro" & start >= as.IDate("2011-12-18") & start <= as.IDate("2012-01-21"), y := NA]
set.seed(2024)
res <- rbindlist(lapply(list(`Main model` = d, `Washi weeks set aside` = dw), function(x) {
  f <- spec(x); s <- summarise_fit(f, "")
  a <- attributable(f, .95)[city == "total"]
  s[, .(n, rr_peak_lag, peak_lag, lags_signif, excess_p95, heavy_rain_cases_pct = a$pct, heavy_rain_pct_lo = a$pct_lo, heavy_rain_pct_hi = a$pct_hi)]
}), idcol = "model")
fwrite(res, file.path(OUT, "washi_check.csv")); print(res)
log_step("Done")
