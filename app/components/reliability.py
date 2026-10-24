"""The Data reliability tab (DESIGN_V3 §3): "How reliable is this?".

Intro with the test period, one row per level (outbreak rate bar with a dashed
base-rate line, headline, detail), four summary tiles, "What it can't do", data
sources and APA 7th references. Every number comes from data/model_outputs/
(via src/reliability.py) or app/config.py, each with a small "source:" caption;
a number with no data shows "pending". The earlier technical tables (track
record, AUC comparison, lag curve, data rules, file status) stay under "More
details". Placeholder parts carry the "Baseline, model pending" label.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import config
from app.components.hover import style_hover
from app.components.ui import esc, level_badge
from app.content.references import REFERENCES
from app.content.reliability_text import cant_do, intro, row_text, tiles
from app.data import (city_groups, city_names, data_status, load_alerts, load_auc_table,
                      load_city_confidence, load_episodes, load_lag_curve, load_level_metrics,
                      load_processed, load_rain_gain, load_replay, load_reporting_flags)
from src.reliability import (auc_pair, calibration_top, case_counts, city_groups_named,
                             episode_share, event_peak, first_week_flagged, level_rows,
                             no_report_weeks, normal_blip_share, rain_gain_split, evaluation_period)
from src.views import lag_caption

AUC_NAMES = {
    "final_model": "Rain + recent cases (the model)",
    "rain_only": "Rain only",
    "seasonal_only": "Time of year only",
    "last_week_only": "Last week's cases only",
}


def data_rules(flags, cases):
    """The data rules, with their numbers computed from the data files.

    Parameters
    ----------
    flags : pandas.DataFrame
        reporting_flags.csv (adm3_pcode, week_start, flag).
    cases : pandas.DataFrame
        Observed weekly cases (mw_year, week_start).

    Returns
    -------
    list[str]
        One sentence per rule. Counts that cannot be computed read "pending".
    """
    n_flagged = config.PENDING_TEXT if flags is None else f"{len(flags):,}"
    years = (f"{int(cases.mw_year.min())}–{int(cases.mw_year.max())}"
             if cases is not None and not cases.empty else config.PENDING_TEXT)
    names = city_names()
    low = []
    if flags is not None and not flags.empty:
        # DOH year of a week = the year of its fourth day (MW1 can start in December).
        for (pcode, year), _ in flags[flags.flag == "low_reporting_year"].assign(
                year=lambda d: (pd.to_datetime(d.week_start) + pd.Timedelta(days=3)).dt.year
        ).groupby(["adm3_pcode", "year"]):
            low.append(f"{names.get(pcode, pcode)} {year}")
    low_text = f" and whole low-reporting years ({', '.join(sorted(low))})" if low else ""
    return [
        "Rainfall is NASA IMERG satellite rain, chosen over CHIRPS because CHIRPS missed "
        "Typhoon Washi (2011).",
        f"Weeks flagged as non-reporting ({n_flagged} city-weeks in all){low_text} are left "
        "out of the model and shown as \"No report\".",
        f"Data period: {years} (Project CCHAIN). Forecasts were tested on years the model had "
        "not seen (see the intro above).",
        "COVID years (2020–2022) had lower reporting; the model includes a COVID indicator.",
        "Reports arrive about a week late, so the cases shown are the latest reported week "
        "(two weeks before the forecast week), the same delay the model uses.",
    ]


# RENDER +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _banner(part):
    """ "Baseline, model pending" tag for a part, or "".

    Parameters
    ----------
    part : str
        Key of config.CONTRACT_FILES.

    Returns
    -------
    str
    """
    text = next(row["banner"] for row in data_status() if row["part"] == part)
    return f' <span class="leap-pending">{esc(text)}</span>' if text else ""


def lag_figure(lag):
    """Small line chart of the rain curve: risk in the weeks after heavy rain.

    Parameters
    ----------
    lag : pandas.DataFrame
        app.data.load_lag_curve output (lag_weeks, rr_p95, rr_p99); not empty.

    Returns
    -------
    plotly.graph_objects.Figure
        Two lines (heavy-rain week, typhoon-level week) against "weeks after
        the rain", with a dashed line at 1× (a typical week).
    """
    fig = go.Figure()
    for column, name, color in [("rr_p95", "After heavy rain", "#4FB3E6"),
                                ("rr_p99", "After a typhoon-level week", "#F2994A")]:
        fig.add_trace(go.Scatter(
            x=lag.lag_weeks, y=lag[column], mode="lines+markers", name=name,
            line=dict(color=color, width=2), marker=dict(size=6),
            hovertemplate=(f"<b>%{{x}} weeks after the rain</b><br>{name}: %{{y:.1f}}× a typical week"
                           "<extra></extra>")))
    fig.add_hline(y=1, line=dict(color="#8FA3B8", dash="dash", width=1))
    fig.update_layout(
        height=230, margin=dict(l=0, r=0, t=4, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color="#E8EEF5", size=12),
        legend=dict(orientation="h", y=1.18, x=0),
        xaxis=dict(title="Weeks after the rain", dtick=1, fixedrange=True,
                   gridcolor="rgba(255,255,255,0.08)"),
        yaxis=dict(title="Risk vs a typical week (×)", fixedrange=True,
                   gridcolor="rgba(255,255,255,0.08)", rangemode="tozero"))
    return style_hover(fig)


def render_details(horizon):
    """The technical tables: track record, AUC comparison, lag curve, rules, sources.

    Parameters
    ----------
    horizon : int
        The forecast week shown (config.HORIZONS).

    Returns
    -------
    None. Empty tables show a short "not available yet" line.
    """
    metrics, _ = load_level_metrics()
    st.html(f'<div class="leap-sec-h">How often each level was right (Week {horizon})'
            f'{_banner("level_metrics")}</div><div class="leap-sec-sub">In testing on '
            '2014–2022, the share of weeks at each level that became outbreak weeks.</div>')
    sub = metrics[metrics.horizon == horizon] if not metrics.empty else metrics
    if sub.empty:
        st.caption("Not available yet.")
    else:
        st.dataframe(pd.DataFrame({
            "Level": sub.alert_level,
            "Weeks at this level": sub.n_weeks.astype(int),
            "Became outbreak weeks (%)": (sub.hit_rate * 100).round(0),
            "vs a usual week": sub.lift.round(1).astype(str) + "×",
            "Outbreak weeks caught at this level or higher (%)": (sub.capture_rate * 100).round(0),
        }), hide_index=True)

    auc, _ = load_auc_table()
    st.html(f'<div class="leap-sec-h">Does rain help?{_banner("auc")}</div>'
            '<div class="leap-sec-sub">How well each approach ranks outbreak weeks above other '
            'weeks (technical name: AUC; 0.5 = guessing, 1.0 = perfect).</div>')
    sub = auc[auc.horizon == horizon] if not auc.empty else auc
    if sub.empty:
        st.caption("Not available yet.")
    else:
        st.dataframe(pd.DataFrame({
            "Approach": sub.model.map(AUC_NAMES).fillna(sub.model),
            "Compared": sub.scope.map({"all weeks": "all city-weeks together",
                                       "within city": "within each city (average)"}),
            "Score": sub.auc.round(2),
            "Source": sub.source.map({"model": "modeling team",
                                      "baseline": config.BASELINE_BANNER}),
        }).sort_values("Score", ascending=False), hide_index=True)

    lag, _ = load_lag_curve()
    st.html('<div class="leap-sec-h">How long risk stays raised after heavy rain</div>'
            f'<div class="leap-sec-sub">{esc(lag_caption(lag))}</div>')
    if not lag.empty:
        st.plotly_chart(lag_figure(lag), key="rel_lag_chart", theme=None,
                        config={"displayModeBar": False})
        st.dataframe(pd.DataFrame({
            "Weeks after heavy rain": lag.lag_weeks.astype(int),
            "Risk vs a typical week": lag.rr_p95.round(2).astype(str) + "×",
            "After a typhoon-level week": lag.rr_p99.round(2).astype(str) + "×",
        }), hide_index=True)

    st.html('<div class="leap-sec-h">Data rules</div><ul class="leap-rules">'
            + "".join(f"<li>{esc(rule)}</li>" for rule in
                      data_rules(load_reporting_flags(), load_processed()["cases"])
                      + [confidence_rule(city_groups(), city_names())])
            + "</ul>")
    render_data_sources()


def confidence_rule(groups, names):
    """The data rule that names the case-signal and lower-confidence cities.

    Parameters
    ----------
    groups : dict[str, str]
        app.data.city_groups output (from city_confidence.csv).
    names : dict[str, str]
        adm3_pcode -> city name.

    Returns
    -------
    str
        One sentence per non-empty group, with the config thresholds.
    """
    def listed(group):
        return ", ".join(sorted(names.get(p, p) for p, g in groups.items() if g == group))

    parts = []
    if listed("case_signal"):
        parts.append(f"{listed('case_signal')} had fewer than "
                     f"{config.CASE_SIGNAL_MAX_OUTBREAK_WEEKS} outbreak weeks in the "
                     "2014–2022 test, too few to forecast a level, so they show \"Case signal "
                     "only\": the weekly case count is the signal.")
    if listed("lower"):
        parts.append(f"{listed('lower')} are marked \"lower confidence\": in testing, the "
                     "model ranked their outbreak weeks less well (AUC below "
                     f"{config.LOWER_CONFIDENCE_AUC:.2f}).")
    return " ".join(parts) + " Both groups come from the modeling team's per-city test."


def render_data_sources():
    """Where the alerts and every contract file come from (was the header chip).

    Returns
    -------
    None. Lists the model version, the Watch / Warning cut-offs (and whether
    they are placeholders) and one line per contract file.
    """
    _, info = load_alerts()
    is_model = info["kind"] == "model"
    cut = info.get("cutoffs", config.LEVEL_CUTOFFS)
    model = (f"Alert levels come from the modeling team's model ({info['model_version']}): a "
             "negative binomial regression with distributed-lag IMERG rainfall terms, each "
             "city's recent case level and its recent reported cases. Typhoon Washi's outbreak "
             "weeks in Cagayan de Oro are set aside in training, so one event does not set that "
             "city's seasonal pattern. It gives the chance that each week is an outbreak week "
             "(above the DOH epidemic threshold)." if is_model else
             "Baseline, model pending: until the modeling team's alerts arrive, the chance of "
             "an outbreak week is how often the same weeks of earlier years were above the "
             "threshold. It does not use rainfall.")
    if info.get("cutoff_source") == "delivered":
        cutoffs = f"Levels come from the modeling team: {config.LEVEL_RULE_TEXT}."
    else:
        cutoffs = (f"Watch from a {cut['Watch']:.0%} chance, Warning from {cut['Warning']:.0%}"
                   + (" (placeholder cut-offs until the modeling team sets them)."
                      if info.get("cutoff_source") != "model" else "."))
    rows = "".join(f"<li><b>{esc(row['label'])}</b>: {esc(row['banner'] or 'modeling team')}"
                   "</li>" for row in data_status())
    st.html('<div class="leap-sec-h">Data sources</div><ul class="leap-rules">'
            f"<li>{esc(model)}</li><li>{esc(cutoffs)}</li>"
            "<li>Reported cases: DOH PIDSR via Project CCHAIN, 2008–2022. Rainfall: NASA "
            "IMERG. Flood hazard: Project NOAH. Population: WorldPop.</li>"
            f"{rows}</ul>")


# PAGE ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def italics(text):
    """HTML for a reference: text between *asterisks* becomes <i>…</i>.

    Parameters
    ----------
    text : str
        Plain text with optional *italic* parts.

    Returns
    -------
    str
        Escaped HTML.
    """
    parts = text.split("*")
    return "".join(f"<i>{esc(part)}</i>" if i % 2 else esc(part) for i, part in enumerate(parts))


def source_html(text):
    """A small "source:" caption.

    Parameters
    ----------
    text : str

    Returns
    -------
    str
    """
    return f'<div class="leap-src">source: {esc(text)}</div>'


def level_row_html(row, head, detail):
    """One level row: badge, headline, detail, and the outbreak-rate bar.

    Parameters
    ----------
    row : dict
        src.reliability.level_rows entry.
    head, detail : str
        app.content.reliability_text.row_text output.

    Returns
    -------
    str
        The bar runs 0 to config.RELIABILITY_BAR_MAX of weeks; the dashed line
        is the share of all weeks that are outbreak weeks.
    """
    top = config.RELIABILITY_BAR_MAX
    rate_text = f"{row['rate']:.1%}" if row["rate"] < 0.1 else f"{row['rate']:.0%}"
    width = min(100.0, 100 * row["rate"] / top)
    base = min(100.0, 100 * row["base_rate"] / top)
    return (f'<div class="leap-rel-row"><div class="leap-rel-text">{level_badge(row["level"])}'
            f'<div class="leap-rel-head">{esc(head)}</div>'
            f'<div class="leap-rel-detail">{esc(detail)}</div></div>'
            f'<div class="leap-rel-bar"><div class="leap-rel-track">'
            f'<i style="width:{width:.1f}%;background:{config.LEVEL_COLORS[row["level"]]}"></i>'
            f'<b style="left:{base:.1f}%"></b></div>'
            f'<span>{rate_text}</span></div></div>')


def tile_html(tile):
    """One summary tile.

    Parameters
    ----------
    tile : dict
        app.content.reliability_text.tiles entry (big, sub, extra, source).

    Returns
    -------
    str
    """
    extra = f'<div class="leap-tile-extra">{esc(tile["extra"])}</div>' if tile["extra"] else ""
    return (f'<div class="leap-rel-tile"><div class="leap-rel-big">{esc(tile["big"])}</div>'
            f'<div class="leap-rel-sub">{esc(tile["sub"])}</div>{extra}'
            f'{source_html(tile["source"])}</div>')


def render_reliability(horizon):
    """Draw the Data reliability tab.

    Parameters
    ----------
    horizon : int
        The forecast week selected on the Overview; the page starts there and
        has its own switch (weeks ahead).

    Returns
    -------
    None. Missing data shows "pending" instead of a number.
    """
    ss = st.session_state
    metrics, _ = load_level_metrics()
    auc, _ = load_auc_table()
    alerts, _ = load_alerts()
    names = city_names()
    cases = load_processed()["cases"]
    episodes, rain_gain = load_episodes(), load_rain_gain()
    ss.setdefault("reliability_h", horizon if horizon in config.HORIZONS else config.HORIZONS[0])

    with st.container(horizontal=True, vertical_alignment="bottom", wrap=False):
        title = st.empty()
        h = st.segmented_control("Weeks ahead", config.HORIZONS, key="reliability_h",
                                 required=True,
                                 format_func=lambda x: config.HORIZON_NAMES[x])
        title.html('<div class="leap-page-h">How reliable is this?</div>')
    when = config.HORIZON_NAMES[h].lower()
    period = evaluation_period(alerts, metrics, h)
    st.html(f'<div class="leap-rel-intro">{esc(intro(period))}'
            f' Showing the forecast {esc(when)}.</div>'
            + source_html("level_metrics.csv: n_weeks; alerts.csv: target_week"))

    rows = level_rows(metrics, h)
    base_text = f"{rows[0]['base_rate']:.0%}" if rows else config.PENDING_TEXT
    left, right = st.columns([2.2, 1], gap="medium")
    with left, st.container(key="relcard"):
        st.html('<div class="leap-card-title">What each level has meant</div>'
                '<div class="leap-card-sub">Share of weeks that became <b>outbreak weeks</b> '
                "(reported cases above the city's DOH epidemic threshold). The dashed line is "
                f"how often any week was one ({esc(base_text)}). Bars run 0–"
                f"{config.RELIABILITY_BAR_MAX:.0%} of weeks.</div>")
        if not rows:
            st.html(f'<div class="leap-empty">Track record by level: '
                    f'{config.PENDING_TEXT}.</div>')
        for row in rows:
            head, detail = row_text(
                row, episode_share(episodes, h, "Watch"), normal_blip_share(episodes, h), when)
            st.html(level_row_html(row, head, detail))
        st.html(source_html("level_metrics.csv: hit_rate, lift, base_rate, n_weeks, "
                            "capture_rate, n_outbreaks; episodes.csv: share; "
                            "config: level rule (modeling report, stage 5d)"))
    with right:
        grid = "".join(tile_html(t) for t in tiles(
            rows, first_week_flagged(episodes, h), auc_pair(auc, h),
            rain_gain_split(rain_gain), h))
        st.html(f'<div class="leap-rel-tiles">{grid}</div>')

    first_year = period["first_year"]
    bullets = cant_do(
        rows, case_counts(cases, first_year), calibration_top(alerts, h),
        city_groups_named(load_city_confidence()[0], names),
        no_report_weeks(load_reporting_flags(), cases),
        event_peak(load_replay()[0], config.REPLAY_EVENT_WASHI))
    left, right = st.columns([1.6, 1], gap="medium")
    with left, st.container(key="cantdo"):
        st.html('<div class="leap-card-title">What it can\'t do</div>'
                + "".join(f'<div class="leap-cant"><b>{esc(b["title"])}.</b> {esc(b["text"])}'
                          f'{source_html(b["source"])}</div>' for b in bullets))
    with right, st.container(key="relsources"):
        years = (f"{int(cases.mw_year.min())}–{int(cases.mw_year.max())}"
                 if not cases.empty else config.PENDING_TEXT)
        st.html('<div class="leap-card-title">Data sources</div><ul class="leap-rel-sources">'
                f"<li>Leptospirosis cases: DOH PIDSR, {esc(years)}, via Project CCHAIN</li>"
                "<li>Rainfall: NASA IMERG satellite rainfall (the model used the Late version; "
                "the Overview shows Final)</li>"
                "<li>Flood hazard: Project NOAH hazard maps</li>"
                "<li>Population: WorldPop</li></ul>"
                + source_html("cases_weekly.csv: mw_year; config; references below"))

    with st.container(key="references"):
        st.html('<div class="leap-card-title">References</div><div class="leap-card-sub">APA '
                '7th edition.</div>'
                + "".join(f'<div class="leap-ref">{italics(r)}</div>' for r in REFERENCES))

    with st.expander(config.RELIABILITY_MORE_LABEL, key="rel_more"):
        render_details(h)
