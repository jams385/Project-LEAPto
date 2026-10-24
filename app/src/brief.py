"""Markdown "city brief" for the panel's Download button.

A short, printable summary a health office can forward: the alert level and
what it means, its track record, the context numbers and the suggested
actions, with the data period and caveats always stated. It never states a
predicted number of cases.
"""

import pandas as pd

from app import config
from src.views import fmt_times, level_sentence, risk_vs_usual

# FORMATTING +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _num(value, digits=1, suffix=""):
    """Format a number for the brief.

    Parameters
    ----------
    value : float | None
    digits : int
    suffix : str

    Returns
    -------
    str
        "not available" for None/NaN.
    """
    if value is None or pd.isna(value):
        return "not available"
    return f"{value:.{digits}f}{suffix}"


# BRIEF ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def build_city_brief(city, horizons, actions, *, role, origin_week, source_label,
                     levels, horizon=1, barangays=None, lag_text=None, reasons=()):
    """Write the city brief as Markdown.

    Parameters
    ----------
    city : Mapping
        One src.views snapshot row (city_name, province, region, alert_level,
        forecast_level, confidence, rank, outbreak_prob, cases_week,
        latest_cases, latest_flag, unusual_at, rain_week_mm, rain_status,
        hazard_pct, threshold, target_week).
    horizons : pandas.DataFrame
        src.views.city_horizons output (may be empty).
    actions : list[dict]
        app.content.actions.select_actions output ({"text", "because"}).
    role : str
        "Resident" or "Health office" (named in the brief).
    origin_week : Timestamp
        Forecast origin.
    source_label : str
        e.g. "Baseline, model pending" or "Model: dlnm-nb-pooled_ar".
    levels : dict
        src.views.level_descriptions output (meaning and track record).
    horizon : int
        Which forecast week `city` describes (1 = next week).
    barangays : pandas.DataFrame | None
        src.views.top_flood_barangays output (brgy_name, high_hazard_pct).
    lag_text : str | None
        The rain -> risk finding (src.views.lag_caption).
    reasons : sequence of Reason
        app.logic.reasons.city_reasons output ("What we're seeing").

    Returns
    -------
    str
        Markdown text. Never raises on missing values; they read
        "not available".
    """
    origin = pd.Timestamp(origin_week)
    target = city.get("target_week")
    if target is None or pd.isna(target):  # city has no forecast row this week
        target = origin + pd.Timedelta(weeks=horizon - 1)
    target = pd.Timestamp(target)
    level = city["alert_level"] or config.CASE_SIGNAL_LEVEL
    info = levels.get(level, {})
    name = config.HORIZON_NAMES.get(horizon, f"In {horizon} weeks")
    heading = f"## {name} (week of {target:%b} {target.day}, {target.year})"
    flag = city.get("latest_flag")
    group = config.CONFIDENCE_NOTES.get(city.get("confidence") or "standard")
    cases_week = city.get("cases_week")
    cases_from = (f" (week from {pd.Timestamp(cases_week):%b} {pd.Timestamp(cases_week).day})"
                  if cases_week is not None and not pd.isna(cases_week) else "")
    unusual = city.get("unusual_at")
    lines = [
        f"# {city['city_name']}: leptospirosis alert brief",
        "",
        f"*Forecast made with data to the week of {origin:%B} {origin.day}, "
        f"{origin.year}*",
        f"*{city['province']}, {city['region']}. Confidence: {group}*",
        f"*Source: {source_label}. Data: Project CCHAIN, DOH PIDSR 2008–2022. "
        f"{config.FORECAST_SCOPE_NOTE}.*",
        "",
        heading,
        f"- Alert level: **{level}**. "
        + (level_sentence(level, info, city.get("outbreak_prob"), unusual) if info else ""),
    ]
    if level == config.CASE_SIGNAL_LEVEL and city.get("forecast_level"):
        lines.append(f"- Model estimate (low confidence): {city['forecast_level']}")
    risk = risk_vs_usual(level, city.get("outbreak_prob"), info.get("base_rate"))
    if risk:
        lines.append(f"- {risk} (compared with a usual week)")
    if info.get("track"):
        lines.append(f"- Track record: {info['track']}")
    lines += [
        f"- Rank: #{int(city['rank'])} of 12 monitored cities by chance of an outbreak week",
        f"- Outbreak week if more than {_num(city.get('threshold'))} reported cases "
        "(DOH epidemic threshold)",
        f"- Cases in the latest reported week{cases_from}: "
        f"{_num(city.get('latest_cases'), 0)}"
        + (f" (unusual at {int(unusual)} or more)"
           if unusual is not None and not pd.isna(unusual) else "")
        + (" (week flagged as non-reporting)" if flag else ""),
        f"- Rainfall last week (NASA IMERG): {_num(city.get('rain_week_mm'), 0, ' mm')}"
        + (f" ({city['rain_status'].lower()})" if city.get("rain_status") else ""),
        f"- High flood-hazard area: {_num(city.get('hazard_pct'), 0, '%')} of the city "
        "(100-year flood, Project NOAH)",
        "",
        "## Forecast by week",
    ]
    if lag_text:
        lines.append(f"*{lag_text}*")
    if horizons.empty:
        lines.append("- No forecast available for this week.")
    base = info.get("base_rate")
    for h in horizons.itertuples():
        week = pd.Timestamp(h.target_week)
        times = (fmt_times(min(h.outbreak_prob / base, config.MAX_RR_SHOWN))
                 if base and h.alert_level in ("Watch", "Warning")
                 and not pd.isna(h.outbreak_prob) else None)
        when = config.HORIZON_NAMES.get(int(h.horizon), f"In {h.horizon} weeks")
        lines.append(f"- {when} ({week:%b} {week.day}): {h.alert_level}"
                     + (f", ≈{times} a usual week" if times else ""))
    if barangays is not None and not barangays.empty:
        lines += ["", "## Most flood-prone barangays (Project NOAH, 100-year flood)",
                  "*Where to focus advisories and doxycycline PEP first.*"]
        lines += [f"{i}. {b.brgy_name}: {b.high_hazard_pct:.0f}% of its area is high hazard"
                  for i, b in enumerate(barangays.itertuples(), 1)]
    if reasons:
        lines += ["", "## What we're seeing (observed data)"]
        lines += [f"- {r.text} *Source: {r.source}.*" for r in reasons]
    lines += ["", f"## Suggested actions ({role})"]
    lines += [f"- {a['text']} Because {a['because']}." for a in actions]
    lines += [
        "",
        "---",
        "Estimated chance of an outbreak week, not a diagnosis and not a count of people. "
        "Reported cases are associated with rainfall and flooding; they do not show cause. "
        "Anyone with fever after wading in floodwater should see a health worker.",
    ]
    return "\n".join(lines) + "\n"
