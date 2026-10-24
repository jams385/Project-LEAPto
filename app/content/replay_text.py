"""Wording of the Replay tab's "What happened" entries.

The templates here have blanks only; every number, date and level is filled
from src/replay.py output (computed from replay_weekly.csv and IMERG rain),
never typed. Wording rules: "chance of an outbreak week", "reported cases";
no claim of cause. A miss is said plainly.
"""

import pandas as pd

from app import config

# TEMPLATES +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

TITLES = {
    "rain": "Heaviest rain",
    "above": "First week above the outbreak line",
    "largest": "Largest outbreak begins",
    "alert": "Level rises",
    "alert_already": "Level already raised",
    "warning": "First Warning",
    "peak_forecast": "Highest forecast chance",
    "peak_cases": "Most cases in a week",
    "size": "Size of the outbreak",
}
RAIN = "{mm:.0f} mm of rain in the week of {week}{heavy}."
RAIN_HEAVY = ", a heavy-rain week ({limit} mm or more)"
RAIN_NOT_HEAVY = ", below the {limit} mm heavy-rain mark"
START = "{cases} reported {case_word} against an outbreak line of more than {line}. "
RUN = "{run_cases} cases over {weeks} {week_word} from this week. "
SHOWN = "The forecast for this week: {levels}. "
OUTCOME = {
    "warned": "The level was raised {horizon_word}: about {lead} weeks before case reports "
              "would have shown it.",
    "background": "The level had already been Watch or Warning for {run} weeks without an "
                  "outbreak, so it did not single this outbreak out. No lead time is claimed.",
    "missed": "The forecast was still Normal: this outbreak was missed at its start.",
}
ALERT = "The forecast for this week rose to {level} ({chance} chance of an outbreak week)."
ALERT_ALREADY = ("The outbreak event starts with the level already at {level} ({chance} chance), so "
                 "there is no rise to show.")
WARNING = "{chance} chance of an outbreak week; {cases} reported {case_word} that week."
PEAK_FORECAST = ("{chance} chance of an outbreak week ({level}); {cases} reported {case_word} "
                 "that week, {above}.")
PEAK_CASES = ("{cases} reported {case_word}{times}. The forecast for that week: {levels}.{miss}")
PEAK_CASES_MISS = " The level did not foresee it."
SIZE = ("{cases} cases in {weeks} {week_word} from the week of {first}: {share} of the "
        "{total} cases reported in this city in 2008–2022.")
SUMMARY = {
    "warned": "Lead time: the largest outbreak was flagged {horizon_word}, about {lead} "
              "weeks before case reports would have shown it.",
    "background": "No lead time is claimed: the level was already on for {run} weeks before "
                  "the largest outbreak began, so it did not signal it.",
    "missed": "No lead time: the largest outbreak began while the forecast was Normal.",
    "none": "No week was above the outbreak line in this outbreak event.",
}
FLAGGED = " {flagged} of {above} weeks above the outbreak line were at Watch or Warning one week ahead."
BEFORE_2014 = ("This outbreak event is before the model's 2014–2022 test years: its forecasts come from "
               "a model trained on about two years of data and use a 3-year outbreak line, so "
               "they are less certain.")
RAIN_NOTE = ("Rain is NASA IMERG Late, the version the model used (the Overview shows IMERG "
             "Final). Weeks after the one selected are shaded: the model could not know them.")


AHEAD = {1: "one week ahead", 2: "two weeks ahead"}


# FILLING +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def span(week):
    """A week as "Jul 8–14, 2018" (or "Dec 30, 2018–Jan 5, 2019" across a year).

    Parameters
    ----------
    week : pandas.Timestamp
        First day (a Sunday).

    Returns
    -------
    str
    """
    start = pd.Timestamp(week)
    end = start + pd.Timedelta(days=6)
    right = f"{end.day}" if end.month == start.month else f"{end:%b} {end.day}"
    left = f"{start:%b} {start.day}" + (f", {start.year}" if start.year != end.year else "")
    return f"{left}–{right}, {end.year}"


def _plural(n, one, many):
    """Singular or plural word for a whole number.

    Parameters
    ----------
    n : float
    one, many : str

    Returns
    -------
    str
    """
    return one if round(n) == 1 else many


def _levels(levels):
    """ "Watch one week ahead, Normal two weeks ahead".

    Parameters
    ----------
    levels : dict[int, str | None]
        Horizon -> level.

    Returns
    -------
    str
    """
    parts = [f"{lvl or 'no forecast'} {AHEAD.get(h, f'{h} weeks ahead')}"
             for h, lvl in sorted(levels.items())]
    return ", ".join(parts)


def _horizon_word(h):
    """ "1 week" / "2 weeks" (how far ahead the level was raised).

    Parameters
    ----------
    h : int

    Returns
    -------
    str
    """
    return f"{int(h)} {_plural(h, 'week', 'weeks')} ahead"


def _pct(p):
    """A chance as a whole percent, "11%" (never "0%": "under 1%").

    Parameters
    ----------
    p : float

    Returns
    -------
    str
    """
    return "under 1%" if p < 0.005 else f"{p:.0%}"


def _line(threshold):
    """The outbreak line as the number to beat: 1.04 -> "1" , 13.26 -> "13".

    Parameters
    ----------
    threshold : float

    Returns
    -------
    str
    """
    return f"{int(threshold)}"


def entry_text(entry):
    """Title and sentence for one "What happened" entry.

    Parameters
    ----------
    entry : dict
        src.replay.what_happened entry (kind, week, facts).

    Returns
    -------
    tuple[str, str]
        (title, body).
    """
    k, f = entry["kind"], entry["facts"]
    if k == "rain":
        heavy = (RAIN_HEAVY if f["heavy"] else RAIN_NOT_HEAVY).format(
            limit=config.REPLAY_HEAVY_RAIN_MM)
        return TITLES[k], RAIN.format(mm=f["mm"], week=span(entry["week"]), heavy=heavy)
    if k in ("above", "largest"):
        text = START.format(cases=f"{f['cases']:.0f}", line=_line(f["threshold"]),
                            case_word=_plural(f["cases"], "case", "cases"))
        if k == "largest":
            text = RUN.format(run_cases=f"{f['run_cases']:.0f}", weeks=int(f["weeks"]),
                              week_word=_plural(f["weeks"], "week", "weeks")) + text
        text += SHOWN.format(levels=_levels(f["levels"]))
        text += OUTCOME[f["outcome"]].format(
            run=int(f["run"]), lead=int(f["lead"] or 0),
            horizon_word=_horizon_word(f["horizon"]) if f["horizon"] else "")
        return TITLES[k], text
    if k == "alert":
        if f["already"]:
            return TITLES["alert_already"], ALERT_ALREADY.format(level=f["level"],
                                                                 chance=_pct(f["chance"]))
        return TITLES[k], ALERT.format(level=f["level"], chance=_pct(f["chance"]))
    if k == "warning":
        return TITLES[k], WARNING.format(chance=_pct(f["chance"]), cases=f"{f['cases']:.0f}",
                                         case_word=_plural(f["cases"], "case", "cases"))
    if k == "peak_forecast":
        return TITLES[k], PEAK_FORECAST.format(
            chance=_pct(f["chance"]), level=f["level"], cases=f"{f['cases']:.0f}",
            case_word=_plural(f["cases"], "case", "cases"),
            above="above the outbreak line" if f["above"] else "not above the outbreak line")
    if k == "peak_cases":
        times = (f", {f['times']:.0f} times the outbreak line" if f["times"] and f["times"] >= 2
                 else "")
        return TITLES[k], PEAK_CASES.format(
            cases=f"{f['cases']:.0f}", case_word=_plural(f["cases"], "case", "cases"),
            times=times, levels=_levels(f["levels"]),
            miss=PEAK_CASES_MISS if f["levels"].get(config.REPLAY_HORIZON) == "Normal" else "")
    if k == "size":
        return TITLES[k], SIZE.format(
            cases=f"{f['cases']:.0f}", weeks=int(f["weeks"]),
            week_word=_plural(f["weeks"], "week", "weeks"), first=span(f["first"]).split(",")[0],
            share=f"{f['share']:.0%}", total=f"{f['total']:,.0f}")
    return k, ""


def summary_text(summary):
    """The lead-time line under the entries.

    Parameters
    ----------
    summary : dict
        src.replay.what_happened summary.

    Returns
    -------
    str
        The verdict for the largest outbreak plus how many weeks above the
        outbreak line were flagged one week ahead.
    """
    s = summary
    text = SUMMARY[s["outcome"]].format(
        horizon_word=_horizon_word(s["horizon"]) if s["horizon"] else "",
        lead=int(s["lead"] or 0), run=int(s["run"]))
    if s["above_weeks"]:
        text += FLAGGED.format(flagged=s["flagged_weeks"], above=s["above_weeks"])
    return text
