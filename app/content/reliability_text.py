"""Wording of the Data reliability tab (DESIGN_V3 §3).

Every sentence is a template whose numbers come from src/reliability.py. If a
number is missing the sentence shows "pending" (config.PENDING_TEXT) instead of
a guess. Descriptive phrases ("about a third", "7 in 10") are only produced
from the number that backs them (src.reliability.fraction_phrase / out_of_ten),
so they cannot drift from the data. Wording rules: "chance of an outbreak
week", "reported cases", no claim of cause.
"""

from app import config
from src.reliability import fraction_phrase, lead_weeks_range, out_of_ten

P = config.PENDING_TEXT

# SOURCE CAPTIONS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

SRC_METRICS = "level_metrics.csv: hit_rate, lift, n_weeks, capture_rate"
SRC_EPISODES = "episodes.csv: share"
SRC_AUC = "auc.csv: auc (final_model, seasonal_only; scope within city / all weeks)"
SRC_RAIN = "rain_gain.csv: lo (95% interval of the gain, per weeks ahead)"
SRC_LEAD = "config: forecast weeks + reporting delay (their stage 6 lead-time rule)"


# SMALL FORMATTERS +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def pct(x, digits=0):
    """A share as a percent, or "pending".

    Parameters
    ----------
    x : float | None
    digits : int

    Returns
    -------
    str
    """
    return P if x is None else f"{100 * x:.{digits}f}%"


def times(x):
    """A multiple as "6.1×" / "0.4×" (whole numbers from 10), or "pending".

    Parameters
    ----------
    x : float | None

    Returns
    -------
    str
    """
    if x is None:
        return P
    return f"{x:.1f}×" if x < 9.95 else f"{x:.0f}×"


def number(x, digits=0):
    """A plain number with thousands separators, or "pending".

    Parameters
    ----------
    x : float | None
    digits : int

    Returns
    -------
    str
    """
    return P if x is None else f"{x:,.{digits}f}"


def _names(pairs, fmt):
    """ "A (0.62) and B (0.68)" from (name, value) pairs.

    Parameters
    ----------
    pairs : list[tuple[str, float]]
    fmt : str
        Format for the value, e.g. "{:.2f}".

    Returns
    -------
    str
        "" for an empty list.
    """
    items = [f"{n} ({fmt.format(v)})" for n, v in pairs]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _horizon_list(hs):
    """ "1 and 2" / "3" / "1, 2 and 3" for a list of weeks ahead.

    Parameters
    ----------
    hs : list[int]

    Returns
    -------
    str
        "pending" for an empty list.
    """
    if not hs:
        return P
    names = [str(h) for h in hs]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# INTRO ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def intro(period):
    """The sentence under the title.

    Parameters
    ----------
    period : dict
        src.reliability.test_period output.

    Returns
    -------
    str
    """
    years = (f"{period['first_year']}–{period['last_year']}" if period["first_year"] else P)
    return (f"We tested the forecasts on {years}. Each year was forecast using only the years "
            f"before it, so the model never saw the answers: {number(period['city_weeks'])} "
            "city-weeks in all.")


# LEVEL ROWS ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def row_text(row, watch_start, normal_blips, horizon_name):
    """Headline and detail of one level row.

    Parameters
    ----------
    row : dict
        src.reliability.level_rows entry.
    watch_start : float | None
        Share of multi-week outbreaks whose first week was Watch (Watch row).
    normal_blips : float | None
        Share of Normal-start outbreaks that lasted one week (Normal row).
    horizon_name : str
        e.g. "next week".

    Returns
    -------
    tuple[str, str]
        (headline, detail).
    """
    head = f"About {times(row['lift'])} a usual week"
    weeks = (f"{pct(row['share_of_weeks'], 1)} of tested weeks, about "
             f"{row['weeks_per_city_year']:.0f} weeks a year per city")
    if row["level"] == "Warning":
        caught = pct(row["own_capture"])
        word = fraction_phrase(row["own_capture"])
        detail = (f"The top {config.LEVEL_RULE_WARNING_PCT}% of forecasts ({weeks}). Caught "
                  f"{caught}{f', about {word},' if word else ''} of all outbreak weeks.")
    elif row["level"] == "Watch":
        word = fraction_phrase(row["own_capture"])
        started = fraction_phrase(watch_start)
        start_text = (f" {pct(watch_start)}{f' (about {started})' if started else ''} of "
                      "multi-week outbreaks started in a Watch week.") if watch_start is not None \
            else f" Share of multi-week outbreaks that started in a Watch week: {P}."
        detail = (f"The next {config.LEVEL_RULE_WATCH_PCT}% of forecasts ({weeks}). Caught a "
                  f"further {pct(row['own_capture'])}"
                  f"{f', about {word},' if word else ''} of outbreak weeks "
                  f"({pct(row['cum_capture'])} with Warning).{start_text}")
    else:
        blips = (f", and {pct(normal_blips)} of the outbreaks that began in a Normal week "
                 "lasted a single week") if normal_blips is not None else ""
        detail = (f"The other {pct(row['share_of_weeks'])} of weeks. Normal means low risk, not "
                  f"none: {pct(row['own_capture'])} of all outbreak weeks still fell in Normal "
                  f"weeks{blips}.")
    return head, detail


# TILES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def tiles(rows, first_flagged, auc, rain_split, horizon):
    """The four summary tiles.

    Parameters
    ----------
    rows : list[dict]
        src.reliability.level_rows output (may be empty).
    first_flagged : float | None
        Share of multi-week outbreaks flagged in their first week.
    auc : dict
        src.reliability.auc_pair output.
    rain_split : dict | None
        src.reliability.rain_gain_split output.
    horizon : int

    Returns
    -------
    list[dict]
        big, sub, extra (second line or ""), source for each tile.
    """
    by = {r["level"]: r for r in rows}
    caught = by["Watch"]["cum_capture"] if "Watch" in by else None
    lo, hi = lead_weeks_range(horizon)
    lead = f"{lo}" if lo == hi else f"{lo}–{hi}"
    if rain_split is None:
        rain = f"How much rain adds at 3 and 4 weeks ahead: {P}."
    else:
        clear = _horizon_list(rain_split["clear"])
        rest = _horizon_list(rain_split["unclear"])
        rain = (f"Rain clearly improves forecasts at {clear} weeks ahead; at {rest} weeks its "
                "gain is not clearly above zero (earlier model vs the calendar).")
    fin, sea = auc["final_within"], auc["seasonal_within"]
    extra_auc = ""
    if auc["final_all"] is not None and auc["seasonal_all"] is not None:
        extra_auc = (f"All city-weeks pooled: {auc['final_all']:.2f} against "
                     f"{auc['seasonal_all']:.2f}.")
    return [
        {"big": out_of_ten(caught) or P,
         "sub": "outbreak weeks fell in a Watch or Warning week",
         "extra": f"That is {pct(caught)} of all outbreak weeks.", "source": SRC_METRICS},
        {"big": pct(first_flagged),
         "sub": "of multi-week outbreaks were flagged (Watch or Warning) in their first week",
         "extra": "", "source": SRC_EPISODES},
        {"big": f"{lead} weeks",
         "sub": "ahead of case reports, when an outbreak is flagged "
                f"{config.HORIZON_NAMES[horizon].lower()} (forecast weeks plus a 1-week "
                "reporting delay)",
         "extra": rain, "source": f"{SRC_LEAD}; {SRC_RAIN}"},
        {"big": P if fin is None else f"{fin:.2f}",
         "sub": "ranking score (AUC) within each city, against "
                f"{P if sea is None else f'{sea:.2f}'} for the seasonal calendar alone",
         "extra": extra_auc, "source": SRC_AUC},
    ]


# WHAT IT CANNOT DO +++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def cant_do(rows, counts, calibration, groups, no_report, peak):
    """The "What it can't do" bullets, each with its own source.

    Parameters
    ----------
    rows : list[dict]
        src.reliability.level_rows output.
    counts : dict | None
        src.reliability.case_counts output.
    calibration : dict | None
        src.reliability.calibration_top output.
    groups : dict | None
        src.reliability.city_groups_named output.
    no_report : dict | None
        src.reliability.no_report_weeks output.
    peak : dict | None
        src.reliability.event_peak output (Typhoon Washi).

    Returns
    -------
    list[dict]
        title, text, source.
    """
    by = {r["level"]: r for r in rows}
    out = []
    few = (f"The typical city-week has {counts['median']:.0f} reported cases, and "
           f"{pct(counts['share_le2'])} of weeks have 2 or fewer, so counts swing by chance. "
           "The app shows levels, not numbers.") if counts else (
        f"How few cases a typical week has: {P}. The app shows levels, not numbers.")
    out.append({"title": "Predict exact case numbers", "text": few,
                "source": "cases_weekly.csv: cases (tested years)"})
    if "Warning" in by:
        text = f"Even at Warning, {pct(1 - by['Warning']['rate'])} of weeks passed without an outbreak."
    else:
        text = f"Share of Warning weeks without an outbreak: {P}."
    if calibration:
        text += (f" The highest chances ran high: the {calibration['weeks']} weeks forecast at "
                 f"{pct(config.RELIABILITY_CALIBRATION_FROM)} or more averaged "
                 f"{pct(calibration['forecast'])}, and {pct(calibration['observed'])} became "
                 "outbreak weeks.")
    out.append({"title": "Promise an outbreak", "text": text,
                "source": "level_metrics.csv: hit_rate; alerts.csv: outbreak_prob, "
                          "observed_outbreak"})
    if groups is None:
        where = f"Which cities are weaker, and which show a case signal only: {P}."
    else:
        weak = _names(groups["lower"], "{:.2f}")
        sig = _names(groups["case_signal"], "{:d} outbreak weeks").replace(
            "(1 outbreak weeks)", "(1 outbreak week)")
        where = ""
        if weak:
            where += (f"It is weaker in {weak}, where outbreak weeks were ranked less well "
                      f"(ranking score, AUC, below {config.LOWER_CONFIDENCE_AUC:.2f}). ")
        if sig:
            where += (f"{sig} had too few outbreak weeks to forecast a level, so they show a "
                      "case signal only.")
    out.append({"title": "Work equally well everywhere", "text": where.strip(),
                "source": "city_confidence.csv: auc, outbreak_weeks"})
    if peak:
        times_text = f", {peak['times']:.0f} times the outbreak line" if peak["times"] else ""
        level = peak["level"] or "missing"
        text = (f"In the peak week of Typhoon Washi in Cagayan de Oro ({peak['cases']:.0f} "
                f"reported cases{times_text}) the forecast was {level}. A sudden flood is a "
                "case for the health office's Flood alert, which is not part of the tested forecasts.")
    else:
        text = f"What happened in Typhoon Washi's peak week: {P}."
    out.append({"title": "Foresee a sudden catastrophic flood", "text": text,
                "source": "replay_weekly.csv: observed_cases, threshold, alert_level"})
    if no_report:
        text = (f"{number(no_report['flagged'])} of {number(no_report['total'])} city-weeks "
                f"({pct(no_report['flagged'] / no_report['total'], 1)}) have no usable case "
                "report. They show No report, not a level.")
    else:
        text = f"How many city-weeks have no usable case report: {P}."
    out.append({"title": "Judge a week with no case report", "text": text,
                "source": "reporting_flags.csv; cases_weekly.csv"})
    return out
