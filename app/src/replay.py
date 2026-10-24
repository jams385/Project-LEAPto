"""Pure builders for the Replay tab: one season's weeks, and "What happened".

Everything here is computed from replay_weekly.csv (the modeling team's
stage 6 "as of then" forecasts: trained on earlier years only, retrained each
January) and IMERG rain. Nothing about a season is typed in: the flood week,
the first week above the outbreak line, the first alert, the peak forecast,
the peak cases and the lead time are all found in the data. The wording lives
in app/content/replay_text.py.
"""

import numpy as np
import pandas as pd

from app import config

FLAGGED = ("Watch", "Warning")

# SEASON TABLE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def season_table(replay, rain, season):
    """One row per week of a season: rain, cases, the outbreak line and the levels.

    Parameters
    ----------
    replay : pandas.DataFrame
        replay_weekly.csv (event, adm3_pcode, horizon, target_week,
        outbreak_prob, alert_level, observed_cases, threshold, observed_outbreak).
    rain : pandas.DataFrame
        IMERG weekly rain with the Late values the model used (adm3_pcode,
        week_start, rain_mm_7d_late).
    season : dict
        A config.REPLAY_SEASONS entry (event, city, from, to).

    Returns
    -------
    pandas.DataFrame
        week_start, rain_mm, cases (float), threshold, above (bool, False
        where there is no outbreak line), and level_<h> / p_<h> for each
        horizon in config.ALERT_HORIZONS (level None where there is no
        forecast). Sorted by week; empty if the event has no rows.
    """
    rows = replay[(replay.event == season["event"]) & (replay.adm3_pcode == season["city"])
                  & replay.target_week.between(pd.Timestamp(season["from"]),
                                               pd.Timestamp(season["to"]))]
    if rows.empty:
        return pd.DataFrame()
    base = (rows[rows.horizon == config.REPLAY_HORIZON]
            .rename(columns={"target_week": "week_start", "observed_cases": "cases"})
            [["week_start", "cases", "threshold", "observed_outbreak"]])
    out = base.assign(cases=base.cases.astype("float"),
                      above=base.observed_outbreak.fillna(False).astype(bool)
                      ).drop(columns="observed_outbreak")
    for h in config.ALERT_HORIZONS:
        part = rows[rows.horizon == h].rename(columns={
            "target_week": "week_start", "alert_level": f"level_{h}",
            "outbreak_prob": f"p_{h}"})[["week_start", f"level_{h}", f"p_{h}"]]
        out = out.merge(part, on="week_start", how="left")
        out[f"level_{h}"] = out[f"level_{h}"].astype(object).where(out[f"level_{h}"].notna(), None)
    r = rain[rain.adm3_pcode == season["city"]][["week_start", "rain_mm_7d_late"]].rename(
        columns={"rain_mm_7d_late": "rain_mm"})
    out = out.merge(r, on="week_start", how="left")
    return out.sort_values("week_start").reset_index(drop=True)


def panel_window(weeks, selected, size=config.REPLAY_PANEL_WEEKS):
    """The `size` weeks the three panels show for a selected week.

    Parameters
    ----------
    weeks : list[pandas.Timestamp]
        Every week of the season, sorted.
    selected : pandas.Timestamp
    size : int

    Returns
    -------
    list[pandas.Timestamp]
        `size` consecutive weeks (fewer if the season is shorter) with the
        selected week as near the middle as the season's ends allow.
    """
    size = min(size, len(weeks))
    i = weeks.index(pd.Timestamp(selected))
    first = max(0, min(i - size // 2, len(weeks) - size))
    return weeks[first:first + size]


# WHAT HAPPENED +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _flagged(level):
    """Whether a level is Watch or Warning.

    Parameters
    ----------
    level : str | None

    Returns
    -------
    bool
    """
    return level in FLAGGED


def _level_at(table, week, h):
    """The level forecast for `week` at horizon `h`, or None (no such week).

    Parameters
    ----------
    table : pandas.DataFrame
        season_table output.
    week : pandas.Timestamp
    h : int

    Returns
    -------
    str | None
    """
    row = table[table.week_start == pd.Timestamp(week)]
    return None if row.empty else row.iloc[0][f"level_{h}"]


def idle_flag_run(table, week, h=config.REPLAY_HORIZON):
    """Weeks just before `week` that were Watch/Warning without an outbreak.

    Counts back from the week before `week` over consecutive Watch/Warning
    weeks at horizon `h`, counting only the ones NOT above the outbreak line
    (false-alarm or background weeks). Weeks above the line are skipped, not
    counted: a flag that continues from an outbreak already under way is not
    background. Stops at the first Normal (or missing) week.

    Parameters
    ----------
    table : pandas.DataFrame
        season_table output.
    week : pandas.Timestamp
    h : int
        Horizon of the levels compared.

    Returns
    -------
    int
        0 when the week before was Normal (or missing).
    """
    above = table.set_index("week_start").above
    n, w = 0, pd.Timestamp(week) - pd.Timedelta(weeks=1)
    while _flagged(_level_at(table, w, h)):
        n += 0 if above.get(w, False) else 1
        w -= pd.Timedelta(weeks=1)
    return n


def lead_time(table, week, delay=config.CASES_REPORT_DELAY_WEEKS):
    """Lead over case reports for the outbreak week `week`, from the data.

    A forecast for week t made h weeks ahead is issued at the end of week
    t - h, while the health office learns of an outbreak starting in week t
    at the end of week t + delay (reports arrive late). So a Watch or Warning
    at horizon h gives h + delay weeks of lead, provided it was RAISED for
    this outbreak: at most config.REPLAY_BACKGROUND_FLAG_WEEKS idle flagged
    weeks (idle_flag_run, on the next-week level) came just before. A level
    that had been on for longer is background and no lead is claimed.

    Parameters
    ----------
    table : pandas.DataFrame
        season_table output.
    week : pandas.Timestamp
        The outbreak week.
    delay : int
        Reporting delay in weeks.

    Returns
    -------
    dict
        outcome: "warned" (raised at some horizon; lead = the longest),
        "background" (flagged, but already on for weeks: no lead claimed) or
        "missed" (Normal at every horizon); lead (int | None); horizon (the
        horizon behind the lead, else None); run (idle flagged weeks before,
        at horizon 1).
    """
    best = None
    flagged_any = False
    run = idle_flag_run(table, week)          # judged on the next-week level, for every horizon
    for h in sorted(config.ALERT_HORIZONS, reverse=True):
        if not _flagged(_level_at(table, week, h)):
            continue
        flagged_any = True
        if best is None and run <= config.REPLAY_BACKGROUND_FLAG_WEEKS:
            best = h
    if best is not None:
        return {"outcome": "warned", "lead": best + delay, "horizon": best, "run": run}
    return {"outcome": "background" if flagged_any else "missed", "lead": None, "horizon": None,
            "run": run}


def outbreak_run(table, week):
    """The unbroken run of weeks above the outbreak line that contains `week`.

    Parameters
    ----------
    table : pandas.DataFrame
        season_table output.
    week : pandas.Timestamp

    Returns
    -------
    pandas.DataFrame
        The consecutive above-line weeks around `week` (empty if `week` is
        not above the line).
    """
    above = table.set_index("week_start").above
    w = pd.Timestamp(week)
    if not above.get(w, False):
        return table.iloc[0:0]
    first, last = w, w
    while above.get(first - pd.Timedelta(weeks=1), False):
        first -= pd.Timedelta(weeks=1)
    while above.get(last + pd.Timedelta(weeks=1), False):
        last += pd.Timedelta(weeks=1)
    return table[table.week_start.between(first, last)]


def outbreak_runs(table):
    """Every unbroken run of weeks above the outbreak line.

    Parameters
    ----------
    table : pandas.DataFrame
        season_table output.

    Returns
    -------
    list[pandas.DataFrame]
        One slice of `table` per run, in date order.
    """
    runs, current = [], []
    for r in table.itertuples():
        if r.above:
            current.append(r.Index)
        elif current:
            runs.append(table.loc[current])
            current = []
    if current:
        runs.append(table.loc[current])
    return runs


def what_happened(table, city_total_cases=None):
    """The dated entries of "What happened", and the lead-time verdict.

    Entries (each only when the data has it), in date order:
    * rain: the wettest week of the season;
    * above: the first week above the outbreak line, with the level the app
      showed then at each horizon and the lead time (lead_time);
    * largest: the start of the outbreak run with the most cases, when it is
      not the first one (same facts as "above" plus the run's weeks and cases);
    * alert: the first week the level ROSE to Watch or Warning (the week
      before was Normal), if that is not the week above; "already on" when the
      season starts flagged;
    * warning: the first Warning week, if different from the weeks above;
    * peak_forecast: the week with the highest chance;
    * peak_cases: the week with the most cases, its multiple of that week's
      outbreak line and the levels then;
    * size: only when the outbreak run around the peak holds at least
      config.REPLAY_SIZE_NOTE_MIN_SHARE of the city's cases.

    Parameters
    ----------
    table : pandas.DataFrame
        season_table output (non-empty).
    city_total_cases : float | None
        The city's reported cases over the whole record (for "size").

    Returns
    -------
    tuple[list[dict], dict]
        (entries sorted by week, summary). Each entry: kind, week, facts.
        summary: lead_time output for the start of the LARGEST outbreak run
        (outcome "none" with no outbreak week), above_weeks, flagged_weeks
        (of those, flagged at horizon 1), largest_weeks, largest_cases.
    """
    entries = []
    h1 = config.REPLAY_HORIZON
    lvl, prob = f"level_{h1}", f"p_{h1}"

    wet = table.dropna(subset=["rain_mm"])
    if not wet.empty:
        top = wet.loc[wet.rain_mm.idxmax()]
        entries.append({"kind": "rain", "week": top.week_start,
                        "facts": {"mm": float(top.rain_mm),
                                  "heavy": bool(top.rain_mm >= config.REPLAY_HEAVY_RAIN_MM)}})

    above = table[table.above]
    runs = outbreak_runs(table)
    big = max(runs, key=lambda r: r.cases.sum()) if runs else None
    summary = {"outcome": "none", "lead": None, "horizon": None, "run": 0,
               "above_weeks": int(len(above)),
               "flagged_weeks": int(above[lvl].isin(FLAGGED).sum()),
               "largest_weeks": 0 if big is None else int(len(big)),
               "largest_cases": 0.0 if big is None else float(big.cases.sum())}

    def start_facts(row):
        """Facts about the first week of an outbreak run (levels and lead)."""
        lead = lead_time(table, row.week_start)
        return {"cases": float(row.cases), "threshold": float(row.threshold),
                "levels": {h: row[f"level_{h}"] for h in config.ALERT_HORIZONS},
                "chance": row[prob], **lead}

    first_above = above.iloc[0].week_start if not above.empty else None
    if first_above is not None:
        entries.append({"kind": "above", "week": first_above,
                        "facts": start_facts(above.iloc[0])})
    if big is not None:
        summary.update(lead_time(table, big.iloc[0].week_start))
        if big.iloc[0].week_start != first_above:
            entries.append({"kind": "largest", "week": big.iloc[0].week_start,
                            "facts": {**start_facts(big.iloc[0]), "weeks": int(len(big)),
                                      "run_cases": float(big.cases.sum())}})

    # First rise to Watch/Warning (or "already on" at the start of the season).
    flags = table[table[lvl].isin(FLAGGED)]
    if not flags.empty:
        rises = [r for r in flags.itertuples()
                 if not _flagged(_level_at(table, r.week_start - pd.Timedelta(weeks=1), h1))]
        start_flagged = _flagged(table.iloc[0][lvl])
        if start_flagged:
            entries.append({"kind": "alert", "week": table.iloc[0].week_start,
                            "facts": {"already": True, "level": table.iloc[0][lvl],
                                      "chance": table.iloc[0][prob]}})
        elif rises and rises[0].week_start != first_above:
            r = rises[0]
            entries.append({"kind": "alert", "week": r.week_start,
                            "facts": {"already": False, "level": getattr(r, lvl),
                                      "chance": getattr(r, prob)}})
    warn = table[table[lvl] == "Warning"]
    if not warn.empty and warn.iloc[0].week_start != first_above:
        w = warn.iloc[0]
        entries.append({"kind": "warning", "week": w.week_start,
                        "facts": {"chance": w[prob], "cases": float(w.cases)}})

    chance = table.dropna(subset=[prob])
    if not chance.empty:
        p = chance.loc[chance[prob].idxmax()]
        entries.append({"kind": "peak_forecast", "week": p.week_start,
                        "facts": {"chance": float(p[prob]), "level": p[lvl],
                                  "cases": float(p.cases), "above": bool(p.above)}})

    seen = table.dropna(subset=["cases"])
    if not seen.empty and seen.cases.max() > 0:
        c = seen.loc[seen.cases.idxmax()]
        facts = {"cases": float(c.cases), "threshold": None if pd.isna(c.threshold)
                 else float(c.threshold),
                 "times": None if pd.isna(c.threshold) or not c.threshold
                 else float(c.cases / c.threshold),
                 "levels": {h: c[f"level_{h}"] for h in config.ALERT_HORIZONS}}
        entries.append({"kind": "peak_cases", "week": c.week_start, "facts": facts})
        run = outbreak_run(table, c.week_start)
        if city_total_cases and not run.empty:
            share = float(run.cases.sum() / city_total_cases)
            if share >= config.REPLAY_SIZE_NOTE_MIN_SHARE:
                entries.append({"kind": "size", "week": run.week_start.max(),
                                "facts": {"cases": float(run.cases.sum()), "weeks": int(len(run)),
                                          "share": share, "total": float(city_total_cases),
                                          "first": run.week_start.min()}})
    entries.sort(key=lambda e: (pd.Timestamp(e["week"]), list(KIND_ORDER).index(e["kind"])))
    return entries, summary


KIND_ORDER = ("rain", "above", "largest", "alert", "warning", "peak_forecast", "peak_cases",
              "size")
